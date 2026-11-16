"""The frame reader, tested against a fake camera (no real device or network)."""
import time

import numpy as np

from worker.stream import FrameReader, parse_source


class FakeCamera:
    """Delivers ``frames`` frames 5 ms apart, then fails like a dropped stream."""

    def __init__(self, frames, opens=True):
        self.remaining = frames
        self.opens = opens
        self.released = False

    def isOpened(self):
        return self.opens

    def read(self):
        if self.remaining <= 0:
            return False, None
        self.remaining -= 1
        time.sleep(0.005)
        return True, np.zeros((4, 4, 3), np.uint8)

    def get(self, _prop):
        return 0.0

    def release(self):
        self.released = True


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_parse_source():
    assert parse_source("0") == 0
    assert parse_source("rtsp://camera/stream") == "rtsp://camera/stream"
    assert parse_source("road.mp4") == "road.mp4"


def test_no_frame_before_the_camera_delivers_one():
    reader = FrameReader("rtsp://x", open_capture=lambda _: FakeCamera(0, opens=False))
    assert reader.latest() is None


def test_reader_keeps_only_the_newest_frame():
    camera = FakeCamera(50)
    reader = FrameReader("rtsp://x", open_capture=lambda _: camera).start()
    try:
        assert wait_for(lambda: reader.latest() is not None and reader.latest().number >= 20)
        first = reader.latest()
        assert wait_for(lambda: reader.latest().number > first.number)
        assert reader.latest().captured_at >= first.captured_at
    finally:
        reader.stop()


def test_reader_reconnects_after_the_stream_drops():
    cameras = []

    def open_capture(_):
        cameras.append(FakeCamera(5))
        return cameras[-1]

    reader = FrameReader("rtsp://x", reconnect_delay=0.02, open_capture=open_capture).start()
    try:
        assert wait_for(lambda: len(cameras) >= 3)
        assert reader.reconnects >= 2
        assert cameras[0].released  # the dead connection was closed
        # Frame numbers keep counting across reconnects, so a caller never
        # mistakes a frame from the new connection for one it has seen.
        assert wait_for(lambda: reader.latest().number > 5)
    finally:
        reader.stop()


def test_reader_keeps_retrying_a_camera_that_will_not_open():
    attempts = []

    def open_capture(_):
        attempts.append(1)
        return FakeCamera(10, opens=len(attempts) >= 3)

    reader = FrameReader("rtsp://x", reconnect_delay=0.02, open_capture=open_capture).start()
    try:
        assert wait_for(lambda: reader.latest() is not None)
        assert len(attempts) >= 3
    finally:
        reader.stop()


def test_video_file_ends_instead_of_reconnecting():
    opened = []

    def open_capture(_):
        opened.append(1)
        return FakeCamera(5)

    reader = FrameReader("road.mp4", open_capture=open_capture, pace_file=False).start()
    try:
        assert wait_for(lambda: reader.ended)
        assert len(opened) == 1
        assert reader.latest().number == 5
    finally:
        reader.stop()


def test_stop_ends_the_thread_promptly():
    reader = FrameReader("rtsp://x", open_capture=lambda _: FakeCamera(10_000)).start()
    assert wait_for(lambda: reader.latest() is not None)
    started = time.monotonic()
    reader.stop()
    assert time.monotonic() - started < 1.0
    assert not reader._thread.is_alive()
