import cv2
import numpy as np

from worker.evidence import ClipRecorder


def frame(value):
    return np.full((48, 64, 3), value, np.uint8)


def frame_count(path):
    capture = cv2.VideoCapture(str(path))
    count = 0
    while capture.read()[0]:
        count += 1
    capture.release()
    return count


def test_clip_includes_frames_from_before_and_after(tmp_path):
    recorder = ClipRecorder(before_seconds=2.0, after_seconds=1.0)
    finished = []
    for i in range(50):  # 10 seconds at 5 frames a second
        t = i / 5
        if t == 6.0:
            recorder.start_clip(t, tmp_path / "v.mp4")
        finished += recorder.add(t, frame(i))

    assert finished == [tmp_path / "v.mp4"]
    # 2 s before (t=3.8 .. 5.8, 11 frames) + t=6.0 .. 7.0 (6 frames). The
    # frame exactly 2 s old may fall either side of the cut-off.
    assert frame_count(tmp_path / "v.mp4") in (16, 17)


def test_old_frames_are_dropped_from_memory():
    recorder = ClipRecorder(before_seconds=2.0)
    for i in range(500):
        recorder.add(i / 5, frame(0))
    assert len(recorder._recent) in (10, 11)  # about 2 s at 5 frames a second


def test_close_writes_clips_still_recording(tmp_path):
    recorder = ClipRecorder(before_seconds=1.0, after_seconds=60.0)
    for i in range(10):
        recorder.add(i / 5, frame(i))
    recorder.start_clip(1.8, tmp_path / "v.mp4")
    recorder.add(2.0, frame(0))
    assert not (tmp_path / "v.mp4").exists()

    assert recorder.close() == [tmp_path / "v.mp4"]
    assert frame_count(tmp_path / "v.mp4") > 0
    assert recorder.close() == []


def test_two_overlapping_clips(tmp_path):
    recorder = ClipRecorder(before_seconds=1.0, after_seconds=1.0)
    finished = []
    for i in range(30):
        t = i / 5
        if t == 2.0:
            recorder.start_clip(t, tmp_path / "a.mp4")
        if t == 2.4:
            recorder.start_clip(t, tmp_path / "b.mp4")
        finished += recorder.add(t, frame(i))
    assert sorted(p.name for p in finished) == ["a.mp4", "b.mp4"]
