# RahSaaf — Real-Time Illegal Parking Detection and Alert System

**Implementation plan and pipeline design**

| | |
|---|---|
| Working name | RahSaaf ("clear road") — placeholder, change freely |
| Target city | Peshawar, Pakistan |
| Document date | 13 November 2026 |
| Status | Original plan. See "Where the build stands" below. |
| Target hardware | Intel Core i5 (6th gen), 12 GB RAM, no GPU |

---

## Where the build stands

This plan was written before any code. The table records what happened to
each phase; the measured results are in [REPORT.md](REPORT.md).

| Phase | State | Differences from the plan |
|---|---|---|
| 0. Setup | Done | No Peshawar footage was recorded; testing used constructed and stock clips |
| 1. Core detection | Built | Jam suppression (6.3) was left out: it cannot be tuned without real footage |
| 2. Live stream | Built | Tested on a stream served locally, not a real camera |
| 3. Local model | Tools only | No model trained: it needs footage, labelling and a Colab run |
| 4. Alerts | Built | Tested against a stand-in for Telegram, not the real service |
| 5. Dashboard | Built | No screen for managing logins; a command-line tool is used |
| 6. Plates | Built | An open-source reader is used in place of a trained plate model; unmeasured on Pakistani plates |
| 7. Analytics | Built | Double parking is the "lane blocked" part of the impact score, not a separate alert |
| 8. Finish | Done | No demo video recorded; a demo script is provided |

## 1. Summary

RahSaaf watches a live road camera, detects vehicles parked in no-parking areas
for longer than an allowed time, and sends traffic police an alert containing a
photo, the time, the number plate (when readable) and a map link to the
location. An officer confirms or rejects each alert before any action is taken.

The system is designed to run on an ordinary computer with no GPU, so that it
can be used in places the Safe City camera network does not cover: bazaars,
hospital gates, university roads and private plazas.

### What makes it different

1. **Low cost.** Runs on a CPU-only machine with a cheap IP camera or a phone.
2. **Local vehicles.** A model trained on rickshaws, Qingqis, loaders and
   motorbikes, not only cars.
3. **Congestion priority.** Violations are ranked by how much traffic they
   block, so police go to the worst case first.
4. **Human decision.** The system prepares evidence. An officer decides.

---

## 2. Goals and non-goals

### Goals

- Detect a vehicle that stays stationary inside a marked no-parking zone longer
  than a configurable grace period.
- Work on a live stream at 5 frames per second or better on the target hardware.
- Send an alert to a phone within 10 seconds of a violation being confirmed.
- Save evidence: one photo, one short clip, timestamps, camera location.
- Read the number plate when it is visible, and say so clearly when it is not.
- Give officers a dashboard to confirm or reject, with every decision logged.
- Report measured accuracy for every model and for the violation logic.

### Non-goals

- **No automatic challan.** Matching a plate to an owner needs the Excise and
  Taxation database, which this project has no access to.
- **No face recognition** and no tracking of people.
- **No city-scale deployment.** The design supports many cameras, but the
  build and demo target one or two.

---

## 3. Scope by priority

| Priority | Feature | Phase |
|---|---|---|
| Must | Parked-too-long detection on recorded video | 1 |
| Must | Same detection on a live stream | 2 |
| Must | Model trained on local vehicles, with measured accuracy | 3 |
| Must | Phone alert with photo, time, map link | 4 |
| Should | Officer dashboard with confirm / reject and audit log | 5 |
| Should | Number plate reading | 6 |
| Could | Congestion impact score | 7 |
| Could | Hotspot map and repeat-offender list | 7 |
| Could | Double-parking detection | 7 |

Finish every "Must" before starting any "Should". Three features that work
reliably are worth more than ten that half work.

---

## 4. Hardware constraints and how the design answers them

| Constraint | Design answer |
|---|---|
| No GPU for inference | Smallest YOLO model, exported to OpenVINO, 416 px input |
| No GPU for training | Train on Google Colab or Kaggle free GPU, download the weights |
| Limited CPU | Analyse every 3rd to 5th frame; parking is slow-moving |
| Plate reading is heavy | Run it once per confirmed violation, on a cropped image |
| Disk fills up | Save a clip and photo per violation only, never continuous video |
| One machine | One live stream as the target, two as the stretch |

