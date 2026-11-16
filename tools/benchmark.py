"""Measure detection speed of one or more models on this machine.

    uv run python tools/benchmark.py VIDEO models/yolo11n.pt models/yolo11n_openvino_model

Times detection plus tracking only (no video decoding or drawing), on the same
frames for every model, after a short warm-up.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.detector import VehicleTracker  # noqa: E402


def load_frames(video: str, count: int, max_width: int) -> list:
    capture = cv2.VideoCapture(video)
    frames = []
    while len(frames) < count:
        ok, frame = capture.read()
        if not ok:
            break
        height, width = frame.shape[:2]
        if width > max_width:
            frame = cv2.resize(frame, (max_width, int(height * max_width / width)))
        frames.append(frame)
    capture.release()
    if not frames:
        raise SystemExit(f"Cannot read frames from: {video}")
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("video")
    parser.add_argument("models", nargs="+")
    parser.add_argument("--imgsz", type=int, nargs="+", default=[416])
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--max-width", type=int, default=960)
    args = parser.parse_args()

    image_size = tuple(args.imgsz) if len(args.imgsz) > 1 else args.imgsz[0]
    frames = load_frames(args.video, args.frames, args.max_width)
    print(f"{len(frames)} frames, model input {image_size}px\n")
    for weights in args.models:
        tracker = VehicleTracker(weights, image_size=image_size)
        for frame in frames[:5]:  # warm-up, not timed
            tracker.track(frame)
        started = time.perf_counter()
        for frame in frames:
            tracker.track(frame)
        elapsed = time.perf_counter() - started
        print(
            f"{weights}: {len(frames) / elapsed:.1f} frames/second "
            f"({1000 * elapsed / len(frames):.0f} ms per frame)"
        )


if __name__ == "__main__":
    main()
