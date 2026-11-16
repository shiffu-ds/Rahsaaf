# Training the local vehicle model (Phase 3)

The stock model only knows cars, motorcycles, buses and trucks. This guide
produces a model that also knows rickshaws, Qingqis, vans and loaders, trained
on your own Peshawar footage.

**A first version already exists without any labelling.** It was trained on
this laptop from the public HeteroTraffic dataset and knows rickshaws, vans
and loaders, but not Qingqis, and its pictures are from Bangladesh. See
"Rickshaws, vans and loaders" in the README. This guide is how to do better
with Peshawar footage, and the only way to add Qingqis.

No free GPU to hand? `tools/train_local.py` trains on the laptop itself in a
few hours instead of the Colab step below.

The tools are ready. What is missing is the footage and the labelling, which
only you can do. Expect about 10–15 hours in total, most of it labelling.

## Overview

```
record ─► extract frames ─► pre-label ─► correct labels ─► split ─► train (Colab) ─► evaluate ─► use
 you        1 command        1 command     you, by hand    1 command   notebook       1 command
```

## 1. Record footage

- **Where:** at least 5 different places with wrong parking: a bazaar road, a
  hospital gate, a university road, a bus stand, a plaza front.
- **How:** from a window, rooftop or overhead bridge, phone held still or
  resting on a ledge, landscape.
- **How long:** 10–15 minutes per place.
- **When:** mix morning, afternoon and evening. Add one clip at dusk.
- Copy the videos into `data/footage/`.

Five or more separate videos matter: the test must use videos the model never
saw in training, or the accuracy number means little.

## 2. Extract frames

```bash
uv run python tools/extract_frames.py data/footage/*.mp4 --every 2
```

Pictures land in `data/dataset/images/`. Aim for 1,500–3,000. Too few: lower
`--every` to 1. Frames that look the same as the previous one are skipped; if
too many are skipped, add `--min-change 0`.

## 3. Pre-label

```bash
uv run python tools/prelabel.py
```

This draws first-guess boxes with the stock model into
`data/dataset/labels/`, so you correct boxes instead of drawing each one.

## 4. Correct the labels (the real work)

Use a labelling tool that reads YOLO-format labels. Two free options:

- **CVAT** (cvat.ai): create a task, upload the pictures, then upload the
  labels as "YOLO 1.1" annotations.
- **Roboflow** (roboflow.com): easiest for beginners. Note that projects on its
  free plan are public.

Create the classes **in exactly this order** (it is also in
`data/dataset/labels/classes.txt`):

| No. | Class | What it covers |
|---|---|---|
| 0 | car | Cars, jeeps, SUVs |
| 1 | motorcycle | Motorbikes, with or without rider |
| 2 | rickshaw | Three-wheeled auto rickshaw |
| 3 | qingqi | Motorcycle rickshaw with a passenger carriage |
| 4 | van | Hiace, Suzuki Bolan and similar |
| 5 | bus | Buses and coasters |
| 6 | truck | Large trucks |
| 7 | pickup_loader | Suzuki pickup, Shehzore and other small loaders |

For every picture:

1. Fix boxes that are loose or cut the vehicle; delete boxes on things that are
   not vehicles.
2. Change the class where the guess is wrong. Rickshaws usually come out as
   `car` or `motorcycle`, loaders as `truck`.
3. Add every vehicle that was missed, including partly hidden ones if at least
   half is visible.

Rules that keep the model honest:

- Label **every** vehicle in a picture. An unlabelled vehicle teaches the model
  that it is background.
- Draw the box tight around the whole vehicle, wheels included.
- Skip vehicles too small or blurred to name; do not guess.
- Aim for at least 200 boxes of each class. Rare classes need extra pictures.

When finished, export in **YOLO** format and put the `.txt` files back in
`data/dataset/labels/`, replacing the guesses.

## 5. Split

```bash
uv run python -m training.split_dataset
```

Makes `data/dataset/split/` with 70% training, 20% validation and 10% test
pictures, split by video. Then zip it:

```bash
cd data/dataset && zip -qr split.zip split
```

## 6. Train on a free GPU

This laptop has no GPU and would take days. Use Google Colab instead:

1. Open colab.research.google.com and sign in.
2. File → Upload notebook → choose `training/train_colab.ipynb`.
3. Runtime → Change runtime type → T4 GPU.
4. Run the cells top to bottom; upload `split.zip` when asked.
5. At the end it downloads `rahsaaf_model.zip`.

Roughly 30–60 minutes for 2,000 pictures.

## 7. Evaluate and use

Unzip `rahsaaf_model.zip` into `models/`, then:

```bash
mv models/best.pt models/local.pt
```

```bash
mv models/best_openvino_model models/local_openvino_model
```

```bash
uv run python tools/evaluate.py models/local.pt
```

This prints accuracy per class and writes `docs/MODEL_REPORT.md`, the table
for your project report. The target is an overall mAP@50 of 0.80 or higher.

Run the live detector with the new model:

```bash
uv run python -m worker.run_live SOURCE --zones zones.json --weights models/local_openvino_model
```

## If accuracy is low

| Symptom | Likely cause | Fix |
|---|---|---|
| One class scores far below the rest | Too few examples | Record more footage containing it |
| Rickshaws and Qingqis confused | Inconsistent labelling | Re-check those labels against the table above |
| Good on test, poor on a new road | All footage from similar places | Add different locations and times |
| Misses distant vehicles | They are too small | Mount the camera closer, or train at `imgsz=960` |
