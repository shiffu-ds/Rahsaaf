"""Turn fetched Street Scene pictures into test clips with marked violations.

    uv run python tools/prepare_streetscene.py

Reads the pictures fetched by tools/fetch_streetscene.py (every third picture,
so 5 per second) and writes one video per sequence plus truth.json into
data/eval/streetscene/, together with the zones drawn by hand for this street.

The real violations come from the dataset's own hand-made marks: the marked
events that are vehicles standing in a no-parking area for longer than the
grace period. Times are seconds from the start of the sequence; the dataset
has 15 pictures per second, so picture N is at (N - 1) / 15 seconds.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2

SOURCE = Path("data/streetscene/files/StreetScene/Test")
OUT = Path("data/eval/streetscene")
FPS = 5  # every third picture of a 15-per-second sequence

#: sequence -> (zone, first picture, last picture) of each standing vehicle,
#: read from the dataset's TestNNN_gt.txt and checked by eye.
VIOLATIONS = {
    "Test010": [("corner", 2284, 3205)],  # car stopped at the corner kerb, 61 s
    "Test029": [("lanes", 3866, 5177)],   # pickup double-parked in the lane, 87 s
    "Test032": [("corner", 620, 5176)],   # car stopped at the corner kerb, 304 s
}


#: No-parking zones for this street, drawn by hand before any run: the two
#: traffic lanes, and the corner kerb beyond the last parking bay.
ZONES = {
 "zones": [
  {
   "id": "lanes",
   "name": "Traffic lanes",
   "grace_seconds": 30,
   "polygon": [
    [
     0.14,
     0.0
    ],
    [
     0.24,
     0.0
    ],
    [
     0.44,
     0.31
    ],
    [
     0.56,
     0.5
    ],
    [
     0.7,
     0.7
    ],
    [
     0.83,
     0.95
    ],
    [
     0.86,
     1.0
    ],
    [
     0.7,
     1.0
    ],
    [
     0.59,
     0.8
    ],
    [
     0.35,
     0.43
    ]
   ]
  },
  {
   "id": "corner",
   "name": "Corner kerb",
   "grace_seconds": 30,
   "polygon": [
    [
     0.29,
     0.0
    ],
    [
     0.44,
     0.0
    ],
    [
     0.44,
     0.09
    ],
    [
     0.33,
     0.1
    ]
   ]
  }
 ]
}

#: Pictures in each full sequence, from the dataset's table of contents.
LENGTHS = {"Test010": 5200, "Test029": 5200, "Test032": 5200}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clips = []
    for sequence, marks in VIOLATIONS.items():
        # Every third picture, starting from picture 1. Any other picture in the
        # folder (a sample fetched by hand) is left out.
        pictures = sorted(p for p in (SOURCE / sequence).glob("*.jpg") if (int(p.stem) - 1) % 3 == 0)
        expected = len(list(range(1, LENGTHS[sequence] + 1, 3)))
        if len(pictures) != expected:
            print(f"{sequence}: {len(pictures)} of {expected} pictures fetched so far, skipped")
            continue
        numbers = [int(p.stem) for p in pictures]
        steps = {b - a for a, b in zip(numbers, numbers[1:])}
        if steps != {3}:
            raise SystemExit(f"{sequence}: pictures are not evenly 3 apart (gaps {sorted(steps)[:5]})")
        first = cv2.imread(str(pictures[0]))
        height, width = first.shape[:2]
        target = OUT / f"{sequence}.mp4"
        writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (width, height))
        for picture in pictures:
            writer.write(cv2.imread(str(picture)))
        writer.release()
        offset = (numbers[0] - 1) / 15
        clips.append({
            "video": target.name,
            "zones": "zones.json",
            "violations": [
                {"zone": zone, "start": round((a - 1) / 15 - offset, 1), "end": round((b - 1) / 15 - offset, 1)}
                for zone, a, b in marks
            ],
        })
        print(f"{target}: {len(pictures)} pictures, {len(pictures) / FPS:.0f} s")
    (OUT / "zones.json").write_text(json.dumps(ZONES, indent=1) + "\n")
    (OUT / "truth.json").write_text(json.dumps({"clips": clips}, indent=2) + "\n")
    print(f"Wrote {OUT / 'truth.json'}")


if __name__ == "__main__":
    main()
