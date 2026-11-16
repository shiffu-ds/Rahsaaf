"""No-parking zones and the geometry used to test vehicles against them.

Zone polygons are stored in normalised coordinates (0 to 1 on both axes), so a
zone drawn on one resolution keeps working when the stream is resized.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
Point = tuple[float, float]


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    polygon: tuple[Point, ...]  # normalised (x, y) points
    grace_seconds: float = 120.0
    #: Optional: the driving lane beside this zone, used to measure how much a
    #: parked vehicle is holding up traffic. Empty means "not measured".
    lane: tuple[Point, ...] = ()

    def __post_init__(self) -> None:
        if len(self.polygon) < 3:
            raise ValueError(f"zone {self.id!r} needs at least 3 points")
        if self.lane and len(self.lane) < 3:
            raise ValueError(f"zone {self.id!r}: a lane needs at least 3 points")
        if self.grace_seconds <= 0:
            raise ValueError(f"zone {self.id!r} needs a positive grace period")

    def contains(self, point: Point) -> bool:
        """True if a normalised point lies inside the polygon."""
        return point_in_polygon(point, self.polygon)

    def pixel_polygon(self, width: int, height: int) -> list[tuple[int, int]]:
        return [(round(x * width), round(y * height)) for x, y in self.polygon]


@dataclass(frozen=True)
class IgnoreArea:
    """A fixed thing in view that is not a vehicle: a booth, a kiosk, a sign.

    The detector sometimes calls such a thing a vehicle, and because it never
    moves it would be reported as parked for ever. A box that lies mostly
    inside an ignore area is dropped before anything else sees it.
    """

    name: str
    polygon: tuple[Point, ...]  # normalised (x, y) points

    def __post_init__(self) -> None:
        if len(self.polygon) < 3:
            raise ValueError(f"ignore area {self.name!r} needs at least 3 points")


def point_in_polygon(point: Point, polygon: tuple[Point, ...] | list[Point]) -> bool:
    """Ray-casting test. Points exactly on an edge may fall either way."""
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_cross = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def ground_point(box: Box, width: int, height: int) -> Point:
    """Normalised bottom-centre of a box: where the vehicle meets the road.

    The centre of the box is the wrong point to test. Seen from a raised
    camera, a tall vehicle's centre floats above the road and can sit inside a
    zone the vehicle is not actually standing in.
    """
    x1, _, x2, y2 = box
    return ((x1 + x2) / 2 / width, y2 / height)


def iou(a: Box, b: Box) -> float:
    """Overlap of two boxes, 0 (apart) to 1 (identical)."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def share_inside(box: Box, polygon: tuple[Point, ...], width: int, height: int) -> float:
    """How much of a box lies inside a normalised polygon, 0 to 1.

    Measured on an 8 x 8 grid of points across the box, which is accurate
    enough for a yes/no decision and needs no geometry library.
    """
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return 0.0
    steps = 8
    inside = 0
    for row in range(steps):
        y = (y1 + (row + 0.5) * (y2 - y1) / steps) / height
        for col in range(steps):
            x = (x1 + (col + 0.5) * (x2 - x1) / steps) / width
            inside += point_in_polygon((x, y), polygon)
    return inside / (steps * steps)


def drop_ignored(observations: list, areas, width: int, height: int, share: float = 0.6) -> list:
    """Remove detections that lie mostly inside an ignore area.

    ``share`` is how much of the box must be inside. A real vehicle parked in
    front of a booth only partly overlaps it and is kept.
    """
    if not areas:
        return observations
    return [
        obs
        for obs in observations
        if not any(share_inside(obs.box, area.polygon, width, height) >= share for area in areas)
    ]


def load_ignore_areas(path: str | Path) -> list[IgnoreArea]:
    """Read the ignore areas from a zones file. A file without any gives []."""
    raw = json.loads(Path(path).read_text())
    return [
        IgnoreArea(
            name=str(item.get("name", f"ignore{number}")),
            polygon=tuple((float(x), float(y)) for x, y in item["polygon"]),
        )
        for number, item in enumerate(raw.get("ignore", []), start=1)
    ]


def load_zones(path: str | Path) -> list[Zone]:
    """Read zones from a JSON file written by tools/draw_zone.py."""
    raw = json.loads(Path(path).read_text())
    return [
        Zone(
            id=str(item["id"]),
            name=item.get("name", str(item["id"])),
            polygon=tuple((float(x), float(y)) for x, y in item["polygon"]),
            grace_seconds=float(item.get("grace_seconds", 120.0)),
            lane=tuple((float(x), float(y)) for x, y in item.get("lane", [])),
        )
        for item in raw["zones"]
    ]


def save_zones(path: str | Path, zones: list[Zone], ignore=()) -> None:
    payload: dict = {
        "zones": [
            {
                "id": z.id,
                "name": z.name,
                "polygon": [[round(x, 4), round(y, 4)] for x, y in z.polygon],
                "grace_seconds": z.grace_seconds,
                **({"lane": [[round(x, 4), round(y, 4)] for x, y in z.lane]} if z.lane else {}),
            }
            for z in zones
        ]
    }
    if ignore:
        payload["ignore"] = [
            {"name": a.name, "polygon": [[round(x, 4), round(y, 4)] for x, y in a.polygon]}
            for a in ignore
        ]
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")
