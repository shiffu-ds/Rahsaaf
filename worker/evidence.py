"""Evidence for a violation: a photo and a short clip.

A clip is only useful if it shows what happened *before* the alert, and that
footage is gone by the time the violation is confirmed. So the recorder keeps
the last few seconds of frames in memory at all times, and when a violation
starts it writes those out and keeps recording for a few seconds more.

Frames are held as JPEGs, not raw pixels. Ten seconds of raw 960 x 540 frames
would take around 80 MB; as JPEGs it is a few megabytes.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class _Clip:
    path: Path
    until: float
    frames: list[tuple[float, bytes]] = field(default_factory=list)


class ClipRecorder:
    def __init__(
        self,
        before_seconds: float = 8.0,
        after_seconds: float = 4.0,
        jpeg_quality: int = 80,
    ):
        self.before_seconds = before_seconds
        self.after_seconds = after_seconds
        self._quality = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
        self._recent: deque[tuple[float, bytes]] = deque()
        self._open: list[_Clip] = []

    def add(self, now: float, frame: np.ndarray) -> list[Path]:
        """Record one frame. Returns the paths of any clips just completed."""
        ok, encoded = cv2.imencode(".jpg", frame, self._quality)
        if not ok:
            return []
        item = (now, encoded.tobytes())

        self._recent.append(item)
        while self._recent and now - self._recent[0][0] > self.before_seconds:
            self._recent.popleft()

        finished: list[Path] = []
        for clip in list(self._open):
            clip.frames.append(item)
            if now >= clip.until:
                self._open.remove(clip)
                finished.append(_write(clip))
        return finished

    def start_clip(self, now: float, path: str | Path) -> None:
        """Begin a clip that includes the seconds leading up to ``now``."""
        self._open.append(
            _Clip(Path(path), now + self.after_seconds, list(self._recent))
        )

    def close(self) -> list[Path]:
        """Write out any clips still recording, e.g. at shutdown."""
        finished = [_write(clip) for clip in self._open]
        self._open.clear()
        return finished


def _write(clip: _Clip) -> Path:
    first = cv2.imdecode(np.frombuffer(clip.frames[0][1], np.uint8), cv2.IMREAD_COLOR)
    height, width = first.shape[:2]
    span = clip.frames[-1][0] - clip.frames[0][0]
    # Play back at the rate the frames were really captured, so the clip runs
    # at true speed whatever the processing rate was.
    fps = (len(clip.frames) - 1) / span if span > 0 else 5.0

    clip.path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(clip.path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    for _, data in clip.frames:
        writer.write(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR))
    writer.release()
    return clip.path
