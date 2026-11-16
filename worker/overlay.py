"""Drawing zones, vehicle boxes and parking timers onto a frame."""
from __future__ import annotations

import cv2
import numpy as np

from worker.parking_state import Observation, State, VehicleStatus
from worker.zones import Zone

# Colours are BGR, as OpenCV expects.
_ZONE = (0, 200, 255)
_LANE = (235, 160, 60)
_PLAIN = (160, 160, 160)
_STATE_COLOUR = {
    State.MOVING: (0, 200, 0),
    State.STOPPED: (0, 165, 255),
    State.VIOLATION: (0, 0, 255),
}


def draw_zones(frame: np.ndarray, zones: list[Zone], ignore=()) -> None:
    height, width = frame.shape[:2]
    for area in ignore:
        # Thin grey outline: shows the operator what is being skipped.
        outline = np.array([(round(x * width), round(y * height)) for x, y in area.polygon], np.int32)
        cv2.polylines(frame, [outline], True, (150, 150, 150), 1, cv2.LINE_AA)
    tint = frame.copy()
    for zone in zones:
        points = np.array(zone.pixel_polygon(width, height), np.int32)
        cv2.fillPoly(tint, [points], _ZONE)
        cv2.polylines(frame, [points], True, _ZONE, 2, cv2.LINE_AA)
        x, y = points.min(axis=0)
        _label(frame, f"NO PARKING: {zone.name}", int(x) + 4, int(y) + 18, _ZONE)
    cv2.addWeighted(tint, 0.15, frame, 0.85, 0, dst=frame)
    for zone in zones:
        if zone.lane:
            lane = np.array([(round(x * width), round(y * height)) for x, y in zone.lane], np.int32)
            cv2.polylines(frame, [lane], True, _LANE, 1, cv2.LINE_AA)


def draw_vehicles(
    frame: np.ndarray,
    observations: list[Observation],
    statuses: list[VehicleStatus],
) -> None:
    watched = {s.track_id: s for s in statuses}

    for obs in observations:
        if obs.track_id in watched:
            continue
        x1, y1, x2, y2 = (int(v) for v in obs.box)
        cv2.rectangle(frame, (x1, y1), (x2, y2), _PLAIN, 1)

    for status in statuses:
        if not status.visible and status.state is State.MOVING:
            continue  # drove off; nothing to show
        colour = _STATE_COLOUR[status.state]
        x1, y1, x2, y2 = (int(v) for v in status.box)
        thickness = 3 if status.state is State.VIOLATION else 2
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, thickness)
        if status.state is State.VIOLATION:
            text = f"ILLEGAL PARKING {_clock(status.parked_seconds)}"
        elif status.state is State.STOPPED:
            text = f"stopped {_clock(status.parked_seconds)} / {_clock(status.grace_seconds)}"
        else:
            text = f"#{status.track_id}"
        if not status.visible:
            text += " (hidden)"
        _label(frame, text, x1, max(y1 - 6, 14), colour)


def _clock(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def _label(frame: np.ndarray, text: str, x: int, y: int, colour) -> None:
    font, scale = cv2.FONT_HERSHEY_SIMPLEX, 0.5
    (w, h), _ = cv2.getTextSize(text, font, scale, 1)
    cv2.rectangle(frame, (x - 2, y - h - 4), (x + w + 2, y + 3), (0, 0, 0), -1)
    cv2.putText(frame, text, (x, y), font, scale, colour, 1, cv2.LINE_AA)
