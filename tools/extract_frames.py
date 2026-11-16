"""Pull still frames out of videos, ready for labelling.

    uv run python tools/extract_frames.py data/footage/*.mp4 --every 2

Saves one frame every --every seconds into data/dataset/images/, skipping
frames that look almost the same as the last one saved. A road where nothing
has moved gives you the same picture again, and labelling it twice teaches the
model nothing.

Files are named <video>__<number>.jpg. The video name is kept so the dataset
can later be split by video.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import cv2
import numpy as np


def _signature(frame: np.ndarray) -> np.ndarray:
    """A tiny grey copy of the frame, for cheap comparison."""
    return cv2.cvtColor(cv2.resize(frame, (64, 36)), cv2.COLOR_BGR2GRAY).astype(np.int16)


def extract(
    video: Path, out_dir: Path, every_seconds: float, min_change: float, max_width: int
) -> int:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        print(f"  cannot open {video}, skipped")
        return 0
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, round(fps * every_seconds))
    stem = re.sub(r"[^A-Za-z0-9-]+", "-", video.stem).strip("-") or "video"

    saved = index = 0
    last = None
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index % step == 0:
            signature = _signature(frame)
            changed = last is None or float(np.abs(signature - last).mean()) >= min_change
            if changed:
                height, width = frame.shape[:2]
                if width > max_width:
                    frame = cv2.resize(frame, (max_width, int(height * max_width / width)))
                saved += 1
                cv2.imwrite(str(out_dir / f"{stem}__{saved:05d}.jpg"), frame)
                last = signature
        index += 1
    capture.release()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("videos", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/dataset/images"))
    parser.add_argument("--every", type=float, default=2.0, help="seconds between frames")
    parser.add_argument(
        "--min-change",
        type=float,
        default=2.0,
        help="skip frames that differ less than this from the last saved one (0 keeps all)",
    )
    parser.add_argument("--max-width", type=int, default=1280)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for video in args.videos:
        count = extract(video, args.out, args.every, args.min_change, args.max_width)
        print(f"{video.name}: {count} frames")
        total += count
    print(f"\n{total} frames saved to {args.out}/")


if __name__ == "__main__":
    main()
