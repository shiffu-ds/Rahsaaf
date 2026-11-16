# RahSaaf project report

**Date:** 14 November 2026
**Machine used for every figure below:** Intel Core i5-6200U (2 cores, 4
threads), 12 GB RAM, no GPU, Kali Linux.

## Summary

RahSaaf is a working system that finds vehicles parked too long in a marked
no-parking zone, gathers evidence, reads the plate when it can, scores the
effect on traffic, alerts an officer by phone, and records the officer's
decision. All eight planned phases have been built and the software runs end
to end on an ordinary laptop.

**The software is proven; the accuracy is not.** Every test so far used
constructed or stock video. The system has not yet been run on footage of a
real road with wrongly parked vehicles, on a real camera, on real Pakistani
number plates, or against the real Telegram service. Until it is, no accuracy
figure can honestly be quoted.

## What was built

| Part | What it does |
|---|---|
| Detector | Finds and tracks vehicles; decides when one has been parked too long |
| Live stream | Reads a camera on its own thread, always analyses the newest frame, reconnects by itself |
| Evidence | Saves a photo and a clip that starts before the alert |
| Plates | Reads the plate from several frames and accepts it only when they agree |
| Traffic impact | Scores lane blocked, queue length and drop in flow |
| Server | Stores violations, serves the dashboard, sends alerts |
| Alerts | Telegram message with photo, plate, impact, time and map link; retried on failure |
| Dashboard | Login, live alert list, confirm / reject / action taken, plate correction, add-only history |
| Logins | Admins add, disable and reset logins from the dashboard; officers change their own password; changes are logged |
| Network use | HTTPS for phones and computers on the same network, with a secure login cookie |
| Analytics | Hotspot map, by hour and by day, repeat offenders, rejection reasons |
| Training kit | Frame extraction, pre-labelling, dataset split, Colab notebook, evaluation |
| Local vehicle model | Adds auto rickshaws, vans and pickup loaders; trained on this laptop from public data |

About 9100 lines of code and tests.

## What was measured

### Speed

| Measurement | Result | How |
|---|---|---|
| Detection and tracking, default model format | 23.2 frames/s | 100 frames, `tools/benchmark.py` |
| Detection and tracking, OpenVINO square input | 24.6 frames/s | same frames |
| Detection and tracking, OpenVINO wide input (256 x 416) | 35.2 frames/s | same frames |
| One plate read | about 70 ms | second call, after warm-up |
| Whole live pipeline | 4.9 frames/s against a target of 5 | 30-minute soak test |

Exporting the model to OpenVINO gave almost nothing by itself. The gain came
from exporting at a wide shape that matches a camera picture, so no part of
the model's input is wasted on padding.

### 30-minute live soak test

A looped test clip was served as a network stream through the worker and the
server for 1,800 seconds.

| Period | Frames/s | Typical delay | Worst delay |
|---|---|---|---|
| Minutes 0–5 | 4.87 | 235 ms | 674 ms |
| Minutes 5–10 | 4.88 | 284 ms | 369 ms |
| Minutes 10–15 | 4.88 | 297 ms | 382 ms |
| Minutes 15–20 | 4.89 | 273 ms | 355 ms |
| Minutes 20–25 | 4.89 | 269 ms | 382 ms |
| Minutes 25–30 | 4.88 | 286 ms | 387 ms |

- **Delay did not grow.** It is the time from a frame arriving to its analysis
  finishing; a system falling behind would show it climbing.
- **Memory did not grow.** The worker held 685–688 MB throughout, sampled each
  minute.
- **No errors and no reconnects.** 8,790 frames processed; one violation
  raised once and held for the full 30 minutes; all three reports delivered.
- The 674 ms worst case is the first frame, while the plate models load.
- Other jobs ran on the laptop during part of this test. The figures show no
  visible effect, but a clean run would be slightly better evidence.

### Local vehicle model (rickshaws)

YOLO11n was trained on this laptop from the public HeteroTraffic dataset in
two stages: 25 rounds on 1,978 pictures (2 hours 12 minutes), then 20 more
rounds on 4,771 pictures (about 4 hours 20 minutes of training). Measured on
594 pictures the model never saw in either stage:

