"""Turn the public HeteroTraffic dataset into a training set for RahSaaf.

    uv run python tools/prepare_heterotraffic.py data/heterotraffic/extracted

HeteroTraffic (Sagar and Koli, Mendeley Data, DOI 10.17632/tvkfk56s2k.2,
CC BY 4.0) is about 16,000 labelled road pictures from Bangladesh with 17
classes. This script:

* renames its classes to RahSaaf's (its "CNG" is an auto rickshaw),
* hides vehicle types RahSaaf has no class for (see below),
* picks a subset small enough to train without a GPU, favouring pictures
  that contain rickshaws,
* shrinks the pictures, and
* splits them into training, validation and test sets.

**Vehicles with no RahSaaf class are painted over, not just left unlabelled.**
An unlabelled vehicle in a training picture teaches the model that such a
thing is background. A cycle rickshaw or an "easybike" looks enough like an
auto rickshaw that this would work directly against what we want to learn.
Painting the box grey removes it from the lesson altogether. A picture is
dropped instead when the paint would cover part of a vehicle we do want.

There is no Qingqi in this dataset. The class stays in the list, empty, so
that Qingqi pictures can be added later without renumbering anything.
"""
from __future__ import annotations

import argparse
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

import cv2
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from training.classes import CLASSES  # noqa: E402

#: HeteroTraffic class (lower case) -> RahSaaf class.
RENAME = {
    "car": "car",
    "mpv": "car",  # multi-purpose vehicle: SUVs and people carriers
    "motorbike": "motorcycle",
    "cng": "rickshaw",  # the local name for a three-wheeled auto rickshaw
    "van": "van",
    "bus": "bus",
    "truck": "truck",
    "pickup": "pickup_loader",
}
#: Not vehicles RahSaaf cares about; leaving them as background is correct.
BACKGROUND = {"pedestrian", "bicycle", "wheelbarrow"}
#: Everything else (cycle rickshaw, easybike, bhotbhoti, leguna, power tiller,
#: shopping van) is painted over.

GREY = (114, 114, 114)


def to_pixels(box, width, height):
    cx, cy, w, h = box
    return (
        (cx - w / 2) * width,
        (cy - h / 2) * height,
        (cx + w / 2) * width,
        (cy + h / 2) * height,
    )


def covered_share(inner, outer) -> float:
    """How much of ``inner`` lies under ``outer``."""
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return ix * iy / area if area > 0 else 0.0


def read_labels(path: Path, names: dict[int, str]):
    """Returns (kept boxes as (class index, box), boxes to paint over)."""
    kept, hidden = [], []
    for line in path.read_text().split("\n"):
        parts = line.split()
        if len(parts) < 5:
            continue
        name = names.get(int(float(parts[0])), "").lower()
        box = tuple(float(v) for v in parts[1:5])
        if name in RENAME:
            kept.append((CLASSES.index(RENAME[name]), box))
        elif name not in BACKGROUND:
            hidden.append(box)
    return kept, hidden


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", type=Path, help="folder holding images/, labels/ and data.yaml")
    parser.add_argument("--out", type=Path, default=Path("data/dataset_hetero"))
    parser.add_argument("--images", type=int, default=2500, help="how many pictures to use")
    parser.add_argument("--rickshaw-share", type=float, default=0.6)
    parser.add_argument("--max-side", type=int, default=960)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    config = yaml.safe_load((args.source / "data.yaml").read_text())
    raw_names = config["names"]
    names = dict(enumerate(raw_names)) if isinstance(raw_names, list) else {int(k): v for k, v in raw_names.items()}
    print("Classes in the source:", ", ".join(names.values()))
    unknown = {n.lower() for n in names.values()} - set(RENAME) - BACKGROUND
    print("Painted over:", ", ".join(sorted(unknown)) or "none")

    image_dir, label_dir = args.source / "images", args.source / "labels"
    images = {p.stem: p for p in image_dir.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")}
    labels = {p.stem: p for p in label_dir.rglob("*.txt")}
    stems = sorted(set(images) & set(labels))
    print(f"{len(stems)} labelled pictures found.")

    rickshaw = CLASSES.index("rickshaw")
    usable = {}
    for stem in stems:
        kept, hidden = read_labels(labels[stem], names)
        if kept:
            usable[stem] = (kept, hidden)

    rng = random.Random(args.seed)
    with_rickshaw = [s for s in usable if any(c == rickshaw for c, _ in usable[s][0])]
    without = [s for s in usable if s not in set(with_rickshaw)]
    rng.shuffle(with_rickshaw)
    rng.shuffle(without)
    wanted_rickshaw = min(len(with_rickshaw), int(args.images * args.rickshaw_share))
    # Over-pick a little: some pictures are dropped below.
    queue = with_rickshaw[: int(wanted_rickshaw * 1.15)] + without[: int((args.images - wanted_rickshaw) * 1.15)]
    rng.shuffle(queue)

    if args.out.exists():
        shutil.rmtree(args.out)
    split_dir = args.out / "split"
    counts = {"train": Counter(), "val": Counter(), "test": Counter()}
    pictures = Counter()
    dropped = painted = 0

    for stem in queue:
        if sum(pictures.values()) >= args.images:
            break
        kept, hidden = usable[stem]
        image = cv2.imread(str(images[stem]))
        if image is None:
            dropped += 1
            continue
        height, width = image.shape[:2]

        kept_px = [to_pixels(box, width, height) for _, box in kept]
        hidden_px = [to_pixels(box, width, height) for box in hidden]
        # Painting must not wipe out part of a vehicle we want to learn.
        if any(covered_share(k, h) > 0.3 for k in kept_px for h in hidden_px):
            dropped += 1
            continue
        for x1, y1, x2, y2 in hidden_px:
            cv2.rectangle(image, (int(x1), int(y1)), (int(x2), int(y2)), GREY, -1)
            painted += 1

        scale = args.max_side / max(width, height)
        if scale < 1:
            image = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)

        # 80 / 10 / 10. Decided by the picture's name, so a picture always
        # lands in the same set however the subset is chosen.
        bucket = random.Random(f"{args.seed}:{stem}").random()
        part = "train" if bucket < 0.8 else "val" if bucket < 0.9 else "test"

        (split_dir / "images" / part).mkdir(parents=True, exist_ok=True)
        (split_dir / "labels" / part).mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(split_dir / "images" / part / f"{stem}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 88])
        lines = [f"{c} {b[0]:.6f} {b[1]:.6f} {b[2]:.6f} {b[3]:.6f}" for c, b in kept]
        (split_dir / "labels" / part / f"{stem}.txt").write_text("\n".join(lines) + "\n")
        pictures[part] += 1
        for c, _ in kept:
            counts[part][CLASSES[c]] += 1

    yaml_lines = ["train: images/train", "val: images/val", "test: images/test", "names:"]
    yaml_lines += [f"  {i}: {name}" for i, name in enumerate(CLASSES)]
    (split_dir / "dataset.yaml").write_text("\n".join(yaml_lines) + "\n")

    print(f"\nPictures: {dict(pictures)}  (dropped {dropped}, painted over {painted} boxes)")
    print(f"{'class':<15}{'train':>8}{'val':>8}{'test':>8}")
    for name in CLASSES:
        print(f"{name:<15}{counts['train'][name]:>8}{counts['val'][name]:>8}{counts['test'][name]:>8}")
    print(f"\nWritten to {split_dir}/")


if __name__ == "__main__":
    main()
