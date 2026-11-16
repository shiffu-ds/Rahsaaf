"""Draw first-guess boxes on extracted frames, to speed up labelling.

    uv run python tools/prelabel.py

Runs the stock model over data/dataset/images/ and writes a label file for
each picture into data/dataset/labels/. It can only find the four classes the
stock model knows (car, motorcycle, bus, truck). You then open the pictures in
a labelling tool to:

* fix wrong boxes and delete false ones,
* relabel vehicles it got wrong (a rickshaw is usually guessed as a car or
  motorcycle, a loader as a truck),
* add the vehicles it missed.

Correcting a guess is several times faster than drawing every box by hand.
Existing label files are never overwritten, so finished work is safe.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from training.classes import CLASSES, COCO_TO_LOCAL  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--images", type=Path, default=Path("data/dataset/images"))
    parser.add_argument("--labels", type=Path, default=Path("data/dataset/labels"))
    parser.add_argument("--weights", default="models/yolo11n.pt")
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    images = sorted(args.images.glob("*.jpg"))
    if not images:
        raise SystemExit(f"No .jpg files in {args.images}. Run tools/extract_frames.py first.")
    args.labels.mkdir(parents=True, exist_ok=True)
    # The class list labelling tools ask for, in the right order.
    (args.labels / "classes.txt").write_text("\n".join(CLASSES) + "\n")

    model = YOLO(args.weights)
    written = skipped = boxes = 0
    for image in images:
        target = args.labels / f"{image.stem}.txt"
        if target.exists():
            skipped += 1
            continue
        result = model.predict(
            str(image), classes=list(COCO_TO_LOCAL), conf=args.conf, imgsz=args.imgsz, verbose=False
        )[0]
        lines = [
            f"{COCO_TO_LOCAL[int(cls)]} {x:.6f} {y:.6f} {w:.6f} {h:.6f}"
            for cls, (x, y, w, h) in zip(result.boxes.cls.tolist(), result.boxes.xywhn.tolist())
        ]
        target.write_text("\n".join(lines) + ("\n" if lines else ""))
        written += 1
        boxes += len(lines)

    print(f"{written} label files written ({boxes} boxes), {skipped} already existed and were kept.")
    print(f"Labels are in {args.labels}/. Now correct them in a labelling tool.")


if __name__ == "__main__":
    main()
