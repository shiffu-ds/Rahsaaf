"""Compares violations the system raised with violations a person marked.

Used to answer the two questions that matter about the detector:

* **Precision.** Of the alerts it raised, how many were real?
* **Recall.** Of the real violations, how many did it catch?
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Interval:
    """A vehicle parked in a zone from ``start`` to ``end`` (seconds into the video)."""
    zone: str
    start: float
    end: float

    def overlap(self, other: "Interval") -> float:
        if self.zone != other.zone:
            return 0.0
        return max(0.0, min(self.end, other.end) - max(self.start, other.start))


@dataclass(frozen=True)
class Score:
    matched: list[tuple[Interval, Interval]]  # (true, detected)
    missed: list[Interval]  # real violations the system did not raise
    false_alarms: list[Interval]  # alerts with no real violation behind them

    @property
    def precision(self) -> float | None:
        raised = len(self.matched) + len(self.false_alarms)
        return len(self.matched) / raised if raised else None

    @property
    def recall(self) -> float | None:
        real = len(self.matched) + len(self.missed)
        return len(self.matched) / real if real else None


def match(truth: list[Interval], detected: list[Interval]) -> Score:
    """Pair each real violation with at most one alert, and the reverse.

    A pair needs the same zone and overlapping times. Where several pairings
    are possible, the ones that overlap longest are made first. One-to-one
    matters: two alerts for one parked car count as one hit and one false
    alarm, which is how an officer would experience them.
    """
    candidates = sorted(
        (
            (t.overlap(d), i, j)
            for i, t in enumerate(truth)
            for j, d in enumerate(detected)
            if t.overlap(d) > 0
        ),
        reverse=True,
    )
    used_truth: set[int] = set()
    used_detected: set[int] = set()
    matched = []
    for _, i, j in candidates:
        if i in used_truth or j in used_detected:
            continue
        used_truth.add(i)
        used_detected.add(j)
        matched.append((truth[i], detected[j]))

    return Score(
        matched=matched,
        missed=[t for i, t in enumerate(truth) if i not in used_truth],
        false_alarms=[d for j, d in enumerate(detected) if j not in used_detected],
    )