| Class | Vehicles in test set | Precision | Recall | mAP@50 |
|---|---|---|---|---|
| Car | 746 | 0.83 | 0.76 | 0.84 |
| Rickshaw | 658 | 0.81 | 0.75 | 0.82 |
| Bus | 342 | 0.88 | 0.71 | 0.82 |
| Truck | 182 | 0.78 | 0.64 | 0.71 |
| Motorcycle | 332 | 0.77 | 0.58 | 0.68 |
| Pickup loader | 88 | 0.69 | 0.56 | 0.57 |
| Van | 101 | 0.68 | 0.49 | 0.55 |
| Qingqi | 0 | not measured | | |
| **All** | 2,449 | 0.78 | 0.64 | **0.71** |

- The first stage alone scored 0.66 on these same 594 pictures, so the second
  stage raised every class (van 0.47 to 0.55, pickup loader 0.44 to 0.57).
- At the size the live system uses (256 x 416), it labelled 684 rickshaws in
  those pictures against 658 marked by hand. This is a count, not a matched
  score, and a count above the hand-marked number means some are false.
- Speed is 35.8 frames/s, against 38.0 for the stock model in the same run.
- **A third stage was tried and rejected.** Fifteen more rounds with every
  layer free to change (the first two stages kept the first ten fixed) scored
  higher on the same 594 test pictures: 0.745 overall, better in every class.
  On the real street footage it was worse: it caught 1 of 3 violations where
  the model above caught 2, and it found 0.6 vehicles per picture where the
  model above found 2.3 and the stock model 3.4. It had fitted itself to
  street-level pictures and lost the overhead view. The model above stays;
  the rejected weights are in `data/train_runs/hetero_full`.
- **The lesson: the picture score alone picks the wrong model.** A higher
  mAP on pictures like the training ones went with worse results on a
  different camera view. Any future model is to be judged on fixed-camera
  footage as well.
- **These figures are optimistic.** The split is random per picture and many
  pictures are consecutive shots of one scene. The pictures are from
  Bangladesh at street level; Peshawar footage from an overhead camera will
  score lower, by an unknown amount.
- **Overall 0.71 is below the plan's 0.80 target.**
- On the overhead stock parking clip the local model still reports a pickup
  loader in about half the frames. Checked by eye with the first-stage model,
  that box was on a blue booth, not a vehicle: a false alarm. The street-level
  training pictures do not prepare it for an overhead view.
- **Fixed:** the booth is now marked as an ignore area in the clip's zones
  file. Re-run with the same settings, the clip gives two alerts (the bus and
  a car in the back lot) and no booth alert. This removes the alert at one
  marked spot; it does not make the model better at telling booths from
  vehicles, so a new camera view may need its own ignore areas.
- **The fix no longer depends on someone noticing.** Each alert now records
  its box, and `tools/learn_ignore.py` proposes an ignore area for any spot
  rejected as "Not a vehicle" twice or more. Tested end to end on a throwaway
  server: two booth alerts rejected, the tool proposed one area, and the next
  run raised the bus and car alerts only. A person still has to run the tool
  and apply the result.
- **One real clip, checked by eye.** In the 14-second overhead clip, four
  vehicles stand in the back lot for the whole clip (a bus, a minibus, a van
  and a covered truck). With a 5-second grace period the system flagged two
  of them and, once the booth was ignored, nothing that was not a vehicle.
  That is 2 of 2 alerts correct and 2 of 4 standing vehicles found, on one
  short, blurred clip: far too little to call precision or recall.
- The stock model remains the default. The local one is chosen with
  `--weights models/local_openvino_model`.

### Behaviour

