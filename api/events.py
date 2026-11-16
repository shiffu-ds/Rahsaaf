"""Live updates for open dashboards.

The server keeps a short list of recent events (new violation, status change).
Each dashboard holds one long-lived connection and is sent whatever was added
since it last looked. Missing an event is harmless: the dashboard reloads its
list when it reconnects.
"""
from __future__ import annotations

import threading
from collections import deque


class EventLog:
    def __init__(self, keep: int = 200):
        self._lock = threading.Lock()
        self._events: deque[tuple[int, str, dict]] = deque(maxlen=keep)
        self._last = 0

    def publish(self, kind: str, data: dict) -> int:
        with self._lock:
            self._last += 1
            self._events.append((self._last, kind, data))
            return self._last

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._last

    def since(self, event_id: int) -> list[tuple[int, str, dict]]:
        with self._lock:
            return [event for event in self._events if event[0] > event_id]
