"""Convert YOLO weights to OpenVINO format, which runs faster on Intel CPUs.

    uv run python tools/export_openvino.py models/yolo11n.pt --imgsz 256 416

--imgsz is "height width" (each a multiple of 32), or one number for a square.
A wide camera picture wastes a third of a square input on padding, so a
rectangular export such as 256 x 416 is noticeably faster for 16:9 video.

The result is a folder next to the weights, e.g. models/yolo11n_openvino_model.
The model only accepts the size it was exported with, so pass the same --imgsz
to the runner.
"""
from __future__ import annotations

import argparse

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("weights")
    parser.add_argument("--imgsz", type=int, nargs="+", default=[256, 416])
    args = parser.parse_args()

    path = YOLO(args.weights).export(format="openvino", imgsz=args.imgsz if len(args.imgsz) > 1 else args.imgsz[0])
    print(f"Exported to {path}")


if __name__ == "__main__":
    main()
