# Plate reading report

First measurement on real Pakistani number plates.

- Pictures: 256 photos of cars from the public set
  `iAhsanJaved/Pakistani-License-Number-Plates-Data-Set` on GitHub (Punjab,
  Islamabad, Sindh and a few KPK plates).
- Each picture was read once, shrunk to 1920 pixels wide first.
- The set has no list of correct plates. Every reading the system accepted,
  before and after the fix, was compared with the plate picture by eye, by
  the assistant that built this project, not by a second person.
- Date: 2026-11-16

| Outcome | Before the fix | After the fix |
|---|---|---|
| Plate found in the picture | 256 (100%) | 256 (100%) |
| Reading accepted and correct | 135 (53%) | 222 (87%) |
| Reading accepted and **wrong** | 25 (10%) | 3 (1%) |
| Reading declined | 96 (37%) | 31 (12%) |
| Of accepted readings, correct | 84% | 99% |

"Correct" means the registration letters and number match. The small year
badge on Punjab plates is not part of the registration and was ignored.

**The "after" column is optimistic.** The fix was designed and its two
thresholds were chosen while looking at these same 256 photos, and there is
no second set to check it on. Expect a real camera to do worse than both
columns. What the table does show is that the fault below is real and that
the fix removes it without breaking the plates that were already read well.

## The fault: the year badge

Punjab plates carry a small two-digit year beside the letters, as in
"ABC·17" over "357". Read whole, the year was taken for the start of the
number: "ABC1735". With a four-digit number the result was too long to be a
plate and was declined; with a three-digit number it still looked like a
plate and was accepted, wrongly. That was 19 of the 25 wrong readings and
most of the declined ones.

## The fix

The reader now also reads the top and bottom halves of the plate on their
own (`combine_two_line` in `worker/plates.py`):

- If the top half reads as letters, with or without two digits, and the
  bottom half reads as a number, the plate has two lines. Otherwise nothing
  changes, so one-line Sindh, Islamabad and KPK plates are untouched.
- The letters are taken from the whole-plate reading, which reads them
  better than a thin strip does. The number is taken from the bottom line.
- If the bottom line disagrees with the whole plate and is not very sure of
  itself (under 0.9), no reading is given.
- If the two readings disagree on how many letters there are, no reading is
  given. This caught a second fault found on the way: a "B" taken for an
  "8", turning "LEB" into "LE".

It costs two more character-reading passes per plate; 256 photos take about
21 seconds on this laptop either way.

## What is still wrong

Three readings are still accepted and wrong: one where the year badge and a
misread digit combine, one "W" read as "V", and one photo where the bottom
of the plate is cut off.

## What this means

- **A plate reading is still a suggestion for the officer to check**, shown
  beside the plate picture and correctable. One good result on easy photos
  does not change that.
- **These photos are easier than camera footage**: close, sharp and well
  lit. A parking camera will read fewer plates.
- The plate texts are not listed here because they belong to real vehicles.
  The photos, the per-picture results and the list of true plates stay on
  this computer (`data/plates_pk`, not in git). The photo set states no
  licence, so it is not redistributed.

## Reproduce

The true plates for 234 of the photos, read by eye, are in
`data/plates_pk/truth.csv`. The other 22 were declined both before and after
and were not transcribed.

```bash
uv run python tools/evaluate_plates.py data/plates_pk/repo/Cars --report docs/PLATE_REPORT_RUN.md
```

On those 234 it gives 221 correct, 2 wrong and 11 declined. It reads the
photos at full size, where the table above shrank them to 1920 pixels wide,
which accounts for the one-photo difference.
