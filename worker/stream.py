"""Reads a live camera on its own thread and always offers the newest frame.

Why a thread: a camera delivers 25 frames a second whether or not anyone is
ready for them. If the detector takes them one by one and is even slightly
slower than the camera, unread frames pile up and the picture being analysed
falls further and further behind real life. Here the reader takes every frame
off the camera immediately and keeps only the latest, so the detector always
works on "now" and old frames are simply dropped.

The reader also reconnects by itself when the camera or network drops.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np


@dataclass(frozen=True)
class Frame:
    image: np.ndarray
    number: int  # counts up from 1; lets a caller tell whether it is new
    captured_at: float  # time.monotonic() when it came off the camera


def parse_source(text: str) -> str | int:
    """'0' means the first webcam; anything else is a URL or file path."""
    return int(text) if text.isdigit() else text


class FrameReader:
    def __init__(
        self,
        source: str | int,
        reconnect_delay: float = 2.0,
        open_capture: Callable = cv2.VideoCapture,
        pace_file: bool = True,
    ):
        """
        source          RTSP/HTTP URL, webcam index, or a video file.
        reconnect_delay seconds to wait before reopening a failed source.
        open_capture    replaced in tests with a fake camera.
        pace_file       play a video file at its own speed instead of as fast
                        as the disk allows, so it behaves like a camera.
        """
        self.source = source
        self.reconnect_delay = reconnect_delay
        self._open_capture = open_capture
        self._is_file = isinstance(source, str) and "://" not in source
        self._pace = pace_file and self._is_file

        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._count = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

        self.connected = False
        self.reconnects = 0
        self.ended = False  # a video file reached its end

    def start(self) -> "FrameReader":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def latest(self) -> Frame | None:
        """The newest frame, or None before the first one arrives."""
        with self._lock:
            return self._latest

    # ---------------------------------------------------------------- internal

    def _run(self) -> None:
        first_attempt = True
        while not self._stop.is_set():
            if not first_attempt:
                self.reconnects += 1
                if self._stop.wait(self.reconnect_delay):
                    break
            first_attempt = False

            capture = self._open_capture(self.source)
            try:
                if not capture.isOpened():
                    continue
                self.connected = True
                self._read_until_failure(capture)
            finally:
                self.connected = False
                capture.release()

            if self._is_file:
                self.ended = True  # a file ending is not a fault to retry
                break

    def _read_until_failure(self, capture) -> None:
        interval = 0.0
        if self._pace:
            fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
            interval = 1.0 / fps
        next_due = time.monotonic()

        while not self._stop.is_set():
            ok, image = capture.read()
            if not ok or image is None:
                return
            with self._lock:
                self._count += 1
                self._latest = Frame(image, self._count, time.monotonic())
            if interval:
                next_due += interval
                delay = next_due - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
