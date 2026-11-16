# RahSaaf

Real-time illegal parking detection and alert system, built for Peshawar roads.

RahSaaf watches a road camera and finds vehicles parked too long in a marked
no-parking zone. For each one it:

- saves a photo and a short clip as evidence,
- reads the number plate when it is clear enough,
- scores how much traffic the vehicle is holding up,
- sends an alert to Telegram with the photo and a map link,
- puts the alert in a dashboard where an officer confirms or rejects it.

It runs on an ordinary computer with no GPU. The system prepares evidence; an
officer makes every decision.

What has and has not been measured is in [docs/REPORT.md](docs/REPORT.md).
A script for showing it to people is in [docs/DEMO.md](docs/DEMO.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/), Node.js 20 or newer, and FFmpeg.
Python and everything else is installed for you; no GPU is required.

**Run every command in this file from the project folder** (the one holding
this README).

1. Install:

   ```bash
   uv sync
   ```

   ```bash
   npm --prefix dashboard install
   ```

   ```bash
   npm --prefix dashboard run build
   ```

2. Create your dashboard login (it asks for a password of 10 or more characters):

   ```bash
   uv run python tools/create_officer.py --name "Your Name" --username yourname
   ```

3. Mark the no-parking area on a video of your road. A window opens: left
   click adds a corner, right click removes one, Enter saves.

   ```bash
   uv run python tools/draw_zone.py my_road.mp4 --out zones.json --name "Hospital gate"
   ```

4. Start everything, using the video as if it were a camera:

   ```bash
   tools/demo.sh my_road.mp4 zones.json
   ```

5. Open `http://127.0.0.1:8000` and log in. A vehicle that stands in the zone
   for 20 seconds appears in the list.

The rest of this file explains each part and how to run it by hand.

## Recorded video

1. Mark the no-parking area on your video:

   ```bash
   uv run python tools/draw_zone.py my_road.mp4 --out zones.json --name "Hospital gate"
   ```

   Left click adds a corner, right click removes one, Enter saves.

2. Run the detector:

   ```bash
   uv run python -m worker.run_video my_road.mp4 --zones zones.json --grace 20
   ```

   `--grace` is how many seconds a vehicle may stand before it counts. Leave it
   out to use the value saved with each zone (120 seconds by default).

3. Look in `data/run/` for `annotated.mp4`, `violations.json` and one photo per
   violation.

## Live camera

1. Convert the model once to OpenVINO, which is faster on Intel CPUs:

   ```bash
   uv run python tools/export_openvino.py models/yolo11n.pt
   ```

2. Run on a stream. The source is an RTSP or HTTP address, a webcam number
   (`0` is the first webcam), or a video file played at its own speed:

   ```bash
   uv run python -m worker.run_live rtsp://CAMERA_ADDRESS --zones zones.json --show
   ```

   To use a phone as the camera, install an "IP Webcam" style app, put the
   phone and laptop on the same Wi-Fi, and use the address the app shows.

3. Each violation is saved in `data/live/` as a photo, a short clip that starts
   a few seconds before the alert, and a line in `violations.jsonl`.

The runner prints its speed and the worst delay every 10 seconds. If the camera
or network drops it keeps retrying by itself.

To measure model speed on your machine:

```bash
uv run python tools/benchmark.py my_road.mp4 models/yolo11n.pt models/yolo11n_openvino_model --imgsz 256 416
```

## Phone alerts

### One-time Telegram setup

1. Copy the settings file:

   ```bash
   cp .env.example .env
   ```

2. In Telegram, open a chat with **@BotFather**, send `/newbot`, follow the
   questions, and copy the token it gives you into `.env` as
   `TELEGRAM_BOT_TOKEN`. Treat the token like a password.
3. Open your new bot in Telegram and press **Start**. For a team, add the bot
   to a group and send any message there.
4. Find the chat ID and put it in `.env` as `TELEGRAM_CHAT_ID`:

   ```bash
   uv run python tools/telegram_setup.py
   ```

5. Send a test message:

   ```bash
   uv run python tools/telegram_setup.py --test
   ```

### Run with alerts

Two terminals. First the server:

