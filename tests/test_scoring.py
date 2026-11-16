from worker.scoring import Interval, match


def test_perfect_detection():
    truth = [Interval("z1", 10, 200), Interval("z1", 300, 500)]
    score = match(truth, [Interval("z1", 12, 198), Interval("z1", 305, 499)])
    assert score.precision == 1.0 and score.recall == 1.0
    assert score.missed == [] and score.false_alarms == []


def test_missed_violation_lowers_recall():
    score = match([Interval("z1", 10, 200), Interval("z1", 300, 500)], [Interval("z1", 12, 198)])
    assert score.recall == 0.5
    assert score.precision == 1.0
    assert score.missed == [Interval("z1", 300, 500)]


def test_false_alarm_lowers_precision():
    score = match([Interval("z1", 10, 200)], [Interval("z1", 12, 198), Interval("z1", 600, 700)])
    assert score.precision == 0.5
    assert score.recall == 1.0
    assert score.false_alarms == [Interval("z1", 600, 700)]


def test_two_alerts_for_one_vehicle_count_once():
    score = match([Interval("z1", 10, 200)], [Interval("z1", 12, 90), Interval("z1", 95, 198)])
    assert len(score.matched) == 1
    assert score.matched[0][1] == Interval("z1", 95, 198)  # the longer overlap is the match
    assert score.false_alarms == [Interval("z1", 12, 90)]
    assert score.precision == 0.5


def test_one_alert_cannot_cover_two_vehicles():
    score = match([Interval("z1", 10, 100), Interval("z1", 90, 200)], [Interval("z1", 10, 200)])
    assert len(score.matched) == 1 and len(score.missed) == 1
    assert score.recall == 0.5


def test_same_time_in_another_zone_is_not_a_match():
    score = match([Interval("z1", 10, 200)], [Interval("z2", 10, 200)])
    assert score.matched == []
    assert score.precision == 0.0 and score.recall == 0.0


def test_nothing_to_measure_is_none_not_zero():
    empty = match([], [])
    assert empty.precision is None and empty.recall is None
    quiet = match([Interval("z1", 10, 200)], [])
    assert quiet.precision is None and quiet.recall == 0.0
