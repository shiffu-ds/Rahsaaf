"""Train the vehicle model on this computer, without a GPU.

    uv run python tools/train_local.py data/dataset_hetero/split/dataset.yaml
    uv run python tools/train_local.py data/dataset_hetero/split/dataset.yaml --resume

Slow: hours, not minutes. Use training/train_colab.ipynb instead if you can.
If the computer sleeps or the run is interrupted, start it again with
--resume and it continues from the last finished round.

Two choices keep it practical on a CPU:

* The first ten layers of the model (the part that already knows edges,
  wheels and windows from general pictures) are frozen, so each round only
  adjusts the later layers. Rounds are faster, at a small cost in accuracy.
* Pictures are used at 416 pixels, close to the size the live detector runs at.

The best model is written to data/train_runs/NAME/weights/best.pt.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data")
    parser.add_argument("--name", default="local")
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--patience", type=int, default=6, help="stop after this many rounds without improvement")
    parser.add_argument("--imgsz", type=int, default=416)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--freeze", type=int, default=10)
    parser.add_argument(
        "--start", default="models/yolo11n.pt",
        help="weights to start from; pass an earlier result (e.g. models/local.pt) to keep improving it",
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    runs = Path("data/train_runs").resolve()
    last = runs / args.name / "weights" / "last.pt"
    if args.resume:
        if not last.exists():
            raise SystemExit(f"Nothing to resume: {last} does not exist.")
        YOLO(str(last)).train(resume=True)
        return

    YOLO(args.start).train(
        data=args.data,
        epochs=args.epochs,
        patience=args.patience,
        imgsz=args.imgsz,
        batch=args.batch,
        freeze=args.freeze,
        workers=2,
        device="cpu",
        project=str(runs),
        name=args.name,
        exist_ok=True,
        plots=False,
    )


if __name__ == "__main__":
    main()
