"""Measure the detector against violations you marked by hand.

    uv run python tools/evaluate_violations.py data/eval/truth.json

``truth.json`` lists test clips and, for each, every real violation in it:

    {
      "clips": [
        {
          "video": "bazaar_morning.mp4",
          "zones": "bazaar_zones.json",
          "violations": [
            {"zone": "zone1", "start": 35, "end": 190},
            {"zone": "zone1", "start": 260, "end": 410}
          ]
        }
      ]
    }

``start`` is the second the vehicle came to rest and ``end`` the second it
drove off (or the clip's length if it never left). List only vehicles that
stayed longer than the zone's grace period: a shorter stop is not a violation.
Paths are relative to the truth file. A clip with no violations still belongs
in the list, with an empty "violations": it tests for false alarms.

Reports precision and recall, and writes docs/VIOLATION_REPORT.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.run_video import run  # noqa: E402
from worker.scoring import Interval, match  # noqa: E402
from worker.zones import load_ignore_areas, load_zones  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("truth", type=Path)
    parser.add_argument("--weights", default="models/yolo11n.pt")
    parser.add_argument("--skip", type=int, default=3)
    parser.add_argument(
        "--imgsz", type=int, nargs="+", default=[416],
        help="model input size: one number, or height width",
    )
    parser.add_argument("--report", type=Path, default=Path("docs/VIOLATION_REPORT.md"))
    args = parser.parse_args()
    image_size = tuple(args.imgsz) if len(args.imgsz) > 1 else args.imgsz[0]

    base = args.truth.parent
    clips = json.loads(args.truth.read_text())["clips"]
    if not clips:
        raise SystemExit("The truth file lists no clips.")

    all_truth: list[Interval] = []
    all_detected: list[Interval] = []
    rows = []
    for index, clip in enumerate(clips):
        zones = load_zones(base / clip["zones"])
        print(f"[{index + 1}/{len(clips)}] {clip['video']}")
        with tempfile.TemporaryDirectory() as scratch:
            summary = run(
                str(base / clip["video"]), zones, scratch, args.weights, args.skip, image_size,
                ignore=load_ignore_areas(base / clip["zones"]),
            )

        # Zone names are made unique per clip so "zone1" in two clips never match.
        tag = lambda zone: f"{index}:{zone}"  # noqa: E731
        truth = [Interval(tag(v["zone"]), v["start"], v["end"]) for v in clip["violations"]]
        detected = [
            Interval(
                tag(v["zone_id"]),
                v["stopped_at_seconds"],
                v["ended_at_seconds"] if v["ended_at_seconds"] is not None else summary["video_seconds"],
            )
            for v in summary["violations"]
        ]
        score = match(truth, detected)
        rows.append((clip["video"], len(truth), len(score.matched), len(score.missed), len(score.false_alarms)))
        all_truth += truth
        all_detected += detected

    total = match(all_truth, all_detected)
    show = lambda value: "not measurable" if value is None else f"{value:.2f}"  # noqa: E731
    lines = [
        "# Violation detection report",
        "",
        f"- Clips: {len(clips)}",
        f"- Model: `{args.weights}`",
        f"- Date: {date.today().isoformat()}",
        f"- Real violations: {len(all_truth)}",
        f"- **Precision: {show(total.precision)}** (of the alerts raised, the share that were real)",
        f"- **Recall: {show(total.recall)}** (of the real violations, the share that were caught)",
        "",
        "| Clip | Real | Caught | Missed | False alarms |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {name} | {real} | {hit} | {miss} | {false} |" for name, real, hit, miss, false in rows]
    if len(all_truth) < 30:
        lines += ["", f"Only {len(all_truth)} real violations: treat these figures as rough."]
    text = "\n".join(lines) + "\n"

    print("\n" + text)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text)
    print(f"Saved to {args.report}")


if __name__ == "__main__":
    main()
