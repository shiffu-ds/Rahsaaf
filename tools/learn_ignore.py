"""Suggest ignore areas from alerts officers rejected as "Not a vehicle".

    uv run python tools/learn_ignore.py zones.json --camera "Hospital gate"

Shows every spot on that camera where alerts were rejected as "Not a vehicle"
at least twice. Nothing is changed until you add --apply, which writes the
spots into the zones file as ignore areas. Restart the camera worker
afterwards so it reads the new file.

    uv run python tools/learn_ignore.py zones.json --camera "Hospital gate" --apply

Use --min to ask for more rejections before a spot counts.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import load_settings  # noqa: E402
from api.db import Database  # noqa: E402
from worker.learn import parse_box, suggest_ignore_areas  # noqa: E402
from worker.zones import load_ignore_areas, load_zones, save_zones  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("zones", help="the zones file this camera's worker uses")
    parser.add_argument("--camera", required=True, help="camera name, as shown in alerts")
    parser.add_argument("--min", type=int, default=2, help="rejections needed at one spot")
    parser.add_argument("--apply", action="store_true", help="write the areas to the zones file")
    args = parser.parse_args()
    if args.min < 1:
        raise SystemExit("--min must be 1 or more")

    path = Path(args.zones)
    if not path.exists():
        raise SystemExit(f"Zones file not found: {path}")
    zones = load_zones(path)
    existing = load_ignore_areas(path)

    rows = Database(load_settings().database_path).not_a_vehicle_boxes(args.camera)
    proposals = suggest_ignore_areas([parse_box(row["box"]) for row in rows], existing, args.min)

    print(f'{len(rows)} alert(s) on "{args.camera}" stand rejected as "Not a vehicle".')
    if not proposals:
        print(f"No spot has {args.min} or more of them that is not already ignored.")
        return
    for area, count in proposals:
        (x1, y1), _, (x2, y2), _ = area.polygon
        print(
            f"  {area.name}: rejected {count} times, "
            f"left {x1:.0%} to {x2:.0%}, top {y1:.0%} to {y2:.0%} of the picture"
        )
    if not args.apply:
        print("Nothing changed. Add --apply to write these to the zones file.")
        return
    save_zones(path, zones, existing + [area for area, _ in proposals])
    print(f"Saved {len(proposals)} ignore area(s) to {path}. Restart the camera worker.")


if __name__ == "__main__":
    main()
