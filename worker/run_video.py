"""Phase 1 runner: find illegally parked vehicles in a recorded video.

    uv run python -m worker.run_video VIDEO --zones zones.json

Writes, into the output folder:

* ``annotated.mp4``    the video with zones, boxes and timers drawn on it
* ``violations.json``  one record per violation
* ``violation_N.jpg``  the frame on which violation N was confirmed
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import time
from pathlib import Path

import cv2

from worker.detector import VehicleTracker
from worker.overlay import draw_vehicles, draw_zones
from worker.parking_state import ParkingMonitor, ViolationEvent
from worker.zones import Zone, drop_ignored, load_ignore_areas, load_zones


def run(
    video_path: str,
    zones: list[Zone],
    output_dir: str,
    weights: str = "models/yolo11n.pt",
    frame_skip: int = 3,
    image_size: int = 416,
    max_width: int = 960,
    ignore=(),
) -> dict:
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise SystemExit(f"Cannot open video: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    src_w = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = min(1.0, max_width / src_w)
    width, height = int(src_w * scale), int(src_h * scale)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(out / "annotated.mp4"),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps / frame_skip,
        (width, height),
    )

    tracker = VehicleTracker(weights, image_size=image_size)
    monitor = ParkingMonitor(zones)
    records: dict[int, dict] = {}

    def record(event: ViolationEvent, frame=None) -> None:
        if event.kind == "started":
            photo = f"violation_{event.violation_id}.jpg"
            cv2.imwrite(str(out / photo), frame)
            records[event.violation_id] = {
                "violation_id": event.violation_id,
                "zone_id": event.zone_id,
                "vehicle_class": event.vehicle_class,
                "confidence": event.confidence,
                "track_id": event.track_id,
                "stopped_at_seconds": round(event.stopped_at, 2),
                "confirmed_at_seconds": round(event.confirmed_at, 2),
                "ended_at_seconds": None,
                "duration_seconds": None,
                "box": [round(v, 1) for v in event.box],
                "photo": photo,
            }
            print(
                f"  VIOLATION {event.violation_id}: {event.vehicle_class} in "
                f"zone {event.zone_id} at {event.confirmed_at:.1f}s"
            )
        else:
            entry = records[event.violation_id]
            entry["ended_at_seconds"] = round(event.ended_at, 2)
            entry["duration_seconds"] = round(event.duration_seconds, 2)

    frame_index = processed = 0
    video_time = 0.0
    started = time.perf_counter()

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame_index += 1
        if (frame_index - 1) % frame_skip:
            continue

        if scale < 1.0:
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        video_time = (frame_index - 1) / fps

        observations = drop_ignored(tracker.track(frame), ignore, width, height)
        events = monitor.update(video_time, observations, width, height)

        draw_zones(frame, zones, ignore)
        draw_vehicles(frame, observations, monitor.statuses(video_time))
        for event in events:
            record(event, frame)
        writer.write(frame)
        processed += 1

    for event in monitor.flush(video_time):
        record(event)

    capture.release()
    writer.release()

    elapsed = time.perf_counter() - started
    summary = {
        "video": str(video_path),
        "video_seconds": round(frame_index / fps, 2),
        "frames_processed": processed,
        "processing_seconds": round(elapsed, 2),
        "processed_frames_per_second": round(processed / elapsed, 2) if elapsed else None,
        "violations": list(records.values()),
    }
    (out / "violations.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("video")
    parser.add_argument("--zones", required=True, help="zones JSON from tools/draw_zone.py")
    parser.add_argument("--out", default="data/run", help="output folder")
    parser.add_argument("--weights", default="models/yolo11n.pt")
    parser.add_argument("--skip", type=int, default=3, help="analyse every Nth frame")
    parser.add_argument(
        "--imgsz", type=int, nargs="+", default=[416],
        help="model input size: one number, or height width",
    )
    parser.add_argument(
        "--grace",
        type=float,
        help="override every zone's grace period, in seconds (useful for demos)",
    )
    args = parser.parse_args()

    zones = load_zones(args.zones)
    if args.grace:
        zones = [replace(z, grace_seconds=args.grace) for z in zones]

    summary = run(
        args.video, zones, args.out, args.weights, args.skip,
        tuple(args.imgsz) if len(args.imgsz) > 1 else args.imgsz[0],
        ignore=load_ignore_areas(args.zones),
    )
    print(
        f"\n{len(summary['violations'])} violation(s) in "
        f"{summary['video_seconds']}s of video. "
        f"Speed: {summary['processed_frames_per_second']} processed frames/second."
    )
    print(f"Results in {args.out}/")


if __name__ == "__main__":
    main()
