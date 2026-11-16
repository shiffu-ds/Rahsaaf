"""Phase 2 runner: watch a live camera for illegally parked vehicles.

    uv run python -m worker.run_live SOURCE --zones zones.json

SOURCE is an RTSP or HTTP stream address, a webcam number (0 is the first
webcam), or a video file, which is played at its own speed like a camera.

Writes, into the output folder:

* ``violations.jsonl``  one line when a violation starts, one when it ends
* ``violation_N.jpg``   the frame on which violation N was confirmed
* ``violation_N.mp4``   a clip from a few seconds before to a few seconds after

Stop with Ctrl+C, or with q in the preview window when --show is used.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2

from worker.congestion import ImpactMonitor
from worker.detector import VehicleTracker
from worker.evidence import ClipRecorder
from worker.overlay import draw_vehicles, draw_zones
from worker.parking_state import ParkingMonitor, ViolationEvent
from worker.plates import PlateVoter, crop_vehicle
from worker.reporter import ViolationReporter
from worker.stream import FrameReader, parse_source
from worker.zones import Zone, drop_ignored, load_ignore_areas, load_zones

DEFAULT_WEIGHTS = "models/yolo11n_openvino_model"
WINDOW = "RahSaaf live (q to quit)"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalised(box, frame_size) -> tuple[float, float, float, float] | None:
    """A pixel box as fractions of the frame, or None before the first frame."""
    width, height = frame_size
    if not width or not height:
        return None
    x1, y1, x2, y2 = box
    return (x1 / width, y1 / height, x2 / width, y2 / height)


def run(
    source: str | int,
    zones: list[Zone],
    output_dir: str,
    weights: str = DEFAULT_WEIGHTS,
    image_size: int | tuple[int, int] = (256, 416),
    target_fps: float = 5.0,
    max_width: int = 960,
    show: bool = False,
    duration: float | None = None,
    report_every: float = 10.0,
    reporter: ViolationReporter | None = None,
    plate_reader=None,
    plate_frames: int = 6,
    plate_seconds: float = 3.0,
    impact_every: float = 15.0,
    ignore=(),
) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "violations.jsonl"

    tracker = VehicleTracker(weights, image_size=image_size)
    tracker.warm_up()
    monitor = ParkingMonitor(zones)
    recorder = ClipRecorder()
    reader = FrameReader(source).start()
    zone_names = {zone.id: zone.name for zone in zones}
    refs: dict[int, str] = {}  # violation number in this run -> ID sent to the server
    clip_refs: dict[Path, str] = {}
    # Violations whose plate is still being read. The report to the server
    # waits for this (a second or so), so the alert can carry the plate.
    awaiting_plate: dict[int, dict] = {}
    plates_read = 0

    # Traffic impact of each open violation: the worst seen so far, and what
    # the server was last told.
    impact_monitor = ImpactMonitor(zones)
    open_impacts: dict[int, dict] = {}
    frame_size = [0, 0]

    def measure_impact(violation_id: int, now: float):
        """Impact right now of an open violation, or None if it cannot be measured."""
        status = next(
            (s for s in monitor.statuses(now) if s.violation_id == violation_id), None
        )
        if status is None or not frame_size[0]:
            return None
        return impact_monitor.score(
            now, status.zone_id, status.box, frame_size[0], frame_size[1], status.track_id
        )

    def check_impacts(now: float) -> None:
        """Every so often, see whether an open violation has got worse."""
        for violation_id, item in open_impacts.items():
            if now < item["next_check"] or violation_id in awaiting_plate:
                continue
            item["next_check"] = now + impact_every
            current = measure_impact(violation_id, now)
            if current is None:
                continue
            if item["peak"] is None or current.score > item["peak"].score:
                item["peak"] = current
            peak = item["peak"]
            worse = peak.score - item["sent_score"] >= 0.1 or (
                peak.level != item["sent_level"] and peak.score > item["sent_score"]
            )
            if worse and reporter and violation_id in refs:
                reporter.impact_changed(refs[violation_id], peak)
                item["sent_score"], item["sent_level"] = peak.score, peak.level
                print(
                    f"[{_now_iso()}] violation {violation_id} traffic impact now "
                    f"{peak.level} ({peak.score:.2f})"
                )

    def send_started(violation_id: int) -> None:
        """Finish plate reading for a violation and report it to the server."""
        nonlocal plates_read
        item = awaiting_plate.pop(violation_id)
        event, name = item["event"], f"violation_{violation_id}"
        plate = item["voter"].result() if item["voter"] else None

        plate_photo = None
        if plate is not None:
            if plate.image is not None and plate.image.size:
                plate_photo = out / f"{name}_plate.jpg"
                cv2.imwrite(str(plate_photo), plate.image)
            plates_read += plate.readable
            log(
                {
                    "event": "plate",
                    "violation_id": violation_id,
                    "plate": plate.text,
                    "confidence": plate.confidence,
                    "reads": plate.reads,
                    "agreeing": plate.agreeing,
                    "reason": plate.reason,
                }
            )
            shown = plate.text or f"unreadable ({plate.reason})"
            print(f"[{_now_iso()}] violation {violation_id} plate: {shown}")

        impact = measure_impact(violation_id, item["now"])
        if impact is not None:
            open_impacts[violation_id].update(
                peak=impact, sent_score=impact.score, sent_level=impact.level
            )
            log({"event": "impact", "violation_id": violation_id, "level": impact.level,
                 "score": impact.score, **impact.parts()})

        if reporter:
            reporter.violation_started(
                refs[violation_id],
                photo=out / f"{name}.jpg",
                zone_id=event.zone_id,
                zone_name=zone_names.get(event.zone_id, ""),
                vehicle_class=event.vehicle_class,
                confidence=event.confidence,
                parked_seconds=round(event.confirmed_at - event.stopped_at, 1),
                started_at=item["started_at"],
                plate_text=plate.text if plate else None,
                plate_confidence=plate.confidence if plate and plate.readable else None,
                plate_photo=plate_photo,
                impact=impact,
                box=_normalised(event.box, frame_size),
            )

    def read_plates(now: float, full_frame, scale: float) -> None:
        """Give each waiting violation one more look at its vehicle's plate."""
        # Looked up by violation, not track ID: the tracker may renumber a vehicle.
        boxes = {s.violation_id: s.box for s in monitor.statuses(now) if s.visible}
        for violation_id in list(awaiting_plate):
            item = awaiting_plate[violation_id]
            item["now"] = now
            box = boxes.get(violation_id)
            if box is not None:
                item["voter"].add(plate_reader.read(crop_vehicle(full_frame, box, scale)))
            item["frames_left"] -= 1
            done = item["frames_left"] <= 0 or now >= item["deadline"] or item["voter"].settled
            if done:
                send_started(violation_id)

    def log(entry: dict) -> None:
        with log_path.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")

    def handle(event: ViolationEvent, now: float, frame=None) -> None:
        name = f"violation_{event.violation_id}"
        if event.kind == "started":
            cv2.imwrite(str(out / f"{name}.jpg"), frame)
            recorder.start_clip(now, out / f"{name}.mp4")
            refs[event.violation_id] = uuid.uuid4().hex
            clip_refs[out / f"{name}.mp4"] = refs[event.violation_id]
            awaiting_plate[event.violation_id] = {
                "event": event,
                "started_at": _now_iso(),
                "now": now,
                "voter": PlateVoter() if plate_reader else None,
                "frames_left": plate_frames,
                "deadline": now + plate_seconds,
            }
            impact_monitor.violation_started(event.zone_id)
            open_impacts[event.violation_id] = {
                "zone_id": event.zone_id,
                "peak": None,
                "sent_score": 0.0,
                "sent_level": "Low",
                "next_check": now + impact_every,
            }
            if plate_reader is None:
                send_started(event.violation_id)  # nothing to wait for
            log(
                {
                    "event": "started",
                    "violation_id": event.violation_id,
                    "time": _now_iso(),
                    "zone_id": event.zone_id,
                    "vehicle_class": event.vehicle_class,
                    "confidence": event.confidence,
                    "parked_seconds": round(event.confirmed_at - event.stopped_at, 1),
                    "box": [round(v, 1) for v in event.box],
                    "photo": f"{name}.jpg",
                    "clip": f"{name}.mp4",
                }
            )
            print(
                f"[{_now_iso()}] VIOLATION {event.violation_id}: "
                f"{event.vehicle_class} in zone {event.zone_id}"
            )
        else:
            log(
                {
                    "event": "ended",
                    "violation_id": event.violation_id,
                    "time": _now_iso(),
                    "duration_seconds": round(event.duration_seconds, 1),
                }
            )
            if event.violation_id in awaiting_plate:
                send_started(event.violation_id)  # "started" must reach the server first
            closed = open_impacts.pop(event.violation_id, None)
            if closed:
                impact_monitor.violation_ended(closed["zone_id"])
                peak = closed["peak"]
                if peak and peak.score > closed["sent_score"] and reporter and event.violation_id in refs:
                    reporter.impact_changed(refs[event.violation_id], peak)
            if reporter and event.violation_id in refs:
                reporter.violation_ended(
                    refs[event.violation_id], round(event.duration_seconds, 1), _now_iso()
                )
            print(
                f"[{_now_iso()}] violation {event.violation_id} ended after "
                f"{event.duration_seconds:.0f}s"
            )

    def clips_done(paths: list[Path]) -> None:
        for path in paths:
            if reporter and path in clip_refs:
                reporter.clip_ready(clip_refs[path], path)

    started = time.monotonic()
    min_gap = 1.0 / target_fps
    last_number = 0
    last_processed = 0.0
    last_report = started
    last_frame_at = started

    processed = violations = 0
    window_processed = 0
    window_worst_delay = worst_delay = 0.0
    width = height = 0

    print(f"Watching {source}. Waiting for the first frame...")
    try:
        while True:
            now = time.monotonic()
            elapsed = now - started
            if duration is not None and elapsed >= duration:
                break
            if reader.ended:
                print("The video file has ended.")
                break

            frame = reader.latest()
            fresh = frame is not None and frame.number != last_number
            if not fresh or now - last_processed < min_gap:
                if now - last_frame_at > 10 and now - last_report > report_every:
                    print(
                        f"[{_now_iso()}] No frames for {now - last_frame_at:.0f}s. "
                        f"Reconnect attempts so far: {reader.reconnects}"
                    )
                    last_report = now
                time.sleep(0.005)
                continue

            last_number = frame.number
            last_processed = last_frame_at = now

            full_frame = image = frame.image
            src_h, src_w = image.shape[:2]
            if src_w > max_width:
                image = cv2.resize(
                    image,
                    (max_width, int(src_h * max_width / src_w)),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                image = image.copy()  # never draw on the reader's own frame
            height, width = image.shape[:2]

            observations = drop_ignored(tracker.track(image), ignore, width, height)
            events = monitor.update(elapsed, observations, width, height)
            frame_size[:] = width, height
            if impact_monitor.enabled:
                impact_monitor.update(elapsed, observations, width, height)
                check_impacts(elapsed)
            if awaiting_plate:
                # Read from the full-size frame, before anything is drawn on it.
                read_plates(elapsed, full_frame, src_w / width)

            draw_zones(image, zones, ignore)
            draw_vehicles(image, observations, monitor.statuses(elapsed))
            for event in events:
                handle(event, elapsed, image)
                violations += event.kind == "started"
            clips_done(recorder.add(elapsed, image))

            # How old the picture was by the time we finished with it. If this
            # keeps growing, the machine is not keeping up with the camera.
            delay = time.monotonic() - frame.captured_at
            window_worst_delay = max(window_worst_delay, delay)
            worst_delay = max(worst_delay, delay)
            processed += 1
            window_processed += 1

            if show:
                cv2.imshow(WINDOW, image)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if now - last_report >= report_every:
                span = now - last_report
                print(
                    f"[{_now_iso()}] {window_processed / span:.1f} frames/s processed, "
                    f"worst delay {window_worst_delay * 1000:.0f} ms, "
                    f"{len(monitor.statuses(elapsed))} vehicle(s) in zones, "
                    f"reconnects {reader.reconnects}"
                )
                last_report = now
                window_processed = 0
                window_worst_delay = 0.0
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        elapsed = time.monotonic() - started
        for violation_id in list(awaiting_plate):
            send_started(violation_id)
        for event in monitor.flush(elapsed):
            handle(event, elapsed)
        clips_done(recorder.close())
        reader.stop()
        if reporter:
            reporter.close()
        if show:
            cv2.destroyAllWindows()

    return {
        "seconds": round(elapsed, 1),
        "frames_processed": processed,
        "processed_frames_per_second": round(processed / elapsed, 2) if elapsed else 0,
        "worst_delay_ms": round(worst_delay * 1000),
        "violations": violations,
        "reconnects": reader.reconnects,
        "plates_read": plates_read,
        "reports_sent": reporter.sent if reporter else 0,
        "reports_failed": reporter.failed if reporter else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", help="stream URL, webcam number, or video file")
    parser.add_argument("--zones", required=True, help="zones JSON from tools/draw_zone.py")
    parser.add_argument("--out", default="data/live", help="output folder")
    parser.add_argument("--weights", default=DEFAULT_WEIGHTS)
    parser.add_argument(
        "--imgsz",
        type=int,
        nargs="+",
        default=[256, 416],
        help="model input size: one number, or height width",
    )
    parser.add_argument("--fps", type=float, default=5.0, help="frames to analyse per second")
    parser.add_argument("--grace", type=float, help="override every zone's grace period, seconds")
    parser.add_argument("--show", action="store_true", help="open a live preview window")
    parser.add_argument("--duration", type=float, help="stop after this many seconds")
    parser.add_argument(
        "--api",
        help="API server address, e.g. http://127.0.0.1:8000. Without it, "
        "violations are only saved locally and no alert is sent.",
    )
    parser.add_argument(
        "--ca",
        default="",
        help="certificate file to trust when --api is an https address with "
        "its own certificate, e.g. data/tls/cert.pem",
    )
    parser.add_argument(
        "--no-plates", action="store_true", help="do not try to read number plates"
    )
    parser.add_argument("--camera", default="Camera 1", help="camera name shown in alerts")
    parser.add_argument("--lat", type=float, help="camera latitude, for the map link")
    parser.add_argument("--lon", type=float, help="camera longitude, for the map link")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    zones = load_zones(args.zones)
    ignore = load_ignore_areas(args.zones)
    if ignore:
        print(f"Ignoring {len(ignore)} marked area(s): {', '.join(a.name for a in ignore)}")
    if args.grace:
        zones = [replace(z, grace_seconds=args.grace) for z in zones]
    image_size = tuple(args.imgsz) if len(args.imgsz) > 1 else args.imgsz[0]

    reporter = None
    if args.api:
        reporter = ViolationReporter(
            args.api,
            camera_name=args.camera,
            latitude=args.lat,
            longitude=args.lon,
            internal_key=os.environ.get("INTERNAL_API_KEY", ""),
            ca_file=args.ca,
        )

    plate_reader = None
    if not args.no_plates:
        from worker.plates import PlateReader

        plate_reader = PlateReader()

    summary = run(
        parse_source(args.source),
        zones,
        args.out,
        weights=args.weights,
        image_size=image_size,
        target_fps=args.fps,
        ignore=ignore,
        show=args.show,
        duration=args.duration,
        reporter=reporter,
        plate_reader=plate_reader,
    )
    if reporter:
        print(
            f"Reports to the server: {summary['reports_sent']} sent, "
            f"{summary['reports_failed']} failed."
        )
    print(
        f"\nRan {summary['seconds']}s: {summary['frames_processed']} frames "
        f"({summary['processed_frames_per_second']}/s), worst delay "
        f"{summary['worst_delay_ms']} ms, {summary['violations']} violation(s), "
        f"{summary['plates_read']} plate(s) read, "
        f"{summary['reconnects']} reconnect(s). Results in {args.out}/"
    )


if __name__ == "__main__":
    main()