| Check | Result |
|---|---|
| Parked vehicle on a constructed clip | Exactly one violation, at the configured time |
| Vehicle driving through the zone | Not flagged |
| Vehicle standing outside the zone | Ignored |
| Stream cut for 3 seconds mid-violation | Reconnected by itself; same violation continued, no duplicate alert |
| Alert delivery, to a stand-in for Telegram on the same machine | Under 2 seconds from violation to alert |
| Painted test plate "LEA 1234" | Read correctly, 3 of 3 frames agreeing, about 1 second |
| Dashboard in a browser | Login, live update, confirm, reject, plate correction, analytics all worked |
| Fresh install in an empty folder | Installed, all tests passed, dashboard built, server started, detection ran |
| HTTPS on the local network | Answered over HTTPS on the loopback and network addresses; plain HTTP got no reply; login cookie marked Secure; a worker report from the network address was refused |
| Login management in a browser | Admin saw the login list, disabled a login, and the change appeared in the log |

### Automated tests

251 tests, all passing, in about one minute. They cover the parking rules,
zone geometry, stream reconnection, evidence clips, plate voting, traffic
impact, the server, login and lockout, reviews and the add-only history,
analytics, and alert sending.

## What was found and fixed along the way

Problems that only showed up by running the system, not by reading the code:

1. **Vehicles that had driven away lingered** for five seconds and could pass
   their timer to the next vehicle through the same spot.
2. **One vehicle reported as two violations** when a multi-class model gave
   it two labels.
3. **A mistyped plate correction wiped the plate** instead of being refused.
4. **The dashboard did not load** when the server was started from another
   folder; a second, empty database was silently created.
5. **A fresh install chose an untested Python version** and began downloading
   a second set of large packages. The project is now pinned to Python 3.11.
6. **The first frame arrived late** because the model compiled on first use;
   it is now warmed up before the camera opens.

## What has not been measured

These are the plan's accuracy targets. None has a figure yet, and each needs
material that only real-world use can provide.

| Target in the plan | Status | What is needed |
|---|---|---|
| Vehicle detection, mAP@50 of 0.80 or higher | Not met: 0.71 on public pictures from Bangladesh; not measured on Peshawar footage | A model trained on local footage (`docs/TRAINING.md`) |
| Violation precision of 0.90 or higher | First figure only: 2 alerts, both real, on 17 minutes of public street footage (`docs/VIOLATION_REPORT.md`). Too few to count as met | 20–30 real clips with violations marked by hand |
| Violation recall of 0.85 or higher | First figure only: 2 of 3 real violations caught on the same footage. Too few to count | The same clips |
| Plate accuracy | On 256 public photos of Pakistani cars: 87% read correctly, 1% wrongly, 12% declined, after a fix for the year badge on Punjab plates (53%, 10% and 37% before it). The fix was tuned on these same photos, so this is optimistic (`docs/PLATE_REPORT.md`) | Plates from a real parking camera, with a list of the true plates, that the fix has not seen |
| Alert within 10 seconds | Met on a stand-in only | A real Telegram bot |
| 5 frames/s or better | Met (4.9 at a target of 5) | — |
| 30 minutes without lag growing | Met on a local stream | A real camera for a like-for-like check |

**First measurement on real street footage (16 November 2026).** Three
sequences of the public Street Scene dataset, 17 minutes 20 seconds from a
fixed camera above a two-lane street, with three real violations marked by
the dataset's authors and a 30-second grace period:

| Model | Real | Caught | Missed | False alarms |
|---|---|---|---|---|
| Local model | 3 | 2 | 1 | 0 |
| Stock model | 3 | 0 | 3 | 2 |

The local model caught a pickup double-parked in the lane and a car stopped
at the corner kerb, and missed a second corner-kerb car when its detection
flickered at 22 of 30 seconds. The stock model caught nothing and twice
flagged a legally parked SUV. Every alert and miss was checked by eye, and
the zones were not changed after seeing the results. Three violations on one
American street in daylight is far too little to claim the targets; what it
does show is that the local model works on footage it was not trained on and
is better than the stock model there. Details and the commands to repeat it
are in `docs/VIOLATION_REPORT.md`.

The miss was traced to the detection's confidence dipping just under the
cut-off, which restarted the timer. The tracker now starts following a
vehicle at 0.3 and keeps following it down to 0.15. With that change the
corner car is caught; the pickup, which stood in one place for almost
exactly the 30-second grace period, is caught or missed by a fraction of a
second either way. With a 20-second grace period all three are caught with
no false alarms. The change was made after seeing these clips, so this is
not independent proof.

