"""Measure a trained model on the held-out test pictures.

    uv run python tools/evaluate.py models/local.pt

Prints accuracy per class and writes the same table to docs/MODEL_REPORT.md.

The number reported is mAP@50: for each class, how well the model finds its
vehicles with boxes that overlap the true box by at least half. 1.0 is
perfect; the plan's target is 0.80 overall.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("weights")
    parser.add_argument("--data", default="data/dataset/split/dataset.yaml")
    parser.add_argument("--split", default="test", choices=["test", "val"])
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--report", type=Path, default=Path("docs/MODEL_REPORT.md"))
    args = parser.parse_args()

    model = YOLO(args.weights)
    metrics = model.val(
        data=args.data, split=args.split, imgsz=args.imgsz, plots=False, verbose=False
    )

    names = metrics.names
    counts = metrics.nt_per_class  # how many of each class the test pictures contain
    rows = []
    for position, class_id in enumerate(metrics.ap_class_index):
        precision, recall, ap50, _ = metrics.class_result(position)
        rows.append((names[int(class_id)], int(counts[int(class_id)]), precision, recall, ap50))
    missing = [names[i] for i in sorted(names) if int(counts[i]) == 0]

    lines = [
        "# Model report",
        "",
        f"- Model: `{args.weights}`",
        f"- Data: `{args.data}`, `{args.split}` set",
        f"- Date: {date.today().isoformat()}",
        f"- Overall mAP@50: **{metrics.box.map50:.3f}**",
        f"- Overall precision: {metrics.box.mp:.3f}, recall: {metrics.box.mr:.3f}",
        "",
        "| Class | Vehicles in test set | Precision | Recall | mAP@50 |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {n} | {c} | {p:.3f} | {r:.3f} | {a:.3f} |" for n, c, p, r, a in rows]
    if missing:
        lines += ["", "Not measured (no examples in this set): " + ", ".join(missing) + "."]
    few = [n for n, c, *_ in rows if c < 30]
    if few:
        lines += [
            "",
            "Fewer than 30 examples, so treat these numbers as rough: " + ", ".join(few) + ".",
        ]
    text = "\n".join(lines) + "\n"

    print("\n" + text)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text)
    print(f"Saved to {args.report}")


if __name__ == "__main__":
    main()
