"""Measure plate reading on your own pictures.

    uv run python tools/evaluate_plates.py data/plates

The folder holds pictures of vehicles (or close-ups of plates) and a file
``truth.csv`` with one line per picture: file name, then the true plate.

    car_001.jpg,LEA1234
    bike_014.jpg,PSR567

Three outcomes are counted for each picture:

* correct      the system read the plate and got it right
* wrong        the system read a plate but it was not the true one
* unreadable   the system declined to give a plate

"Wrong" is the number that matters most: it is how often an alert would name
the wrong vehicle. A high "unreadable" count is safe, just less useful.

Each picture is read once here. The live system reads several frames and lets
them vote, so its wrong-plate rate should be lower than this report shows.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.plates import PlateReader, looks_like_plate, normalise  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--min-confidence", type=float, default=0.7)
    parser.add_argument("--report", type=Path, default=Path("docs/PLATE_REPORT.md"))
    args = parser.parse_args()

    truth_file = args.folder / "truth.csv"
    if not truth_file.exists():
        raise SystemExit(f"{truth_file} not found. See the top of this file for its format.")
    with truth_file.open(newline="") as handle:
        truth = [(row[0].strip(), normalise(row[1])) for row in csv.reader(handle) if len(row) >= 2]
    if not truth:
        raise SystemExit(f"{truth_file} has no usable lines.")

    reader = PlateReader()
    correct = wrong = unreadable = missing = 0
    mistakes: list[tuple[str, str, str]] = []
    for name, expected in truth:
        image = cv2.imread(str(args.folder / name))
        if image is None:
            missing += 1
            continue
        read = reader.read(image)
        accepted = (
            read is not None
            and read.confidence >= args.min_confidence
            and looks_like_plate(read.text)
        )
        if not accepted:
            unreadable += 1
        elif read.text == expected:
            correct += 1
        else:
            wrong += 1
            mistakes.append((name, expected, read.text))

    total = correct + wrong + unreadable
    if total == 0:
        raise SystemExit("None of the listed pictures could be opened.")
    share = lambda n: f"{100 * n / total:.1f}%"  # noqa: E731
    given = correct + wrong

    lines = [
        "# Plate reading report",
        "",
        f"- Pictures: {total} (from `{args.folder}`)",
        f"- Date: {date.today().isoformat()}",
        f"- Minimum confidence to accept a read: {args.min_confidence}",
        "",
        "| Outcome | Count | Share |",
        "|---|---|---|",
        f"| Correct | {correct} | {share(correct)} |",
        f"| Wrong plate given | {wrong} | {share(wrong)} |",
        f"| Declined as unreadable | {unreadable} | {share(unreadable)} |",
        "",
        (
            f"When the system did give a plate, it was right {100 * correct / given:.1f}% "
            f"of the time ({correct} of {given})."
            if given
            else "The system did not give a plate for any picture."
        ),
    ]
    if total < 100:
        lines += ["", f"Only {total} pictures: treat these figures as rough. The plan asks for 100 or more."]
    if missing:
        lines += ["", f"{missing} listed picture(s) could not be opened and were left out."]
    if mistakes:
        lines += ["", "## Wrong reads", "", "| Picture | True plate | Read as |", "|---|---|---|"]
        lines += [f"| {n} | {e} | {r} |" for n, e, r in mistakes[:50]]
    text = "\n".join(lines) + "\n"

    print("\n" + text)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text)
    print(f"Saved to {args.report}")


if __name__ == "__main__":
    main()
