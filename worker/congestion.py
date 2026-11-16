"""Measures how much a wrongly parked vehicle is holding up traffic.

Two cars can both be parked illegally while only one of them is causing a
jam. This module gives each violation an impact score so the worst one can be
dealt with first.

It needs to know where the driving lane is: each zone may carry a ``lane``
polygon marking the road beside it. Three things are measured there:

* **Lane blocked.** How much of the parked vehicle's footprint sits in the
  driving lane. A car tucked against the kerb scores 0; one double-parked in
  the lane scores near 1. Known the instant the violation starts.
* **Queue.** How many vehicles are standing still in the lane right now.
* **Flow drop.** How many vehicles get through the lane per minute, compared
  with what is normal for this camera. "Normal" is learned while no violation
  is active in the zone, so it takes a few minutes of clear road to exist.

    impact = 0.5 x flow drop + 0.3 x queue + 0.2 x lane blocked

Each part runs from 0 to 1. These weights are a first guess, to be tuned on
real footage.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from worker.parking_state import Observation
from worker.zones import Box, Zone, ground_point, iou, point_in_polygon

WEIGHT_FLOW, WEIGHT_QUEUE, WEIGHT_LANE = 0.5, 0.3, 0.2


def level_for(score: float) -> str:
    if score >= 0.6:
        return "High"
    if score >= 0.3:
        return "Medium"
    return "Low"


@dataclass(frozen=True)
class Impact:
    score: float
    level: str
    flow_drop: float
    queue: float
    lane_blocked: float
    queued_vehicles: int
    #: False until enough clear-road time has passed to know what normal flow
    #: is. Until then flow drop counts as 0 and the score is an underestimate.
    baseline_ready: bool

    def parts(self) -> dict:
        return {
            "flow_drop": self.flow_drop,
            "queue": self.queue,
            "lane_blocked": self.lane_blocked,
            "queued_vehicles": self.queued_vehicles,
            "baseline_ready": self.baseline_ready,
        }


@dataclass(frozen=True)
class CongestionConfig:
    #: Standing vehicles in the lane that count as a full queue.
    queue_capacity: int = 5
    #: A vehicle is "standing" if its box still overlaps this much with where
    #: it was ``still_window`` seconds ago.
    still_iou: float = 0.6
    still_window: float = 1.5
    #: Flow is counted over this many seconds.
    flow_window: float = 60.0
    #: Clear-road time needed before normal flow is trusted.
    baseline_warmup: float = 120.0
    #: Below this many vehicles a minute the road is too quiet for a "drop"
    #: to mean anything.
    min_baseline_per_minute: float = 2.0
    #: How quickly normal flow follows the road's changing rhythm.
    baseline_smoothing: float = 0.1
    sample_every: float = 10.0
    #: A track unseen this long has left the lane.
    gone_after: float = 1.0


class _Lane:
    def __init__(self, zone: Zone):
        self.zone = zone
        self.tracks: dict[int, deque[tuple[float, Box]]] = {}
        self.last_seen: dict[int, float] = {}
        self.moved: set[int] = set()  # tracks that were seen moving at least once
        self.exits: deque[float] = deque()  # times a moving vehicle left the lane
        self.baseline: float | None = None  # vehicles per minute on a clear road
        self.clear_since: float | None = None
        self.last_sample = 0.0
        self.active_violations = 0


class ImpactMonitor:
    def __init__(self, zones: list[Zone], config: CongestionConfig | None = None):
        self.config = config or CongestionConfig()
        self._lanes = {zone.id: _Lane(zone) for zone in zones if zone.lane}

    @property
    def enabled(self) -> bool:
        return bool(self._lanes)

    def has_lane(self, zone_id: str) -> bool:
        return zone_id in self._lanes

    def violation_started(self, zone_id: str) -> None:
        if zone_id in self._lanes:
            self._lanes[zone_id].active_violations += 1
            self._lanes[zone_id].clear_since = None

    def violation_ended(self, zone_id: str) -> None:
        lane = self._lanes.get(zone_id)
        if lane:
            lane.active_violations = max(0, lane.active_violations - 1)

    def update(self, now: float, observations: list[Observation], width: int, height: int) -> None:
        """Feed every frame's tracked vehicles, whether or not anything is wrong."""
        cfg = self.config
        for lane in self._lanes.values():
            for obs in observations:
                if not point_in_polygon(ground_point(obs.box, width, height), lane.zone.lane):
                    continue
                history = lane.tracks.setdefault(obs.track_id, deque())
                history.append((now, obs.box))
                while now - history[0][0] > cfg.still_window * 2:
                    history.popleft()
                lane.last_seen[obs.track_id] = now
                if len(history) >= 2 and not self._standing(history, now):
                    lane.moved.add(obs.track_id)

            for track_id in [t for t, seen in lane.last_seen.items() if now - seen > cfg.gone_after]:
                # Only a vehicle that was driving counts as having got through.
                if track_id in lane.moved:
                    lane.exits.append(lane.last_seen[track_id])
                lane.tracks.pop(track_id, None)
                lane.last_seen.pop(track_id, None)
                lane.moved.discard(track_id)

            while lane.exits and now - lane.exits[0] > cfg.flow_window:
                lane.exits.popleft()

            self._learn_baseline(lane, now)

    def score(
        self,
        now: float,
        zone_id: str,
        vehicle_box: Box,
        width: int,
        height: int,
        exclude_track: int | None = None,
    ) -> Impact | None:
        """Impact of the vehicle parked at ``vehicle_box``; None with no lane marked."""
        lane = self._lanes.get(zone_id)
        if lane is None:
            return None
        cfg = self.config

        blocked = footprint_inside(vehicle_box, lane.zone.lane, width, height)

        standing = sum(
            1
            for track_id, history in lane.tracks.items()
            if track_id != exclude_track
            # The parked vehicle itself may stand partly in the lane.
            and iou(history[-1][1], vehicle_box) < 0.5
            and self._standing(history, now)
        )
        queue = min(1.0, standing / cfg.queue_capacity)

        ready = lane.baseline is not None and lane.baseline >= cfg.min_baseline_per_minute
        flow_drop = 0.0
        if ready:
            per_minute = len(lane.exits) * 60.0 / cfg.flow_window
            flow_drop = min(1.0, max(0.0, 1.0 - per_minute / lane.baseline))

        total = WEIGHT_FLOW * flow_drop + WEIGHT_QUEUE * queue + WEIGHT_LANE * blocked
        return Impact(
            score=round(total, 3),
            level=level_for(total),
            flow_drop=round(flow_drop, 3),
            queue=round(queue, 3),
            lane_blocked=round(blocked, 3),
            queued_vehicles=standing,
            baseline_ready=ready,
        )

    # ---------------------------------------------------------------- internal

    def _standing(self, history: deque, now: float) -> bool:
        """Has this vehicle stayed put for ``still_window`` seconds?"""
        cfg = self.config
        newest_time, newest_box = history[-1]
        if now - newest_time > cfg.gone_after:
            return False
        past = [box for time, box in history if newest_time - time >= cfg.still_window]
        if not past:
            return False  # not watched long enough to say
        return iou(past[-1], newest_box) >= cfg.still_iou

    def _learn_baseline(self, lane: _Lane, now: float) -> None:
        cfg = self.config
        if lane.active_violations:
            return
        if lane.clear_since is None:
            lane.clear_since = now
        # A full flow window of clear road must pass first, or the count would
        # still include traffic held up by the violation that just ended.
        if now - lane.clear_since < max(cfg.flow_window, cfg.baseline_warmup):
            return
        if now - lane.last_sample < cfg.sample_every:
            return
        lane.last_sample = now
        per_minute = len(lane.exits) * 60.0 / cfg.flow_window
        if lane.baseline is None:
            lane.baseline = per_minute
        else:
            a = cfg.baseline_smoothing
            lane.baseline = (1 - a) * lane.baseline + a * per_minute


def footprint_inside(box: Box, polygon, width: int, height: int) -> float:
    """Share of a vehicle's footprint that lies inside a polygon, 0 to 1.

    The footprint is taken as the bottom third of the box: seen from a raised
    camera that is roughly the patch of road the vehicle stands on, while the
    top of the box is the vehicle's roof, floating over whatever is behind it.
    """
    x1, y1, x2, y2 = box
    top = y2 - (y2 - y1) / 3
    columns, rows = 9, 3
    inside = 0
    for i in range(columns):
        x = x1 + (x2 - x1) * (i + 0.5) / columns
        for j in range(rows):
            y = top + (y2 - top) * (j + 0.5) / rows
            inside += point_in_polygon((x / width, y / height), polygon)
    return inside / (columns * rows)