**Expected speed:** roughly 5–10 processed frames per second. This is an
estimate and must be measured in Phase 2 before anything else is built on it.

---

## 5. System architecture

```
 ┌──────────────┐  RTSP / HTTP   ┌─────────────────────────────────────────┐
 │  IP camera   │ ─────────────► │            DETECTION WORKER             │
 │  or phone    │                │                                         │
 └──────────────┘                │  frame reader ─► detector ─► tracker    │
                                 │                        │                │
                                 │                        ▼                │
                                 │         zone test ─► parking state      │
                                 │                        machine          │
                                 │                        │                │
                                 │                        ▼                │
                                 │       evidence capture ─► plate reader  │
                                 └────────────────────────┬────────────────┘
                                                          │ violation record
                                                          ▼
 ┌──────────────┐   HTTPS    ┌──────────────────────────────────────────┐
 │  Telegram    │ ◄───────── │               API SERVER                 │
 │  (officer's  │            │   FastAPI · SQLite · evidence files      │
 │   phone)     │            │   auth · alert sender · analytics        │
 └──────────────┘            └───────────────────┬──────────────────────┘
                                                 │ REST + live events
                                                 ▼
                             ┌──────────────────────────────────────────┐
                             │            OFFICER DASHBOARD             │
                             │  live feed · alert queue · map · reports │
                             └──────────────────────────────────────────┘
```

**Two separate processes.** The detection worker and the API server run
separately. If the dashboard is slow or restarts, detection keeps running, and
the reverse. The worker sends each violation to the API over a local HTTP call.

---

## 6. Pipelines

### 6.1 Data and training pipeline (offline, on Colab or Kaggle)

```
record footage ─► extract frames ─► label ─► split ─► train ─► evaluate ─► export
   (phone)         (1 per 1–2 s)    (boxes)  70/20/10  (GPU)    (mAP)    (OpenVINO)
```

| Step | Detail |
|---|---|
| Record | 3–5 locations in Peshawar, morning, afternoon and evening. Film from a height (rooftop, window, overhead bridge) to copy a CCTV angle. |
| Extract | One frame every 1–2 seconds. Remove near-duplicates. |
| Label | Roboflow, CVAT or Label Studio. Target 1,500–3,000 images. |
| Classes | `car`, `motorcycle`, `rickshaw`, `qingqi`, `van`, `bus`, `truck`, `pickup_loader` |
| Split | 70% train, 20% validation, 10% test. Split by video, not by frame, so the test set is honest. |
| Train | Start from pretrained YOLO11n weights and fine-tune. |
| Evaluate | mAP@50 overall and per class, on the test set only. |
| Export | OpenVINO format at 416 px. Copy to the laptop. |

Public datasets can add to your own footage. Search Roboflow Universe and
Kaggle for auto-rickshaw and Pakistani number-plate sets, and check each
licence before use.

A second, smaller model is trained the same way for **number plates** (one
class: `plate`).

### 6.2 Real-time detection pipeline (on the laptop)

```
camera ─► reader thread ─► frame skip ─► resize ─► detect ─► track ─► zone test
                                                                         │
            alert ◄── evidence ◄── violation confirmed ◄── parking state machine
```

| Stage | What it does | Notes |
|---|---|---|
| Reader thread | Reads the stream and keeps only the newest frame | Prevents lag building up; reconnects if the stream drops |
| Frame skip | Passes on every Nth frame | N = 3 to 5, set in config |
| Resize | Scales to the model input size | 416 px |
| Detect | Vehicle detection | Fine-tuned YOLO11n, OpenVINO |
| Track | Gives each vehicle a stable ID | ByteTrack |
| Zone test | Checks whether the vehicle is in a no-parking zone | Uses the bottom-centre point of the box, where the wheels meet the road |
| State machine | Decides whether it is parked too long | Section 6.3 |
| Evidence | Saves photo and clip | A rolling buffer of the last ~10 seconds makes the clip possible |

### 6.3 Parking state machine

Each tracked vehicle inside a zone is in one of these states:

```
            enters zone              stopped                grace period over
  OUTSIDE ─────────────► MOVING ──────────────► STOPPED ─────────────────────► VIOLATION
     ▲                     ▲                       │                               │
     │                     └───────────────────────┘                               │
     │                          moves again                                        │
     └─────────────────────────────────────────────────────────────────────────────┘
                              leaves the zone (violation closed, duration saved)
```