```bash
uv run uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Then the camera worker, with the camera's name and position (right-click a
spot in Google Maps to copy its latitude and longitude):

```bash
uv run python -m worker.run_live rtsp://CAMERA_ADDRESS --zones zones.json --api http://127.0.0.1:8000 --camera "Hospital gate" --lat 34.0151 --lon 71.5249
```

Each violation is stored in `data/rahsaaf.db`, its photo and clip go to
`data/evidence/`, and the alert shows the photo, vehicle type, place, time
parked and a Google Maps link, followed by a map pin.

- Stored violations are shown in the dashboard (next section).
- `http://127.0.0.1:8000/docs` shows every server route.
- If the server is down, the worker keeps detecting and retries its reports.
- If Telegram fails, the alert is retried three times and the outcome is
  recorded with the violation.

## Officer dashboard

1. Build the dashboard once (and again after changing anything in
   `dashboard/`). Needs Node.js:

   ```bash
   npm --prefix dashboard install
   ```

   ```bash
   npm --prefix dashboard run build
   ```

2. Create a login. You are asked to type a password of at least 10 characters:

   ```bash
   uv run python tools/create_officer.py --name "Ali Khan" --username ali
   ```

3. Start the server and open `http://127.0.0.1:8000`:

   ```bash
   uv run uvicorn api.main:app --host 127.0.0.1 --port 8000
   ```

What officers can do:

- See alerts arrive by themselves in the **Pending** tab.
- Open an alert to see the photo, the clip, the place and a map link.
- **Confirm** it, **reject** it with a reason, mark **action taken**, or
  **reopen** it.

Every decision is recorded with the officer's name and the time. The history
cannot be edited or deleted, even directly in the database.

Other login commands:

```bash
uv run python tools/create_officer.py --list
```

```bash
uv run python tools/create_officer.py --username ali --reset-password
```

Started this way, the server listens only on this computer.

### What the dashboard offers

- **Alerts:** summary tiles, tabs by status, search by plate, code, camera or
  zone, and a filter by traffic impact. New alerts arrive by themselves, with
  a pop-up and a count in the browser tab.
- **Light and dark mode:** follows the device until changed with the button
  in the side bar, then remembers the choice.
- **Phones:** the layout rearranges itself for a narrow screen.
- It loads nothing from the internet except the map tiles on the Analytics
  page.

### Managing logins from the dashboard

Create the first admin once from the terminal:

```bash
uv run python tools/create_officer.py --name "Your Name" --username yourname --role admin
```

After that, the **Account** page does the rest. Every officer can change
their own password there. An admin can also add logins, reset a password,
and disable or re-enable a login. A disabled login, or one whose password was
changed, is logged out everywhere at once. Logins are never deleted, and each
change is recorded with who made it.

### Using the dashboard from a phone or another computer

```bash
uv run python tools/serve.py --lan
```

This serves the dashboard to devices on the same Wi-Fi or office network over
HTTPS. A certificate is made once in `data/tls/`, the login cookie is only
sent over HTTPS, and links in alerts point at this computer's network address.
The certificate is self-signed, so each browser warns once; compare the
fingerprint it shows with the one printed in the terminal before accepting.

The camera worker then needs the HTTPS address and the certificate:

```bash
uv run python -m worker.run_live SOURCE --zones zones.json --api https://127.0.0.1:8000 --ca data/tls/cert.pem
```

This is for a local network. Do not put it on the open internet as it is; use
a real certificate and a proper web server in front for that.

## Number plates

When a violation is confirmed, the worker reads the vehicle's plate from the
next few frames. It is on by default; add `--no-plates` to turn it off.

- **Several reads must agree.** One read is never trusted. The plate is
  accepted only when at least two frames give the same text, the text has the
  shape of a Pakistani plate, and the reader was confident.
- **Otherwise it says "not readable".** The alert still carries the photo. A
  wrong plate would point at an innocent person's vehicle, so the system
  prefers to give none.
- **The alert waits about a second** for the plate, three at most.
- **Officers can correct it** in the dashboard, or enter one the system could
  not read. Every correction is recorded in the history.

The reader uses open-source models trained on plates from many countries, not
on Pakistani plates specifically. Measure it on your own pictures before
relying on it: put pictures in a folder with a `truth.csv` listing each file
and its true plate (`car_001.jpg,LEA1234`), then run:

```bash
uv run python tools/evaluate_plates.py data/plates
```

