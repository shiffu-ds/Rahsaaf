"""Turn repeated "Not a vehicle" rejections into ignore areas.

When officers reject alerts at one spot as "Not a vehicle" again and again,
the thing there is a booth, a kiosk or a sign, not a vehicle. This module
groups the rejected boxes by position and proposes an ignore area for each
spot that was rejected often enough.

It only proposes. A person runs ``tools/learn_ignore.py`` and decides whether
to apply the result, so one wrong click in the dashboard cannot blind the
camera to a piece of road.
"""
from __future__ import annotations

from worker.zones import Box, IgnoreArea, iou, share_inside


def parse_box(text: str) -> Box:
    """Read the "x1,y1,x2,y2" form the server stores (each value 0 to 1)."""
    x1, y1, x2, y2 = (float(part) for part in text.split(","))
    return (x1, y1, x2, y2)


def suggest_ignore_areas(
    boxes: list[Box],
    existing: list[IgnoreArea] | tuple = (),
    minimum: int = 2,
    same_spot_iou: float = 0.5,
    margin: float = 0.01,
) -> list[tuple[IgnoreArea, int]]:
    """Propose ignore areas from normalised boxes of rejected alerts.

    Boxes that overlap by ``same_spot_iou`` or more are treated as one spot.
    A spot is proposed once it has ``minimum`` rejections, and skipped if an
    existing ignore area already covers it. Returns (area, rejection count).
    """
    groups: list[list[Box]] = []
    for box in boxes:
        for group in groups:
            if iou(box, group[0]) >= same_spot_iou:
                group.append(box)
                break
        else:
            groups.append([box])

    proposals = []
    for group in groups:
        if len(group) < minimum:
            continue
        x1 = max(0.0, min(b[0] for b in group) - margin)
        y1 = max(0.0, min(b[1] for b in group) - margin)
        x2 = min(1.0, max(b[2] for b in group) + margin)
        y2 = min(1.0, max(b[3] for b in group) + margin)
        # The boxes are already fractions of the frame, so the frame is 1 x 1.
        if any(share_inside(group[0], area.polygon, 1, 1) >= 0.6 for area in existing):
            continue
        number = len(existing) + len(proposals) + 1
        polygon = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        proposals.append((IgnoreArea(f"Learned spot {number}", polygon), len(group)))
    return proposals