**Rules**

- **Stopped** means the vehicle's box has barely moved over a short window. The
  test is overlap between its current box and its box a few seconds ago; high
  overlap means stationary.
- **Grace period** is configurable per zone. Start with 120 seconds for real
  use and 20 seconds for demos.
- **Brief disappearance does not reset the timer.** If a bus hides the vehicle
  for a few seconds, the timer continues.
- **Tracker ID changes are handled.** If a new ID appears in almost exactly the
  same place as a stopped vehicle that just vanished, it inherits the timer.
- **One alert per violation.** When the vehicle leaves, the violation is closed
  and its total duration is recorded.

**False alarms to design against**

| Situation | Handling |
|---|---|
| Traffic jam or red signal | Many vehicles stopped in the driving lane at once; suppress alerts while the whole lane is stationary |
| Passenger drop-off | Covered by the grace period |
| Vehicle outside the zone but overlapping it in the picture | The bottom-centre point test, not the whole box |
| Ambulance or police vehicle | Officer rejects it; a later version could add an exempt class |

### 6.4 Plate reading pipeline

Runs once, when a violation is confirmed.

```
vehicle crop ─► plate detector ─► plate crop ─► enhance ─► OCR ─► validate ─► result
                                                                       │
                                                  low confidence ─► "unreadable, see photo"
```

| Step | Detail |
|---|---|
| Vehicle crop | Cut from the full-resolution frame, not the resized one |
| Plate detector | The one-class plate model from 6.1 |
| Enhance | Upscale, greyscale, contrast |
| OCR | PaddleOCR; evaluate EasyOCR as the alternative and keep whichever scores higher on your test plates |
| Multi-frame vote | Read the plate from several frames and keep the most common result |
| Validate | Check the text against Pakistani plate patterns (letters then digits) |
| Fallback | Below a confidence threshold, store "unreadable" and send the photo anyway |

Never guess a plate. A wrong plate in an alert is worse than no plate.

### 6.5 Alert pipeline

```
violation ─► build message ─► send to Telegram ─► log delivery ─► retry on failure
```

Each alert contains:

- Photo of the vehicle with the zone outlined
- Vehicle type and number plate, or "plate unreadable"
- Time and how long it has been parked
- Camera name and a Google Maps link built from the camera's saved coordinates
- Congestion impact level (once Phase 7 exists)
- A link to the incident in the dashboard

**Why Telegram first:** its bot API is free and needs no approval. WhatsApp
Business needs a registered business and paid messaging, so it is a later
option.

**Location:** the camera is fixed, so each camera's latitude and longitude are
stored once when it is set up. No live GPS is needed.

### 6.6 Officer review pipeline

```
new alert ─► PENDING ─► officer opens it ─► CONFIRMED ─► ACTION TAKEN
                                       └──► REJECTED (with a reason)
```

- Every decision records who made it, when, and any note.
- Review records are only ever added, never edited or deleted.
- Rejected alerts are kept with their reasons. They show where the system is
  wrong and become training data for the next model.

### 6.7 Congestion impact pipeline (Phase 7)

Measures how badly a parked vehicle is affecting traffic.

| Signal | How it is measured |
|---|---|
| Flow drop | Vehicles crossing a counting line per minute, compared with the normal rate for that camera and hour |
| Queue | Number of slow or stopped vehicles in the region behind the parked vehicle |
| Lane blocked | How much of the driving lane the parked vehicle covers |

```
impact = 0.5 × flow drop + 0.3 × queue + 0.2 × lane blocked     (each scaled 0 to 1)
```

These weights are a starting point to be tuned on real footage. The result is
shown as Low, Medium or High and used to sort the alert queue.

---