An earlier result on a stock clip was not good: on a stock clip
with small, blurred trucks standing in the distance, the stock model detected
them only now and then and raised no violation. No false alarms occurred on
the moving cars in the same clip. The clip was a sped-up time-lapse, so this
is weak evidence, but it points at the system's likely weak spot: small or
distant vehicles.

## Known limits

- **Vehicle types.** The stock model knows cars, motorcycles, buses and
  trucks. The optional local model adds rickshaws, vans and loaders but
  learned them from Bangladeshi street pictures. **Neither detects Qingqis**;
  no public pictures exist, so that needs your own.
- **Traffic jams.** A jam inside a marked zone can be flagged as parking. A
  suppression rule was planned and deliberately not built: without real
  footage to tune it, a wrong rule could hide the vehicles causing the worst
  jams. Officers can reject such alerts with the reason "not parked".
- **Small or distant vehicles** are often missed.
- **Plates.** The reader was trained on plates from many countries, not on
  Pakistani ones. Distant, dirty, angled or non-standard plates will mostly
  come back "not readable", which is the intended safe failure.
- **Traffic impact weights** (50 / 30 / 20) are a first guess. The flow part
  has never been exercised on moving traffic.
- **Stream gaps.** If a stream is down for more than five seconds, parking
  timers restart.
- **Night and rain** are untested.
- **Deployment.** HTTPS works on a local network with a self-signed
  certificate, which browsers warn about once. It has not been opened from a
  real phone, and it is not set up for the open internet.
- **One camera per worker.** Several cameras need several workers.

## What to do next, in order

1. **Record footage** at five or more places in Peshawar where wrong parking
   is common. Everything else depends on this.
2. **Mark the violations by hand** in 20–30 of those clips and run
   `tools/evaluate_violations.py`. This gives the first real precision and
   recall.
3. **Create the Telegram bot** and confirm an alert reaches a phone.
4. **Label pictures and train the local model** (`docs/TRAINING.md`), then
   repeat step 2 with it and compare.
5. **Collect 100 plate pictures** and run `tools/evaluate_plates.py`.
6. **Tune** the grace period, the impact weights and, with enough examples,
   a jam rule.
7. **Run it on a real camera** for a day and review every alert.

## Ethics and privacy

- The system gives an officer evidence. It issues no fines and has no access
  to vehicle ownership records.
- It reads plates only for vehicles already flagged, and reports "not
  readable" rather than guess.
- It does not recognise faces or track people.
- Every decision is recorded with the officer's name and cannot be edited or
  deleted.
- Before any real use: written approval from Peshawar traffic police, a
  retention period for evidence, and HTTPS in front of the dashboard.

## Third-party software

| Software | Use | Licence |
|---|---|---|
| Ultralytics YOLO11 | Vehicle detection and tracking | AGPL-3.0 |
| OpenVINO | Faster inference on Intel CPUs | Apache-2.0 |
| fast-alpr | Plate detection and reading | MIT |
| FastAPI, React, Leaflet | Server, dashboard, map | MIT / BSD |
| OpenStreetMap | Map tiles on the analytics page | ODbL; attribution shown |
| HeteroTraffic dataset (Sagar and Koli, Mendeley Data, DOI 10.17632/tvkfk56s2k.2) | Training pictures for the local vehicle model | CC BY 4.0; credit required |
| Pakistani License Number Plates Data Set (iAhsanJaved, GitHub) | Test photos for plate reading; not used for training | No licence stated; kept on one computer only and not redistributed |
| Street Scene dataset (Ramachandra and Jones, WACV 2020, MERL; Zenodo DOI 10.5281/zenodo.10870471) | Test footage for violation detection; not used for training | CC BY-SA 4.0; credit required, footage itself is not in this repository |

The AGPL licence on Ultralytics has conditions for distributing or hosting
software built on it. Check them before publishing or deploying this project.
