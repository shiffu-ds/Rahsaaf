import pytest

from worker.zones import Zone, ground_point, iou, load_zones, point_in_polygon, save_zones

SQUARE = ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8))


def test_point_inside_and_outside_square():
    assert point_in_polygon((0.5, 0.5), SQUARE)
    assert not point_in_polygon((0.1, 0.5), SQUARE)
    assert not point_in_polygon((0.5, 0.9), SQUARE)


def test_point_in_concave_polygon():
    # An L shape: the notch at the top right is outside.
    l_shape = ((0, 0), (0.5, 0), (0.5, 0.5), (1, 0.5), (1, 1), (0, 1))
    assert point_in_polygon((0.25, 0.25), l_shape)
    assert point_in_polygon((0.75, 0.75), l_shape)
    assert not point_in_polygon((0.75, 0.25), l_shape)


def test_ground_point_is_bottom_centre():
    assert ground_point((100, 50, 300, 250), 1000, 500) == (0.2, 0.5)


def test_tall_vehicle_uses_wheels_not_centre():
    # Box centre is inside the zone, but its wheels are below it.
    zone = Zone("z", "z", ((0.0, 0.0), (1.0, 0.0), (1.0, 0.5), (0.0, 0.5)))
    box = (400, 100, 600, 700)  # centre y = 400 of 1000 -> inside; bottom 700 -> outside
    assert not zone.contains(ground_point(box, 1000, 1000))


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)


def test_zone_rejects_bad_input():
    with pytest.raises(ValueError):
        Zone("z", "z", ((0, 0), (1, 1)))
    with pytest.raises(ValueError):
        Zone("z", "z", SQUARE, grace_seconds=0)


def test_zones_round_trip(tmp_path):
    path = tmp_path / "zones.json"
    zones = [Zone("gate", "Hospital gate", SQUARE, grace_seconds=45)]
    save_zones(path, zones)
    assert load_zones(path) == zones


def test_lane_round_trips_and_is_optional(tmp_path):
    lane = ((0.0, 0.2), (0.2, 0.2), (0.2, 0.8), (0.0, 0.8))
    zones = [Zone("a", "With lane", SQUARE, 30, lane=lane), Zone("b", "Without", SQUARE)]
    path = tmp_path / "zones.json"
    save_zones(path, zones)
    assert load_zones(path) == zones
    assert '"lane"' not in path.read_text().split('"b"')[1]  # nothing written when unset


def test_lane_needs_three_points():
    with pytest.raises(ValueError):
        Zone("z", "z", SQUARE, lane=((0, 0), (1, 1)))


# --- ignore areas: fixed things (a booth, a kiosk) that are not vehicles ---

from dataclasses import dataclass  # noqa: E402

from worker.zones import (  # noqa: E402
    IgnoreArea,
    drop_ignored,
    load_ignore_areas,
    share_inside,
)

BOOTH = IgnoreArea("Booth", ((0.6, 0.4), (0.8, 0.4), (0.8, 0.7), (0.6, 0.7)))


@dataclass
class Seen:
    box: tuple


def test_share_inside_full_none_and_half():
    square = ((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0))
    assert share_inside((0, 0, 100, 100), square, 1000, 1000) == 1.0
    assert share_inside((600, 0, 700, 100), square, 1000, 1000) == 0.0
    assert share_inside((400, 0, 600, 100), square, 1000, 1000) == 0.5
    assert share_inside((100, 100, 100, 200), square, 1000, 1000) == 0.0  # empty box


def test_box_on_the_booth_is_dropped():
    booth_box = Seen((610, 410, 790, 690))
    assert drop_ignored([booth_box], [BOOTH], 1000, 1000) == []


def test_vehicle_in_front_of_the_booth_is_kept():
    # Overlaps the lower part of the booth only: a real vehicle parked there.
    car = Seen((580, 600, 760, 850))
    elsewhere = Seen((100, 100, 200, 200))
    assert drop_ignored([car, elsewhere], [BOOTH], 1000, 1000) == [car, elsewhere]


def test_no_ignore_areas_changes_nothing():
    seen = [Seen((610, 410, 790, 690))]
    assert drop_ignored(seen, [], 1000, 1000) is seen


def test_ignore_area_needs_three_points():
    with pytest.raises(ValueError):
        IgnoreArea("bad", ((0, 0), (1, 1)))


def test_ignore_areas_save_and_load(tmp_path):
    path = tmp_path / "zones.json"
    zones = [Zone("gate", "Hospital gate", SQUARE, grace_seconds=45)]
    save_zones(path, zones, [BOOTH])
    assert load_zones(path) == zones
    assert load_ignore_areas(path) == [BOOTH]


def test_zones_file_without_ignore_areas_loads_none(tmp_path):
    path = tmp_path / "zones.json"
    save_zones(path, [Zone("gate", "Hospital gate", SQUARE)])
    assert load_ignore_areas(path) == []
    assert "ignore" not in path.read_text()