## 7. Technology choices

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11 | Best library support for vision work |
| Detection | Ultralytics YOLO11n | Small and fast; note its AGPL-3.0 licence |
| CPU acceleration | OpenVINO | Built for Intel processors |
| Tracking | ByteTrack | Light and reliable |
| Video | OpenCV | Stream reading, drawing, clip writing |
| Plate OCR | PaddleOCR or EasyOCR | Both run on CPU |
| API | FastAPI | Simple, fast, automatic API docs |
| Database | SQLite | Enough for one site; no server to manage |
| Live updates | Server-Sent Events | Simpler than WebSockets for one-way updates |
| Dashboard | React + Vite | Light, fast to develop |
| Map | Leaflet + OpenStreetMap | Free, no API key |
| Alerts | Telegram Bot API | Free, immediate |
| Login | JWT with hashed passwords | Standard and small |
| Training | Google Colab or Kaggle | Free GPU |

---

## 8. Data model

**cameras**

| Field | Meaning |
|---|---|
| id, name | Identity |
| stream_url | RTSP or HTTP address |
| latitude, longitude | Fixed location for the map link |
| active | Whether the worker should read it |

**zones**

| Field | Meaning |
|---|---|
| id, camera_id, name | Identity |
| polygon | Points marking the no-parking area on the camera view |
| grace_seconds | Allowed stopping time |
| active_hours | Optional: hours when the rule applies |

**violations**

| Field | Meaning |
|---|---|
| id, code | Identity, for example `PV-20261113-0042` |
| camera_id, zone_id | Where |
| vehicle_class, detection_confidence | What |
| started_at, confirmed_at, ended_at, duration_seconds | When and how long |
| plate_text, plate_confidence | Plate, or empty when unreadable |
| photo_path, clip_path | Evidence |
| impact_score, impact_level | Congestion impact |
| status | Pending, Confirmed, Rejected, Action Taken |

**reviews** (add-only)

| Field | Meaning |
|---|---|
| id, violation_id, officer_id | Who reviewed what |
| decision, reason, note | The decision |
| created_at | When |

**officers** — id, name, username, password hash, role (admin or officer), Telegram chat ID.

**alert_log** — violation, channel, sent time, success or error.

---

## 9. API outline

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | Officer login |
| GET | `/cameras` · POST `/cameras` | List and add cameras |
| GET | `/cameras/{id}/zones` · PUT `/zones/{id}` | Read and edit zones |
| POST | `/internal/violations` | Worker reports a violation (local only) |
| GET | `/violations` | List with filters: status, camera, date, plate |
| GET | `/violations/{id}` | One violation with its review history |
| POST | `/violations/{id}/review` | Confirm or reject |
| GET | `/events` | Live stream of new violations for the dashboard |
| GET | `/analytics/hotspots` | Counts by zone and hour |
| GET | `/analytics/repeat-offenders` | Plates with multiple violations |
| GET | `/health` | Worker and stream status |

---

## 10. Project structure

```
rahsaaf/
├── worker/                  # detection process
│   ├── stream.py            # reader thread, reconnect
│   ├── detector.py          # OpenVINO YOLO wrapper
│   ├── tracking.py          # ByteTrack wrapper
│   ├── zones.py             # polygon tests
│   ├── parking_state.py     # state machine (6.3)
│   ├── evidence.py          # rolling buffer, photo, clip
│   ├── plates.py            # plate pipeline (6.4)
│   ├── congestion.py        # impact score (6.7)
│   └── main.py
├── api/                     # FastAPI server
│   ├── main.py
│   ├── auth.py
│   ├── db.py
│   ├── models.py
│   ├── alerts.py            # Telegram sender
│   ├── analytics.py
│   └── routes/
├── dashboard/               # React app
├── training/                # Colab notebooks, dataset config
├── models/                  # exported weights (not in git)
├── data/                    # database, evidence (not in git)
├── tests/
├── docs/
├── .env.example
└── README.md
```

---

## 11. Phased plan

Durations assume part-time work by one person. Adjust to your deadline.

