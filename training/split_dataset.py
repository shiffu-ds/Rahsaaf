"""Split labelled pictures into training, validation and test sets.

    uv run python -m training.split_dataset

Reads data/dataset/images + labels and writes data/dataset/split/ in the
layout YOLO training expects, plus a dataset.yaml describing it.

**Split by video, not by picture.** Frames from one video look almost alike.
If some went to training and others to the test set, the model would be tested
on pictures it has practically seen, and the accuracy would look better than
it is. So every frame of a video goes to the same set. With fewer than 5
videos that is impossible to do fairly, and the tool falls back to splitting
by picture and says so.
"""
from __future__ import annotations

import argparse
import random
import shutil
from collections import defaultdict
from pathlib import Path

from training.classes import CLASSES

SETS = ("train", "val", "test")


def assign(groups: dict[str, list[Path]], fractions: tuple[float, float, float], seed: int):
    """Give whole groups to train / val / test, close to the wanted shares."""
    names = sorted(groups)
    random.Random(seed).shuffle(names)
    total = sum(len(groups[n]) for n in names)
    targets = [f * total for f in fractions]
    result = {s: [] for s in SETS}
    counts = [0, 0, 0]

    # Largest groups first; each goes to the set furthest below its target.
    for name in sorted(names, key=lambda n: -len(groups[n])):
        gaps = [targets[i] - counts[i] for i in range(3)]
        chosen = max(range(3), key=lambda i: gaps[i])
        result[SETS[chosen]].extend(groups[name])
        counts[chosen] += len(groups[name])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset", type=Path, default=Path("data/dataset"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    images_dir, labels_dir = args.dataset / "images", args.dataset / "labels"
    labelled = [p for p in sorted(images_dir.glob("*.jpg")) if (labels_dir / f"{p.stem}.txt").exists()]
    if not labelled:
        raise SystemExit(f"No labelled pictures found under {args.dataset}/.")

    by_video: dict[str, list[Path]] = defaultdict(list)
    for image in labelled:
        by_video[image.stem.split("__")[0]].append(image)

    if len(by_video) >= 5:
        groups = dict(by_video)
        print(f"Splitting {len(labelled)} pictures by video ({len(by_video)} videos).")
    else:
        groups = {image.stem: [image] for image in labelled}
        print(
            f"WARNING: only {len(by_video)} video(s). Splitting by picture instead. "
            "Test accuracy will look better than it really is; record more videos."
        )

    split = assign(groups, (0.7, 0.2, 0.1), args.seed)

    out = args.dataset / "split"
    if out.exists():
        shutil.rmtree(out)
    for name, images in split.items():
        (out / "images" / name).mkdir(parents=True)
        (out / "labels" / name).mkdir(parents=True)
        for image in images:
            shutil.copy2(image, out / "images" / name / image.name)
            shutil.copy2(labels_dir / f"{image.stem}.txt", out / "labels" / name / f"{image.stem}.txt")
        print(f"  {name}: {len(images)} pictures")

    # No "path:" line on purpose: without it the paths below are read relative
    # to this file, so the folder still works after being zipped and moved.
    yaml = ["train: images/train", "val: images/val", "test: images/test", "names:"]
    yaml += [f"  {i}: {name}" for i, name in enumerate(CLASSES)]
    (out / "dataset.yaml").write_text("\n".join(yaml) + "\n")
    print(f"\nWritten to {out}/. Zip that folder and upload it for training.")


if __name__ == "__main__":
    main()
