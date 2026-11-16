# Demo script

A ten-minute walk-through for showing RahSaaf to a teacher, a panel or a
traffic officer. It works with a recorded video, so nothing depends on a
camera or the venue's Wi-Fi.

## The day before

1. Pick a video where a vehicle clearly stops in a place it should not, and
   other vehicles drive past. One or two minutes is enough.
2. Draw the zone, and the driving lane beside it:

   ```bash
   uv run python tools/draw_zone.py demo.mp4 --out demo_zones.json --name "Hospital gate"
   ```

   ```bash
   uv run python tools/draw_zone.py demo.mp4 --out demo_zones.json --lane zone1
   ```

3. Create a login and run the whole thing once, start to finish:

   ```bash
   tools/demo.sh demo.mp4 demo_zones.json --show --lat 34.0151 --lon 71.5249
   ```

4. Check that the alert reaches your phone. If Telegram is not set up, the
   dashboard still works; skip step 5 below.
5. **Record your screen during this rehearsal.** If anything fails on the day,
   play the recording and talk over it.

## On the day

Start it before people are watching; the first alert takes about 20 seconds.

```bash
tools/demo.sh demo.mp4 demo_zones.json --show --lat 34.0151 --lon 71.5249
```

| Step | Show | Say |
|---|---|---|
| 1 | The live preview window, with the yellow zone | "This is a no-parking area marked on the camera's view. Vehicles driving through are ignored." |
| 2 | A vehicle stops; an orange timer counts up | "It is timing how long this vehicle has stood still. Stopping to drop someone off is allowed." |
| 3 | The box turns red: ILLEGAL PARKING | "After the allowed time, it becomes a violation. One alert is raised, however long it stays." |
| 4 | The dashboard: the alert appears by itself | "The officer sees it at once, with no refresh. The list puts whatever is blocking traffic most at the top." |
| 5 | Your phone: the Telegram alert | "The same alert reaches the officer's phone with the photo, the plate, and a map link to the spot." |
| 6 | Open the alert: photo, clip, plate | "The clip starts before the alert, so the officer sees the vehicle arrive. The plate was read from several frames; if they disagree, it says 'not readable' rather than guess." |
| 7 | Traffic impact panel | "This is how much the vehicle is holding up traffic: how far it sticks into the lane, the queue behind it, and the drop in flow." |
| 8 | Click Confirm, add a note; show History | "The officer decides, not the software. Every decision is recorded with a name and time, and cannot be edited or deleted." |
| 9 | Reject another alert, choosing a reason | "Rejections need a reason. That list is how we learn where the system is wrong." |
| 10 | The Analytics page | "Over time this shows where and when wrong parking happens, and which plates keep coming back." |

## Questions you will be asked

**How accurate is it?**
Say what you measured, with the numbers from `docs/`. Where you have not
measured, say so. "I have not tested that yet" is a stronger answer than a
number you cannot back up.

**Does it issue fines?**
No. It has no access to vehicle ownership records and is not meant to. It
gives an officer evidence; the officer acts.

**What if it reads a plate wrong?**
It needs several frames to agree and otherwise reports "not readable". The
officer sees a close-up of the plate beside the text and can correct it; the
correction is logged.

**What about a traffic jam?**
A jam inside a marked zone can be flagged as parking. This is a known limit,
and the officer can reject it with the reason "not parked".

**Why not use the Safe City cameras?**
This is for places they do not cover: bazaars, hospital gates, campuses,
private plazas. It runs on an ordinary computer with a cheap camera.

**What does it cost to run?**
One computer without a GPU and one camera. All the software is free.

## If something goes wrong

| Problem | What to do |
|---|---|
| Preview window does not open | Run without `--show`; use the dashboard instead |
| No alert on the phone | Carry on with the dashboard; mention the alert and show a screenshot |
| Nothing is detected | Play the recording from your rehearsal |
| Dashboard will not load | Check the terminal for the address; the server must still be running |
