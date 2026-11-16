"""Sends violations from the camera worker to the API server.

Reports go through a queue handled by a background thread, so a slow or
unreachable server never pauses detection. A report that fails is retried with
growing waits; reports are sent in order, so "ended" never overtakes "started".
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise

RETRY_DELAYS = (1, 2, 5, 10, 30)  # seconds; then the report is given up on


def _impact_fields(impact) -> dict:
    return {
        "impact_score": str(impact.score),
        "impact_level": impact.level,
        "impact_parts": json.dumps(impact.parts()),
    }


@dataclass
class _Job:
    path: str
    data: dict
    #: (form field, file, content type) for each file to upload.
    files: list[tuple[str, Path, str]] = field(default_factory=list)
    done: threading.Event = field(default_factory=threading.Event)


class ViolationReporter:
    def __init__(
        self,
        api_url: str,
        camera_name: str,
        latitude: float | None = None,
        longitude: float | None = None,
        internal_key: str = "",
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
        transport: httpx.BaseTransport | None = None,
        ca_file: str = "",
    ):
        self.camera_name = camera_name
        self.latitude = latitude
        self.longitude = longitude
        self._retry_delays = retry_delays
        headers = {"x-internal-key": internal_key} if internal_key else {}
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers=headers,
            timeout=20,
            transport=transport,
            # For a server using its own (self-signed) certificate: trust
            # exactly that certificate, rather than turning checking off.
            verify=ca_file or True,
        )
        self._queue: queue.Queue[_Job | None] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.sent = 0
        self.failed = 0

    # ------------------------------------------------------------------ public

    def violation_started(
        self,
        client_ref: str,
        photo: Path,
        zone_id: str,
        zone_name: str,
        vehicle_class: str,
        confidence: float,
        parked_seconds: float,
        started_at: str,
        plate_text: str | None = None,
        plate_confidence: float | None = None,
        plate_photo: Path | None = None,
        impact=None,
        box: tuple[float, float, float, float] | None = None,
    ) -> None:
        data = {
            "client_ref": client_ref,
            "camera_name": self.camera_name,
            "zone_id": zone_id,
            "zone_name": zone_name,
            "vehicle_class": vehicle_class,
            "confidence": str(confidence),
            "parked_seconds": str(parked_seconds),
            "started_at": started_at,
        }
        if self.latitude is not None and self.longitude is not None:
            data["latitude"] = str(self.latitude)
            data["longitude"] = str(self.longitude)
        if impact is not None:
            data.update(_impact_fields(impact))
        if box is not None:
            # Normalised x1,y1,x2,y2: where in the picture the vehicle was.
            data["box"] = ",".join(f"{min(1.0, max(0.0, v)):.4f}" for v in box)
        files = [("photo", Path(photo), "image/jpeg")]
        if plate_text:
            data["plate_text"] = plate_text
            if plate_confidence is not None:
                data["plate_confidence"] = str(plate_confidence)
        if plate_photo is not None:
            files.append(("plate_photo", Path(plate_photo), "image/jpeg"))
        self._queue.put(_Job("/internal/violations", data, files))

    def violation_ended(self, client_ref: str, duration_seconds: float, ended_at: str) -> None:
        self._queue.put(
            _Job(
                f"/internal/violations/{client_ref}/ended",
                {"duration_seconds": str(duration_seconds), "ended_at": ended_at},
            )
        )

    def impact_changed(self, client_ref: str, impact) -> None:
        """The violation is holding up traffic more than last reported."""
        self._queue.put(_Job(f"/internal/violations/{client_ref}/impact", _impact_fields(impact)))

    def clip_ready(self, client_ref: str, clip: Path) -> None:
        self._queue.put(
            _Job(f"/internal/violations/{client_ref}/clip", {}, [("clip", Path(clip), "video/mp4")])
        )

    def close(self, timeout: float = 30.0) -> None:
        """Send what is still queued (up to ``timeout`` seconds), then stop."""
        self._queue.put(None)
        self._thread.join(timeout=timeout)
        self._stop.set()
        self._client.close()

    # ---------------------------------------------------------------- internal

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            if self._deliver(job):
                self.sent += 1
            else:
                self.failed += 1
                logger.error("Gave up reporting %s after repeated failures", job.path)

    def _deliver(self, job: _Job) -> bool:
        for delay in (0, *self._retry_delays):
            if delay and self._stop.wait(delay):
                return False
            outcome = self._post(job)
            if outcome == "ok":
                return True
            if outcome == "rejected":
                return False  # the server understood and said no; retrying is pointless
        return False

    def _post(self, job: _Job) -> str:
        try:
            with ExitStack() as stack:
                files = {
                    name: (path.name, stack.enter_context(path.open("rb")), kind)
                    for name, path, kind in job.files
                }
                response = self._client.post(job.path, data=job.data, files=files or None)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("Report to %s failed: %s", job.path, type(exc).__name__)
            return "retry"
        if response.status_code < 300:
            return "ok"
        if response.status_code >= 500:
            logger.warning("Report to %s failed: HTTP %d", job.path, response.status_code)
            return "retry"
        logger.error("Report to %s rejected: HTTP %d %s", job.path, response.status_code, response.text[:200])
        return "rejected"