It reports how many plates were read correctly, read wrongly, and declined,
and writes `docs/PLATE_REPORT.md`.

**Result on real Pakistani plates:** on 256 public photos of cars, 87% are
read correctly, 1% wrongly and 12% are declined. Before a fix for the small
year badge on Punjab plates it was 53%, 10% and 37%. The fix was tuned on
these same photos, which are also easier than camera footage, so expect less
on a real camera. Treat a plate reading as a suggestion for the officer to
check, never as proof. See [docs/PLATE_REPORT.md](docs/PLATE_REPORT.md).

## Traffic impact

Two cars can both be parked illegally while only one is causing a jam. Mark
the driving lane beside a zone and each violation gets an impact level, so the
worst one can be dealt with first:

```bash
uv run python tools/draw_zone.py my_road.mp4 --out zones.json --lane zone1
```

Draw the lane over the road traffic uses, for a good distance before the zone.
Three things are then measured:

| Part | Weight | Meaning |
|---|---|---|
| Flow drop | 50% | Vehicles getting through per minute, against what is normal for this road |
| Queue | 30% | Vehicles standing still in the lane (5 counts as full) |
| Lane blocked | 20% | How much of the parked vehicle is in the driving lane |

The result is Low, Medium or High. It appears in the alert, sorts the waiting
list in the dashboard (worst first), and only ever goes up: the stored value
is the worst the vehicle caused.

- "Normal flow" is learned from at least two minutes of clear road, so a
  violation that starts right after the worker does has no flow figure yet.
- The weights are a first guess and have not been tuned on real traffic.
- A zone with no lane drawn simply has no impact level.

## False alarms from fixed things

A booth, kiosk or sign can be mistaken for a vehicle, and because it never
moves it would be reported as parked. Draw around it once and the system
skips any box that lies mostly inside that area:

```bash
uv run python tools/draw_zone.py my_road.mp4 --out zones.json --ignore "Ticket booth"
```

The area is saved in the zones file under `"ignore"` and shown as a thin grey
outline on the evidence photo. A real vehicle parked in front of the booth
only partly overlaps it, so it is still reported. Keep the area tight around
the object: a vehicle that sits almost entirely inside it will be missed.

### Letting officers' decisions find these spots

You do not have to spot the booth yourself. Each alert records where in the
picture the vehicle's box was. When officers reject alerts at one spot as
"Not a vehicle" two or more times, this lists the spot:

```bash
uv run python tools/learn_ignore.py zones.json --camera "Hospital gate"
```

Nothing changes until you add `--apply`, which writes the spot into the zones
file as an ignore area. Restart the camera worker afterwards. A person runs
this on purpose, so one wrong click in the dashboard cannot hide a piece of
road from the camera. Alerts recorded before this feature have no box and are
not counted.

## Analytics

The dashboard's **Analytics** page covers the last 7, 30 or 90 days:

- **Hotspots:** a map of cameras sized by number of violations, with each
  camera's busiest hour. The map needs internet for its street tiles; the
  table beside it does not.
- **By hour and by day:** when wrong parking happens.
- **Repeat offenders:** plates caught more than once. A plate read
  automatically can be a misread, so this is a prompt to check, not proof.
- **Why alerts were rejected:** where the system gets it wrong.

Alerts an officer rejected are not counted as violations.

## Rickshaws, vans and loaders

The stock model knows cars, motorcycles, buses and trucks. A second model,
trained on this laptop from a public dataset, also knows auto rickshaws, vans
and pickup loaders. It is not downloaded with the project; build it once
(a 4.55 GB download and about 2.5 hours of training, no GPU needed):

```bash
uv run python tools/prepare_heterotraffic.py data/heterotraffic/extracted
```

```bash
uv run python tools/train_local.py data/dataset_hetero/split/dataset.yaml --name hetero
```

```bash
cp data/train_runs/hetero/weights/best.pt models/local.pt
```

```bash
uv run python tools/export_openvino.py models/local.pt
```

Then add `--weights models/local_openvino_model` to `worker/run_live.py` or
`tools/demo.sh`. The stock model stays the default.

The model in `models/local.pt` went one step further: 20 more rounds on a
larger set of 4,771 pictures, started from the first result:

```bash
uv run python tools/prepare_heterotraffic.py data/heterotraffic/extracted --out data/dataset_hetero_big --images 6000 --rickshaw-share 0.45
```

