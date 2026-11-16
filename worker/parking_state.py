"""Decides when a tracked vehicle has been parked in a no-parking zone too long.

This module knows nothing about video or models. It receives, for each
processed frame, the time and a list of tracked vehicle boxes, and returns
violation events. That keeps the rules testable in milliseconds with made-up
tracks.

How "parked" is decided
-----------------------
Each vehicle standing in a zone gets an *anchor*: the box where it was first
seen (or last came to rest) and the time that happened. On every later frame
the current box is compared with the anchor:

* It still overlaps the anchor strongly -> the vehicle has not moved. The
  parked time is simply ``now - anchor time``.
* It has stopped overlapping for longer than ``move_confirm_seconds`` -> the
  vehicle really moved, so the anchor (and the timer) restarts.

The short confirmation delay matters: when a bus passes in front of a parked
car the detector may briefly return a half-sized box. Without the delay that
single bad box would reset a two-minute timer.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from worker.zones import Box, Zone, ground_point, iou


class State(str, Enum):
    MOVING = "moving"
    STOPPED = "stopped"
    VIOLATION = "violation"


@dataclass(frozen=True)
class Observation:
    """One tracked vehicle in one frame."""
    track_id: int
    box: Box
    vehicle_class: str = "vehicle"
    confidence: float = 1.0


@dataclass(frozen=True)
class ParkingConfig:
    #: Overlap with the anchor box above which a vehicle counts as not moved.
    stationary_iou: float = 0.7
    #: How long the overlap must stay broken before the timer restarts.
    move_confirm_seconds: float = 1.0
    #: How long a vehicle must be still before it is shown as stopped.
    stop_confirm_seconds: float = 2.0
    #: How long a vehicle may go unseen before it is treated as gone.
    occlusion_tolerance_seconds: float = 5.0
    #: Overlap needed for a new track ID to take over a vanished vehicle's timer.
    reid_iou: float = 0.6


@dataclass(frozen=True)
class ViolationEvent:
    kind: str  # "started" or "ended"
    violation_id: int
    track_id: int
    zone_id: str
    vehicle_class: str
    confidence: float
    box: Box
    stopped_at: float  # when the vehicle came to rest
    confirmed_at: float  # when the grace period ran out
    ended_at: float | None = None

    @property
    def duration_seconds(self) -> float | None:
        """Total time parked, from coming to rest until it left."""
        if self.ended_at is None:
            return None
        return self.ended_at - self.stopped_at


@dataclass(frozen=True)
class VehicleStatus:
    """What the overlay needs to draw one vehicle."""
    track_id: int
    zone_id: str
    state: State
    box: Box
    parked_seconds: float
    grace_seconds: float
    #: False when the vehicle was not detected in the latest frame and ``box``
    #: is only where it was last seen.
    visible: bool = True
    #: Set while this vehicle is an open violation.
    violation_id: int | None = None


@dataclass
class _Vehicle:
    track_id: int
    zone: Zone
    anchor_box: Box
    anchor_time: float
    last_box: Box
    last_seen: float
    moved_since: float | None = None
    violation_id: int | None = None
    confirmed_at: float | None = None
    classes: Counter = field(default_factory=Counter)
    confidences: list[float] = field(default_factory=list)

    @property
    def vehicle_class(self) -> str:
        return self.classes.most_common(1)[0][0] if self.classes else "vehicle"

    @property
    def confidence(self) -> float:
        recent = self.confidences[-10:]
        return sum(recent) / len(recent) if recent else 0.0


class ParkingMonitor:
    """Tracks every vehicle standing in a zone and raises violation events."""

    def __init__(self, zones: list[Zone], config: ParkingConfig | None = None):
        self.zones = list(zones)
        self.config = config or ParkingConfig()
        self._vehicles: dict[int, _Vehicle] = {}
        self._next_violation_id = 1

    # ------------------------------------------------------------------ public

    def update(
        self,
        now: float,
        observations: list[Observation],
        frame_width: int,
        frame_height: int,
    ) -> list[ViolationEvent]:
        """Feed one frame's tracked vehicles; get back any violation events."""
        events: list[ViolationEvent] = []
        seen: set[int] = set()
        present = {obs.track_id for obs in observations}

        for obs in observations:
            zone = self._zone_for(obs.box, frame_width, frame_height)
            vehicle = self._vehicles.get(obs.track_id)

            if vehicle is None:
                vehicle = self._adopt_lost_vehicle(obs, present)
            if vehicle is None:
                if zone is None:
                    continue  # not in any zone: nothing to watch
                vehicle = _Vehicle(
                    track_id=obs.track_id,
                    zone=zone,
                    anchor_box=obs.box,
                    anchor_time=now,
                    last_box=obs.box,
                    last_seen=now,
                )
                self._vehicles[obs.track_id] = vehicle

            seen.add(vehicle.track_id)
            vehicle.last_box = obs.box
            vehicle.last_seen = now
            vehicle.classes[obs.vehicle_class] += 1
            vehicle.confidences.append(obs.confidence)

            events.extend(self._advance(vehicle, zone, now))

        events.extend(self._expire_unseen(now, seen))
        return events

    def statuses(self, now: float) -> list[VehicleStatus]:
        """Current state of every watched vehicle, for drawing."""
        return [
            VehicleStatus(
                track_id=v.track_id,
                zone_id=v.zone.id,
                state=self._state(v, now),
                box=v.last_box,
                parked_seconds=max(0.0, now - v.anchor_time),
                grace_seconds=v.zone.grace_seconds,
                visible=v.last_seen >= now,
                violation_id=v.violation_id,
            )
            for v in self._vehicles.values()
        ]

    def flush(self, now: float) -> list[ViolationEvent]:
        """Close every open violation, e.g. when the video ends."""
        events = [
            self._end_event(v, v.last_seen)
            for v in self._vehicles.values()
            if v.violation_id is not None
        ]
        self._vehicles.clear()
        return events

    # ---------------------------------------------------------------- internal

    def _zone_for(self, box: Box, width: int, height: int) -> Zone | None:
        point = ground_point(box, width, height)
        for zone in self.zones:
            if zone.contains(point):
                return zone
        return None

    def _adopt_lost_vehicle(
        self, obs: Observation, present: set[int]
    ) -> _Vehicle | None:
        """Hand a vanished vehicle's timer to a new track ID in the same spot.

        Trackers sometimes drop an ID and issue a new one for the same parked
        vehicle. Without this the timer would restart and the vehicle could sit
        there all day without ever reaching the grace period.
        """
        best: _Vehicle | None = None
        best_overlap = self.config.reid_iou
        for candidate in self._vehicles.values():
            if candidate.track_id in present:
                continue  # that vehicle is still being tracked under its own ID
            overlap = iou(obs.box, candidate.anchor_box)
            if overlap >= best_overlap:
                best, best_overlap = candidate, overlap
        if best is None:
            return None
        del self._vehicles[best.track_id]
        best.track_id = obs.track_id
        self._vehicles[obs.track_id] = best
        return best

    def _advance(
        self, vehicle: _Vehicle, zone: Zone | None, now: float
    ) -> list[ViolationEvent]:
        cfg = self.config
        events: list[ViolationEvent] = []

        if iou(vehicle.last_box, vehicle.anchor_box) >= cfg.stationary_iou:
            vehicle.moved_since = None
        elif vehicle.moved_since is None:
            vehicle.moved_since = now

        moved = (
            vehicle.moved_since is not None
            and now - vehicle.moved_since >= cfg.move_confirm_seconds
        )
        if moved:
            # The vehicle really moved. Whatever it was doing before is over.
            if vehicle.violation_id is not None:
                events.append(self._end_event(vehicle, vehicle.moved_since))
            if zone is None:
                del self._vehicles[vehicle.track_id]
                return events
            vehicle.zone = zone
            vehicle.anchor_box = vehicle.last_box
            vehicle.anchor_time = now
            vehicle.moved_since = None
            vehicle.violation_id = None
            vehicle.confirmed_at = None
            return events

        still = vehicle.moved_since is None
        parked_for = now - vehicle.anchor_time
        if (
            still
            and vehicle.violation_id is None
            and parked_for >= vehicle.zone.grace_seconds
        ):
            vehicle.violation_id = self._next_violation_id
            self._next_violation_id += 1
            vehicle.confirmed_at = now
            events.append(
                ViolationEvent(
                    kind="started",
                    violation_id=vehicle.violation_id,
                    track_id=vehicle.track_id,
                    zone_id=vehicle.zone.id,
                    vehicle_class=vehicle.vehicle_class,
                    confidence=round(vehicle.confidence, 3),
                    box=vehicle.last_box,
                    stopped_at=vehicle.anchor_time,
                    confirmed_at=now,
                )
            )
        return events

    def _expire_unseen(self, now: float, seen: set[int]) -> list[ViolationEvent]:
        events: list[ViolationEvent] = []
        for track_id in list(self._vehicles):
            vehicle = self._vehicles[track_id]
            if track_id in seen:
                continue
            # Only a vehicle that had come to rest is worth remembering while
            # hidden. One that was driving through has simply left; keeping it
            # would let the next vehicle to pass that spot inherit its record.
            at_rest = self._state(vehicle, vehicle.last_seen) is not State.MOVING
            limit = (
                self.config.occlusion_tolerance_seconds
                if at_rest
                else self.config.move_confirm_seconds
            )
            if now - vehicle.last_seen <= limit:
                continue
            if vehicle.violation_id is not None:
                events.append(self._end_event(vehicle, vehicle.last_seen))
            del self._vehicles[track_id]
        return events

    def _state(self, vehicle: _Vehicle, now: float) -> State:
        if vehicle.violation_id is not None:
            return State.VIOLATION
        if (
            vehicle.moved_since is None
            and now - vehicle.anchor_time >= self.config.stop_confirm_seconds
        ):
            return State.STOPPED
        return State.MOVING

    def _end_event(self, vehicle: _Vehicle, ended_at: float) -> ViolationEvent:
        return ViolationEvent(
            kind="ended",
            violation_id=vehicle.violation_id,
            track_id=vehicle.track_id,
            zone_id=vehicle.zone.id,
            vehicle_class=vehicle.vehicle_class,
            confidence=round(vehicle.confidence, 3),
            box=vehicle.last_box,
            stopped_at=vehicle.anchor_time,
            confirmed_at=vehicle.confirmed_at,
            ended_at=ended_at,
        )
