"""Rules of the parking state machine, tested with made-up tracks.

Frames are 1000 x 1000 pixels and arrive 5 times a second. The zone covers the
right half of the picture and allows 10 seconds of stopping.
"""
from worker.parking_state import Observation, ParkingConfig, ParkingMonitor, State
from worker.zones import Zone

W = H = 1000
FPS = 5
GRACE = 10.0
ZONE = Zone("z1", "Right side", ((0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)), GRACE)

IN_ZONE = (700, 400, 800, 500)
OUT_OF_ZONE = (100, 400, 200, 500)


def shift(box, dx, dy=0):
    return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)


def run(script, seconds, monitor=None):
    """script(t) -> list of Observation. Returns (monitor, all events)."""
    monitor = monitor or ParkingMonitor([ZONE])
    events = []
    for i in range(int(seconds * FPS) + 1):
        t = i / FPS
        events += monitor.update(t, script(t), W, H)
    return monitor, events


def started(events):
    return [e for e in events if e.kind == "started"]


def ended(events):
    return [e for e in events if e.kind == "ended"]


def test_parked_vehicle_raises_exactly_one_violation():
    _, events = run(lambda t: [Observation(1, IN_ZONE, "car", 0.9)], 30)
    assert len(started(events)) == 1
    event = started(events)[0]
    assert event.zone_id == "z1"
    assert event.vehicle_class == "car"
    assert event.stopped_at == 0.0
    assert event.confirmed_at == GRACE


def test_passing_vehicle_raises_nothing():
    # Drives through the zone at 100 px/s, a full box width every second.
    _, events = run(lambda t: [Observation(1, shift((500, 400, 600, 500), 100 * t))], 4)
    assert events == []


def test_slow_creeping_vehicle_raises_nothing():
    # 15 px/s: crawling in a queue, never really parked.
    _, events = run(lambda t: [Observation(1, shift((520, 400, 620, 500), 15 * t))], 25)
    assert events == []


def test_short_stop_within_grace_raises_nothing():
    def script(t):
        if t <= 6:  # passenger drop-off
            return [Observation(1, IN_ZONE)]
        return [Observation(1, shift(IN_ZONE, -150 * (t - 6)))]

    _, events = run(script, 12)
    assert events == []


def test_vehicle_parked_outside_zone_raises_nothing():
    monitor, events = run(lambda t: [Observation(1, OUT_OF_ZONE)], 30)
    assert events == []
    assert monitor.statuses(30) == []


def test_detector_jitter_does_not_reset_timer():
    def script(t):
        wobble = 4 if int(t * FPS) % 2 else -4
        return [Observation(1, shift(IN_ZONE, wobble, -wobble))]

    _, events = run(script, 15)
    assert len(started(events)) == 1
    assert started(events)[0].confirmed_at == GRACE


def test_brief_bad_box_does_not_reset_timer():
    # For half a second a passing bus leaves only half the car visible.
    def script(t):
        if 5.0 <= t < 5.5:
            return [Observation(1, (700, 400, 750, 500))]
        return [Observation(1, IN_ZONE)]

    _, events = run(script, 15)
    assert len(started(events)) == 1
    assert started(events)[0].confirmed_at == GRACE


def test_short_disappearance_keeps_the_timer():
    def script(t):
        return [] if 4 <= t < 7 else [Observation(1, IN_ZONE)]

    _, events = run(script, 15)
    assert len(started(events)) == 1
    assert started(events)[0].confirmed_at == GRACE


def test_long_disappearance_forgets_the_vehicle():
    def script(t):
        return [] if 4 <= t < 12 else [Observation(1, IN_ZONE)]

    _, events = run(script, 15)
    assert events == []  # timer restarted at t=12, grace not reached by t=15


def test_track_id_switch_inherits_the_timer():
    def script(t):
        return [Observation(1 if t < 5 else 2, IN_ZONE)]

    _, events = run(script, 15)
    assert len(started(events)) == 1
    event = started(events)[0]
    assert event.track_id == 2
    assert event.stopped_at == 0.0
    assert event.confirmed_at == GRACE


def test_new_vehicle_does_not_steal_timer_of_one_still_present():
    # A second, overlapping detection must not take over vehicle 1's record.
    def script(t):
        obs = [Observation(1, IN_ZONE)]
        if t >= 8:
            obs.insert(0, Observation(2, shift(IN_ZONE, 5)))
        return obs

    _, events = run(script, 12)
    assert [e.track_id for e in started(events)] == [1]