| Phase | Weeks | Work | Done when |
|---|---|---|---|
| 0. Setup | 1 | New folder, git, Python environment, record first footage | Repo exists; 30+ minutes of footage from 3 locations |
| 1. Core detection | 2 | Pretrained model on recorded video, zone drawing, state machine | A parked car in a test clip raises exactly one violation; a passing car raises none |
| 2. Live stream | 1 | Reader thread, frame skip, OpenVINO export, speed measurement | Runs on a phone camera stream for 30 minutes without lag growing; frames per second recorded |
| 3. Local model | 2 | Label data, train on Colab, evaluate, export | mAP@50 reported per class; rickshaws and Qingqis detected |
| 4. Alerts | 1 | API server, database, evidence saving, Telegram bot | A violation produces a phone alert with photo and map link within 10 seconds |
| 5. Dashboard | 2 | Login, alert queue, confirm / reject, audit log, live updates | An officer can confirm an alert and the decision is logged |
| 6. Plates | 2 | Plate model, OCR, voting, fallback | Plate accuracy measured on 100+ test plates |
| 7. Analytics | 2 | Congestion score, hotspot map, repeat offenders | Alert queue sorted by impact; map shows hotspots |
| 8. Finish | 1 | Testing, README, demo video, report | A stranger can install and run it from the README |

**Total:** about 14 weeks. Phases 0–4 (7 weeks) give a complete, demonstrable
system on their own.

---

## 12. Testing and measurement

### Automated tests

- State machine: synthetic tracks for parked, passing, drop-off, jam, occlusion
  and ID-switch cases. No video or model needed, so they run in seconds.
- Zone geometry: points inside, outside and on the edge.
- Plate validation: valid and invalid plate strings.
- API: login, review, add-only audit behaviour.

### Measured results to report

| Measure | How | Target |
|---|---|---|
| Vehicle detection | mAP@50 on the held-out test set | 0.80 or higher overall |
| Violation precision | Of the alerts raised, how many were real | 0.90 or higher |
| Violation recall | Of the real violations, how many were caught | 0.85 or higher |
| Plate accuracy | Fully correct reads on test plates | Report honestly, including the unreadable share |
| Speed | Processed frames per second on the target laptop | 5 or higher |
| Alert delay | Violation confirmed to phone alert | Under 10 seconds |

Targets are goals, not promises. Report what you actually measure, including
day versus night, and where the system fails.

To measure violation precision and recall, hand-label 20–30 test clips with the
true start and end of every illegal parking event, and compare.

---

## 13. Risks

| Risk | Likelihood | Response |
|---|---|---|
| Plate reading is poor on distant or dirty plates | High | Fallback to "unreadable"; treat plates as a bonus, not the core |
| Laptop is too slow | Medium | Smaller input size, higher frame skip, quantised model |
| Not enough labelled data | Medium | Start with the pretrained classes; add local classes gradually |
| Jams cause false alerts | Medium | Lane-wide stationary check; longer grace period |
| Night and rain reduce accuracy | High | Test and report it; recommend a camera with infrared |
| Scope too large for the time | High | Follow the priority order in section 3 |
| No access to a real CCTV stream | Certain | Use a phone as the camera; this is enough for a demo |

---

## 14. Privacy, legal and ethics

- Film only public roads. Ask permission before filming from private property.
- Blur faces in any footage or screenshots you publish.
- Keep evidence for a fixed time, such as 30 days, then delete it.
- Protect the dashboard with a login; plates and locations are personal data.
- Present the system as decision support. The officer, not the software, is
  responsible for any fine.
- Before any real use, get written approval from Peshawar traffic police.

---

## 15. Demo plan

1. Mount a phone at a window overlooking a road, streaming to the laptop.
2. Show the live view with the no-parking zone outlined.
3. A vehicle stops in the zone; the timer appears above it.
4. After the grace period (20 seconds for the demo) it turns red.
5. The alert arrives on a phone: photo, plate, time, map link.
6. Open the dashboard, confirm the alert, show the audit log.
7. Show the hotspot map and the measured accuracy table.

Keep a recorded video as a backup in case the live stream fails on the day.

---

## 16. Keeping this project your own

This project was inspired by a friend's surveillance project. To keep it fully
independent:

- Start in a new, empty folder with its own git history.
- Write every file yourself. Do not copy code, README text, formulas or
  dashboard design from the other project.
- Using the same public tools (YOLO, FastAPI, OpenCV) is normal and not copying.
- Tell your friend what you are building, and credit the inspiration in your
  README.

---

## 17. First steps

1. Choose the final project name.
2. Create the new folder and run `git init`.
3. Record footage at three Peshawar locations where wrong parking is common.
4. Install Python 3.11, OpenCV and Ultralytics.
5. Run the pretrained model on one clip and confirm vehicles are detected.
6. Begin Phase 1: draw a zone and build the parking state machine.
