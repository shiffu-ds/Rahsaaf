"""Ignore areas proposed from alerts rejected as "Not a vehicle"."""
from worker.learn import parse_box, suggest_ignore_areas
from worker.zones import IgnoreArea, drop_ignored

BOOTH = (0.68, 0.46, 0.80, 0.65)
BOOTH_AGAIN = (0.67, 0.47, 0.79, 0.64)
ELSEWHERE = (0.10, 0.10, 0.20, 0.20)


class Seen:
    def __init__(self, box):
        self.box = box


def test_parse_box():
    assert parse_box("0.6800,0.4600,0.8000,0.6500") == BOOTH


def test_one_rejection_is_not_enough():
    assert suggest_ignore_areas([BOOTH]) == []


def test_two_rejections_at_one_spot_make_an_area():
    [(area, count)] = suggest_ignore_areas([BOOTH, ELSEWHERE, BOOTH_AGAIN])
    assert count == 2
    xs = [x for x, _ in area.polygon]
    ys = [y for _, y in area.polygon]
    # Covers both boxes, with a small margin.
    assert min(xs) < 0.67 and max(xs) > 0.80 and min(ys) < 0.46 and max(ys) > 0.65


def test_the_learned_area_drops_the_same_box_next_time():
    [(area, _)] = suggest_ignore_areas([BOOTH, BOOTH_AGAIN])
    pixels = Seen((680, 460, 800, 650))
    assert drop_ignored([pixels], [area], 1000, 1000) == []


def test_minimum_can_be_raised():
    assert suggest_ignore_areas([BOOTH, BOOTH_AGAIN], minimum=3) == []


def test_spot_already_ignored_is_not_proposed_again():
    existing = [IgnoreArea("Booth", ((0.66, 0.44), (0.81, 0.44), (0.81, 0.67), (0.66, 0.67)))]
    assert suggest_ignore_areas([BOOTH, BOOTH_AGAIN], existing) == []


def test_two_separate_spots_give_two_areas():
    other = (0.11, 0.11, 0.21, 0.21)
    found = suggest_ignore_areas([BOOTH, ELSEWHERE, BOOTH_AGAIN, other])
    assert [count for _, count in found] == [2, 2]
    assert len({area.name for area, _ in found}) == 2