```bash
uv run python tools/train_local.py data/dataset_hetero_big/split/dataset.yaml --name hetero_big --epochs 20 --start models/local.pt
```

If the laptop sleeps or shuts down part-way, the same command with `--resume`
in place of `--epochs` and `--start` carries on from the last finished round.

Measured on 594 held-out pictures ([docs/MODEL_REPORT.md](docs/MODEL_REPORT.md)):
car mAP@50 0.84, rickshaw 0.82, bus 0.82, truck 0.71, motorcycle 0.68,
pickup loader 0.57, van 0.55; overall 0.71. Read these with care:

- The pictures are from Bangladesh, taken at street level. Peshawar rickshaws
  look different and a parking camera looks down from above, so expect lower
  accuracy on real footage.
- The test pictures resemble the training ones, so the figures are optimistic.
- **Qingqis are not detected.** No public pictures of them were found. The
  class exists and is empty; it needs about 200 or more of your own labelled
  pictures.
- Vans and pickup loaders are the weakest classes (few training examples).
- On an overhead parking clip it mistook a booth for a pickup loader. Marking the
  booth as an ignore area removed that alert (see "False alarms from fixed
  things").

Training data: HeteroTraffic by Sagar and Koli, Mendeley Data,
DOI 10.17632/tvkfk56s2k.2, licensed CC BY 4.0.

To train on your own Peshawar footage instead, which is what will make it
accurate, follow [docs/TRAINING.md](docs/TRAINING.md).

## Measuring accuracy

Nothing here should be trusted on a claim. Each part has a tool that measures
it on your own material and writes a report into `docs/`:

| What | Tool | You provide |
|---|---|---|
| Violation detection | `tools/evaluate_violations.py` | Clips, with each real violation's start and end marked |
| Vehicle model | `tools/evaluate.py` | The labelled test pictures from training |
| Plate reading | `tools/evaluate_plates.py` | Pictures with each true plate listed |
| Speed on this machine | `tools/benchmark.py` | Any video |

Run any of them with `--help` for the exact input format.

### First result on real street footage

On 17 minutes of public fixed-camera street video (Street Scene dataset) with
three real violations, the local model caught 2, missed 1 and raised no false
alarms; the stock model caught none and raised 2 false alarms. Three
violations is too few to call a precision or recall figure, and the street is
not in Peshawar. Details, limits and the commands to repeat it are in
[docs/VIOLATION_REPORT.md](docs/VIOLATION_REPORT.md).

A later training run scored higher on test pictures (0.745 against 0.714) but
did worse on this footage, so it was not adopted. Judge any new model on
fixed-camera video, not on its picture score alone.

## How it decides

- A vehicle is tested by the bottom-centre of its box, where the wheels meet
  the road, not by the centre of the box.
- A vehicle that stays in the same place is timed. When the grace period runs
  out, one violation is raised.
- A passing bus hiding the vehicle for a few seconds does not reset the timer.
- A vehicle must be detected at 0.3 confidence or better to be followed at
  all. Once followed, detections down to 0.15 keep it followed, so a vehicle
  the model is only fairly sure about does not keep restarting its timer.
- If the tracker gives a parked vehicle a new ID, the timer carries over.

The rules live in [worker/parking_state.py](worker/parking_state.py) and are
covered by tests that need no video or model:

```bash
uv run pytest
```

## Known limits

- The default stock model knows cars, motorcycles, buses and trucks only.
  The optional local model adds rickshaws, vans and loaders, trained on
  pictures from Bangladesh. Neither detects Qingqis.
- A traffic jam inside a no-parking zone will be flagged as parking.
- Small, distant or blurred vehicles are often missed by the stock model.
- Plate reading has only been measured on close, sharp photos, and its
  two-line rule was tuned on those same photos.
- If a live stream is down for more than 5 seconds, parking timers restart.
- HTTPS on a local network uses a self-signed certificate, which every
  browser warns about once. It is not set up for the open internet.
- Plate reading has not been measured on real Pakistani plates. Distant,
  dirty, angled or non-standard plates will mostly come back "not readable".

## Licence note

Ultralytics YOLO is AGPL-3.0. Check what that means for you before
distributing this project.
# Rahsaaf
