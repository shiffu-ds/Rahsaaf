# Violation detection report

First measurement on real street footage. Read the limits at the end before
quoting any figure.

- Footage: three sequences (Test010, Test029, Test032) of the Street Scene
  dataset, a fixed camera looking down on a two-lane street with metered
  parking. 17 minutes 20 seconds in total, at 5 pictures per second.
- Zones: kept in `tools/prepare_streetscene.py`, drawn by hand before any run:
  the traffic lanes, and the corner kerb beyond the last parking bay.
- Grace period: 30 seconds.
- Real violations: 3, taken from the dataset's own hand-made marks (vehicles
  standing in a zone for longer than the grace period) and checked by eye.
- Date: 2026-11-16

| Model | Real | Caught | Missed | False alarms | Precision | Recall |
|---|---|---|---|---|---|---|
| Local model (`models/local_openvino_model`) | 3 | 2 | 1 | 0 | 1.00 | 0.67 |
| Stock model (`models/yolo11n_openvino_model`) | 3 | 0 | 3 | 2 | 0.00 | 0.00 |

Per clip, local model:

| Clip | What happens | Result |
|---|---|---|
| Test029 | Pickup double-parked in the traffic lane, 87 s | Caught, alert 55 s after it first stopped (it moved once in between) |
| Test032 | Car stopped at the corner kerb, 304 s | Caught, alert 63 s after it arrived |
| Test010 | Car stopped at the corner kerb, 61 s | Missed: the timer reached 22 of 30 s, then the detection flickered and it reset |

Per clip, stock model:

| Clip | Result |
|---|---|
| Test029 | Missed: the timer reached 17 of 30 s and never confirmed |
| Test032 | Missed |
| Test010 | Missed, and two false alarms on one legally parked SUV whose box reached into the lane zone |

Every alert and every miss above was looked at on the annotated video.

## Why vehicles were missed, and what was changed

The missed corner car was seen in almost every picture, but at a confidence
that kept dipping just under the 0.3 cut-off: gaps of up to 14.8 s at 0.3,
against 3.6 s at 0.15. Each dip dropped the vehicle and restarted its timer.

The tracker now uses two thresholds (`worker/bytetrack_rahsaaf.yaml`): 0.3 to
start following a vehicle, 0.15 to keep following one it already follows. A
weak detection still cannot start an alert. Re-run with the local model:

| Grace period | Real | Caught | Missed | False alarms |
|---|---|---|---|---|
| 30 s, one threshold (the first table) | 3 | 2 | 1 | 0 |
| 30 s, two thresholds | 3 | 2 | 1 | 0 |
| 20 s, two thresholds | 3 | 3 | 0 | 0 |

At 30 s the total is the same but the miss moved. The corner car in Test010
is now caught. The double-parked pickup in Test029 is now missed at 27 of
30 s: it stood in one place for almost exactly 30 seconds before pulling
forward, and the first run caught it with 0.2 s to spare. That catch was
luck, and so is this miss. At 20 s all three are caught, still with no false
alarms.

**This change was made after looking at these clips, so the rows above are
not independent evidence that it helps.** They show it did no harm here and
removed the flicker that caused the first miss. It needs footage it has not
seen to be counted as proven.

A second weakness is visible and was left alone: a vehicle that pulls
forward a few car lengths inside a no-parking zone restarts its timer. The
pickup was in the lane for 87 s in three separate stops.

## A model that scored higher on pictures did worse here

A later training run, with every layer free to change, reached 0.745 on the
test pictures against 0.714 for the local model above. On this footage:

| Model | Picture score (mAP@50) | Caught of 3 | False alarms | Vehicles found per picture |
|---|---|---|---|---|
| Local model (in use) | 0.714 | 2 | 0 | 2.3 |
| Later run (rejected) | 0.745 | 1 | 0 | 0.6 |
| Stock model | not comparable | 0 | 2 | 3.4 |

It never drew a box on the double-parked pickup at all. It did catch the
long corner-kerb stop sooner (alert 34 s after arrival against 63 s). It was
not adopted.

The last column also shows the local model finds fewer vehicles in this
overhead view than the stock model does. Its advantage here is steadier
boxes on the vehicles it does find, not finding more of them.

## What this does and does not show

- **The local model beat the stock model on real footage**, on catches and on
  false alarms. That is the main finding.
- **Three violations is far too few for a precision or recall figure.** One
  more miss or catch would move recall by a third. The plan's targets
  (precision 0.90, recall 0.85) are neither met nor failed by this.
- **No false alarms in 17 minutes** of passing traffic and legally parked
  cars is the more solid half of the result for the local model.
- **The corner car is a hard case**: it is half cut off by the top edge of
  the picture. Both late alerts and the miss come from its detection
  flickering, which resets the timer. A camera should be aimed so that
  no-parking areas are not at the edge of the view.
- **One street, daytime, one camera angle, in the United States.** No
  rickshaws, no motorcycles standing, no night, no rain. It says nothing yet
  about Peshawar.
- The zones were not changed after seeing the results.

## Reproduce

```bash
uv run python tools/fetch_streetscene.py get StreetScene/Test/Test029/0 StreetScene/Test/Test010/0 StreetScene/Test/Test032/0 --every 3 --limit-gb 1.5
```

```bash
uv run python tools/prepare_streetscene.py
```

```bash
uv run python tools/evaluate_violations.py data/eval/streetscene/truth.json --weights models/local_openvino_model --skip 1 --imgsz 256 416 --report docs/VIOLATION_REPORT_RUN.md
```

The first command downloads about 1.3 GB.

Footage: Street Scene, Ramachandra and Jones, WACV 2020, Mitsubishi Electric
Research Laboratories. Zenodo DOI 10.5281/zenodo.10870471, CC BY-SA 4.0.
