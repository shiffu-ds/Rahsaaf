"""Congestion impact, tested with made-up traffic.

Frames are 1000 x 1000. The no-parking zone is a strip along the right kerb
(x 800..1000) and the driving lane is the strip beside it (x 500..800).
Traffic drives down the lane from top to bottom.
"""
import pytest

from worker.congestion import CongestionConfig, ImpactMonitor, footprint_inside, level_for
from worker.parking_state import Observation
from worker.zones import Zone

W = H = 1000
FPS = 5
KERB = ((0.8, 0.0), (1.0, 0.0), (1.0, 1.0), (0.8, 1.0))
LANE = ((0.5, 0.0), (0.8, 0.0), (0.8, 1.0), (0.5, 1.0))
ZONE = Zone("z1", "Kerb", KERB, 10.0, lane=LANE)
CONFIG = CongestionConfig(baseline_warmup=60.0)

AT_KERB = (850, 400, 950, 500)  # entirely on the kerb side
DOUBLE_PARKED = (600, 400, 700, 500)  # entirely in the driving lane
HALF_OUT = (750, 400, 850, 500)  # straddling the line


def car(track_id, x, y, size=100):
    return Observation(track_id, (x, y, x + size, y + size))


def flowing(t, per_minute, speed=250.0):
    """Cars entering the top of the lane at a steady rate and driving down it."""
    gap = 60.0 / per_minute
    cars = []
    first = int(max(0.0, t - H / speed) / gap)
    for n in range(first, int(t / gap) + 1):
        y = (t - n * gap) * speed - 100
        if -100 <= y <= H - 100:
            cars.append(car(1000 + n, 600, y))
    return cars


def run(monitor, seconds, traffic, start=0.0):
    t = start
    for i in range(int(seconds * FPS)):
        t = start + i / FPS
        monitor.update(t, traffic(t), W, H)
    return t


def test_levels():
    assert [level_for(s) for s in (0.0, 0.29, 0.3, 0.59, 0.6, 1.0)] == [
        "Low", "Low", "Medium", "Medium", "High", "High",
    ]


@pytest.mark.parametrize(
    "box, expected",
    [(AT_KERB, 0.0), (DOUBLE_PARKED, 1.0), (HALF_OUT, pytest.approx(0.5, abs=0.07))],
)
def test_lane_blocked_follows_how_far_the_vehicle_sticks_out(box, expected):
    assert footprint_inside(box, LANE, W, H) == expected


def test_no_lane_marked_means_no_score():
    monitor = ImpactMonitor([Zone("plain", "Plain", KERB, 10.0)])
    assert not monitor.enabled
    assert monitor.score(0, "plain", AT_KERB, W, H) is None


def test_kerb_parking_on_an_empty_road_is_low_impact():
    monitor = ImpactMonitor([ZONE], CONFIG)
    run(monitor, 5, lambda t: [])
    impact = monitor.score(5, "z1", AT_KERB, W, H)
    assert impact.score == 0.0
    assert impact.level == "Low"
    assert not impact.baseline_ready


def test_double_parking_scores_from_the_first_moment():
    monitor = ImpactMonitor([ZONE], CONFIG)
    impact = monitor.score(0, "z1", DOUBLE_PARKED, W, H)
    assert impact.lane_blocked == 1.0
    assert impact.score == 0.2  # lane-blocked weight alone


def test_standing_vehicles_in_the_lane_form_the_queue():
    monitor = ImpactMonitor([ZONE], CONFIG)
    queue = [car(i, 600, 100 + 150 * i) for i in range(3)]
    end = run(monitor, 4, lambda t: queue)
    impact = monitor.score(end, "z1", AT_KERB, W, H)
    assert impact.queued_vehicles == 3
    assert impact.queue == 0.6  # 3 of a capacity of 5
    assert impact.score == pytest.approx(0.18)


def test_moving_vehicles_are_not_a_queue():
    monitor = ImpactMonitor([ZONE], CONFIG)
    end = run(monitor, 10, lambda t: flowing(t, per_minute=20))
    assert monitor.score(end, "z1", AT_KERB, W, H).queued_vehicles == 0


def test_the_parked_vehicle_is_not_counted_in_its_own_queue():
    monitor = ImpactMonitor([ZONE], CONFIG)
    end = run(monitor, 4, lambda t: [Observation(7, DOUBLE_PARKED)])
    assert monitor.score(end, "z1", DOUBLE_PARKED, W, H, exclude_track=7).queued_vehicles == 0
    # Even if the tracker has since given it a different ID.
    assert monitor.score(end, "z1", DOUBLE_PARKED, W, H, exclude_track=99).queued_vehicles == 0


def test_vehicles_outside_the_lane_are_ignored():
    monitor = ImpactMonitor([ZONE], CONFIG)
    elsewhere = [car(i, 100, 100 + 200 * i) for i in range(4)]
    end = run(monitor, 4, lambda t: elsewhere)
    assert monitor.score(end, "z1", AT_KERB, W, H).queued_vehicles == 0


def test_flow_drop_appears_once_normal_flow_is_known_and_traffic_stalls():
    monitor = ImpactMonitor([ZONE], CONFIG)
    # Three minutes of clear road at 20 vehicles a minute teaches "normal".
    end = run(monitor, 180, lambda t: flowing(t, per_minute=20))
    before = monitor.score(end, "z1", AT_KERB, W, H)
    assert before.baseline_ready
    assert before.flow_drop < 0.15

    # A vehicle double-parks; traffic stops getting through and backs up.
    monitor.violation_started("z1")
    jam = [car(i, 600, 50 + 130 * i) for i in range(5)]
    end = run(monitor, 70, lambda t: jam + [Observation(7, DOUBLE_PARKED)], start=end + 0.2)
    during = monitor.score(end, "z1", DOUBLE_PARKED, W, H, exclude_track=7)
    assert during.flow_drop == 1.0
    assert during.queue == 1.0
    assert during.score == 1.0
    assert during.level == "High"


def test_normal_flow_is_not_learned_while_a_violation_is_active():
    monitor = ImpactMonitor([ZONE], CONFIG)
    monitor.violation_started("z1")
    end = run(monitor, 300, lambda t: flowing(t, per_minute=3))  # held-up trickle
    assert not monitor.score(end, "z1", AT_KERB, W, H).baseline_ready
    monitor.violation_ended("z1")
    end = run(monitor, 200, lambda t: flowing(t, per_minute=20), start=end + 0.2)
    assert monitor.score(end, "z1", AT_KERB, W, H).baseline_ready


def test_quiet_road_gives_no_flow_drop():
    # One car every two minutes: "fewer cars than normal" would mean nothing.
    monitor = ImpactMonitor([ZONE], CONFIG)
    end = run(monitor, 400, lambda t: flowing(t, per_minute=0.5))
    impact = monitor.score(end, "z1", AT_KERB, W, H)
    assert not impact.baseline_ready
    assert impact.flow_drop == 0.0
