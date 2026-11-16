"""Draw a no-parking zone on the first frame of a video and save it.

    uv run python tools/draw_zone.py VIDEO --out zones.json --name "Hospital gate"

Left click  add a corner
Right click remove the last corner
Enter       save and quit (needs at least 3 corners)
Esc         quit without saving

If the output file already exists, the new zone is added to it.

To measure how much a parked vehicle holds up traffic, also mark the driving
lane beside a zone. Draw it over the road that traffic uses, for a good
distance before the zone:

    uv run python tools/draw_zone.py VIDEO --out zones.json --lane zone1

If a fixed thing such as a booth or kiosk keeps being reported as a parked
vehicle, draw around it once and the system will skip it:

    uv run python tools/draw_zone.py VIDEO --out zones.json --ignore "Ticket booth"
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.zones import (  # noqa: E402
    IgnoreArea,
    Zone,
    load_ignore_areas,
    load_zones,
    save_zones,
)

WINDOW = "Draw zone: left click = add, right click = undo, Enter = save, Esc = cancel"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("video")
    parser.add_argument("--out", default="zones.json")
    parser.add_argument("--name", default="No parking")
    parser.add_argument("--grace", type=float, default=120.0, help="allowed stop, seconds")
    parser.add_argument("--max-width", type=int, default=1280, help="display width")
    parser.add_argument(
        "--lane",
        metavar="ZONE_ID",
        help="draw the driving lane for this existing zone instead of a new zone",
    )
    parser.add_argument(
        "--ignore",
        metavar="NAME",
        help="draw around a fixed thing (booth, kiosk) that must never be reported",
    )
    args = parser.parse_args()

    capture = cv2.VideoCapture(args.video)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise SystemExit(f"Cannot read a frame from: {args.video}")

    height, width = frame.shape[:2]
    if width > args.max_width:
        frame = cv2.resize(frame, (args.max_width, int(height * args.max_width / width)))
        height, width = frame.shape[:2]

    points: list[tuple[int, int]] = []

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()

    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, on_mouse)

    while True:
        view = frame.copy()
        if len(points) >= 2:
            cv2.polylines(view, [np.array(points, np.int32)], len(points) >= 3, (0, 200, 255), 2)
        for point in points:
            cv2.circle(view, point, 4, (0, 0, 255), -1)
        cv2.imshow(WINDOW, view)

        key = cv2.waitKey(20) & 0xFF
        if key == 27:
            print("Cancelled. Nothing saved.")
            return
        if key in (13, 10) and len(points) >= 3:
            break

    cv2.destroyAllWindows()

    out = Path(args.out)
    zones = load_zones(out) if out.exists() else []
    ignore = load_ignore_areas(out) if out.exists() else []
    polygon = tuple((x / width, y / height) for x, y in points)

    if args.lane:
        if args.lane not in {z.id for z in zones}:
            raise SystemExit(f"No zone {args.lane!r} in {out}. Draw the zone first.")
        zones = [replace(z, lane=polygon) if z.id == args.lane else z for z in zones]
        save_zones(out, zones, ignore)
        print(f"Saved the driving lane for {args.lane} to {out}")
        return

    if args.ignore:
        ignore.append(IgnoreArea(name=args.ignore, polygon=polygon))
        save_zones(out, zones, ignore)
        print(f"Saved the ignore area {args.ignore!r} to {out}")
        return

    zone_id = f"zone{len(zones) + 1}"
    zones.append(
        Zone(
            id=zone_id,
            name=args.name,
            polygon=polygon,
            grace_seconds=args.grace,
        )
    )
    save_zones(out, zones, ignore)
    print(f"Saved {zone_id} ({args.name}) to {out}")


if __name__ == "__main__":
    main()
