"""Summaries for the dashboard's analytics page.

Everything here is computed from the stored violations on request. With the
volumes one site produces that is instant, and it means the figures can never
drift out of step with the records.

Alerts an officer rejected are left out of the counts of *violations*: they
were mistakes by the system, not wrong parking. They are reported separately,
with the reasons given, because that is the record of where the system fails.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

REAL = ("Pending", "Confirmed", "Action Taken")  # not rejected
UPHELD = ("Confirmed", "Action Taken")


def build(violations: list[dict], reject_reasons: list[dict], timezone: str, days: int) -> dict:
    zone = ZoneInfo(timezone)
    now = datetime.now(zone)
    since = now - timedelta(days=days)

    rows = []
    for v in violations:
        local = datetime.fromisoformat(v["started_at"]).astimezone(zone)
        if local >= since:
            rows.append({**v, "local": local})

    real = [r for r in rows if r["status"] in REAL]
    rejected = [r for r in rows if r["status"] == "Rejected"]
    upheld = [r for r in rows if r["status"] in UPHELD]
    decided = len(upheld) + len(rejected)

    return {
        "days": days,
        "timezone": timezone,
        "summary": {
            "violations": len(real),
            "pending": sum(r["status"] == "Pending" for r in rows),
            "confirmed": len(upheld),
            "rejected": len(rejected),
            # Of the alerts an officer has judged, the share that were wrong.
            "rejected_share": round(len(rejected) / decided, 3) if decided else None,
            "plates_read_share": (
                round(sum(bool(r["plate_text"]) for r in real) / len(real), 3) if real else None
            ),
            "high_impact": sum(r.get("impact_level") == "High" for r in real),
            "median_parked_seconds": _median(r["duration_seconds"] for r in real),
        },
        "by_hour": _by_hour(real),
        "by_day": _by_day(real, now, min(days, 14)),
        "hotspots": _hotspots(rows),
        "repeat_offenders": _repeat_offenders(real),
        "reject_reasons": reject_reasons,
    }


def _median(values) -> float | None:
    known = [v for v in values if v is not None]
    return round(median(known), 1) if known else None


def _by_hour(rows: list[dict]) -> list[int]:
    counts = [0] * 24
    for row in rows:
        counts[row["local"].hour] += 1
    return counts


def _by_day(rows: list[dict], now: datetime, days: int) -> list[dict]:
    counts = Counter(row["local"].date() for row in rows)
    start = now.date() - timedelta(days=days - 1)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "count": counts[start + timedelta(days=i)]}
        for i in range(days)
    ]


def _hotspots(rows: list[dict]) -> list[dict]:
    by_camera: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_camera[row["camera_name"]].append(row)

    spots = []
    for name, group in by_camera.items():
        real = [r for r in group if r["status"] in REAL]
        hours = _by_hour(real)
        spots.append(
            {
                "camera_name": name,
                "latitude": group[0]["latitude"],
                "longitude": group[0]["longitude"],
                "violations": len(real),
                "rejected": sum(r["status"] == "Rejected" for r in group),
                "high_impact": sum(r.get("impact_level") == "High" for r in real),
                "median_parked_seconds": _median(r["duration_seconds"] for r in real),
                # The hour of day with the most violations, if there are any.
                "busiest_hour": max(range(24), key=hours.__getitem__) if real else None,
            }
        )
    return sorted(spots, key=lambda s: -s["violations"])


def _repeat_offenders(rows: list[dict]) -> list[dict]:
    by_plate: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["plate_text"]:
            by_plate[row["plate_text"]].append(row)

    offenders = []
    for plate, group in by_plate.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda r: r["local"])
        offenders.append(
            {
                "plate_text": plate,
                "violations": len(group),
                "cameras": sorted({r["camera_name"] for r in group}),
                "first_seen": group[0]["started_at"],
                "last_seen": group[-1]["started_at"],
                "last_id": group[-1]["id"],
                # A plate nobody has checked may be a misread, and a misread
                # can make two different vehicles look like one offender.
                "officer_checked": any(r["plate_source"] == "officer" for r in group),
            }
        )
    return sorted(offenders, key=lambda o: (-o["violations"], o["plate_text"]))