def test_violation_ends_when_vehicle_drives_away():
    def script(t):
        if t <= 20:
            return [Observation(1, IN_ZONE)]
        box = shift(IN_ZONE, -200 * (t - 20))
        return [Observation(1, box)] if box[2] > 0 else []

    monitor, events = run(script, 30)
    assert len(started(events)) == 1
    assert len(ended(events)) == 1
    end = ended(events)[0]
    assert end.violation_id == started(events)[0].violation_id
    assert 20 <= end.ended_at <= 21
    assert 20 <= end.duration_seconds <= 21
    assert monitor.statuses(30) == []


def test_violation_ends_when_vehicle_vanishes():
    _, events = run(lambda t: [Observation(1, IN_ZONE)] if t <= 15 else [], 25)
    assert len(ended(events)) == 1
    assert ended(events)[0].ended_at == 15.0


def test_same_vehicle_parking_twice_raises_two_violations():
    elsewhere = (550, 100, 650, 200)

    def script(t):
        if t <= 12:
            return [Observation(1, IN_ZONE)]
        return [Observation(1, elsewhere)]  # moves to another spot in the zone

    _, events = run(script, 30)
    assert len(started(events)) == 2
    assert len(ended(events)) == 1
    assert started(events)[0].violation_id != started(events)[1].violation_id


def test_two_vehicles_are_timed_independently():
    other = (600, 100, 700, 200)

    def script(t):
        obs = [Observation(1, IN_ZONE)]
        if t >= 5:
            obs.append(Observation(2, other))
        return obs

    _, events = run(script, 20)
    confirmed = {e.track_id: e.confirmed_at for e in started(events)}
    assert confirmed == {1: 10.0, 2: 15.0}


def test_states_progress_moving_stopped_violation():
    monitor = ParkingMonitor([ZONE])
    seen = {}
    for i in range(int(12 * FPS) + 1):
        t = i / FPS
        monitor.update(t, [Observation(1, IN_ZONE)], W, H)
        seen[t] = monitor.statuses(t)[0].state
    assert seen[1.0] is State.MOVING
    assert seen[5.0] is State.STOPPED
    assert seen[11.0] is State.VIOLATION


def test_flush_closes_open_violations():
    monitor, events = run(lambda t: [Observation(1, IN_ZONE)], 15)
    assert len(ended(events)) == 0
    closing = monitor.flush(15)
    assert [e.kind for e in closing] == ["ended"]
    assert closing[0].duration_seconds == 15.0


def test_grace_period_is_per_zone():
    quick = Zone("quick", "Quick", ((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)), 3.0)
    monitor = ParkingMonitor([ZONE, quick], ParkingConfig())
    _, events = run(
        lambda t: [Observation(1, IN_ZONE), Observation(2, OUT_OF_ZONE)], 12, monitor
    )
    confirmed = {e.zone_id: e.confirmed_at for e in started(events)}
    assert confirmed == {"quick": 3.0, "z1": 10.0}


def test_vehicle_that_drove_off_is_forgotten_quickly():
    # Passes through and leaves the picture at t=2.
    def script(t):
        return [Observation(1, shift((500, 400, 600, 500), 100 * t))] if t < 2 else []

    monitor, events = run(script, 4)
    assert events == []
    assert monitor.statuses(4) == []


def test_hidden_parked_vehicle_is_reported_as_not_visible():
    monitor = ParkingMonitor([ZONE])
    for i in range(int(4 * FPS) + 1):
        monitor.update(i / FPS, [Observation(1, IN_ZONE)], W, H)
    assert monitor.statuses(4.0)[0].visible
    monitor.update(4.2, [], W, H)
    status = monitor.statuses(4.2)[0]
    assert not status.visible
    assert status.state is State.STOPPED


def test_passing_vehicle_does_not_inherit_from_one_that_just_left():
    # Vehicle 1 drives through a spot and leaves; vehicle 2 then stops there.
    spot = (700, 400, 800, 500)

    def script(t):
        if t < 1:
            return [Observation(1, shift(spot, -100 + 100 * t))]
        if t < 3:
            return []
        return [Observation(2, spot)]

    _, events = run(script, 20)
    assert len(started(events)) == 1
    assert started(events)[0].stopped_at == 3.0
