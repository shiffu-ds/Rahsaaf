"""Number plate reading.

A plate is read only for a vehicle that has just been confirmed as a
violation, never for every vehicle on the road. Reading works on a crop of
that vehicle cut from the full-size camera picture, where the plate has the
most pixels.

One read of one frame is not trusted. The same plate is read from several
frames and the reads vote: a result is accepted only when enough of them
agree, the agreed text looks like a plate, and the reader was confident.
Otherwise the plate is reported as unreadable.

**Never guess.** An alert carrying a wrong plate points at an innocent
person's vehicle, which is worse than an alert with no plate at all.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

#: Pakistani plates are one to four letters followed by one to four digits
#: ("LEA 1234", "ABC 123", "A 1234"), sometimes with a trailing letter. Spaces
#: and dashes are removed before matching.
PLATE_PATTERN = r"[A-Z]{1,4}[0-9]{1,4}[A-Z]?"


def normalise(text: str) -> str:
    """Upper-case letters and digits only: 'lea-1234 ' -> 'LEA1234'."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def looks_like_plate(text: str, pattern: str = PLATE_PATTERN) -> bool:
    return 3 <= len(text) <= 9 and re.fullmatch(pattern, text) is not None


@dataclass(frozen=True)
class PlateRead:
    """One reading of a plate from one frame."""
    text: str  # already normalised
    confidence: float  # the reader's least certain character, 0 to 1
    image: np.ndarray | None = None  # the plate cut out of the frame


@dataclass(frozen=True)
class PlateResult:
    text: str | None  # None means unreadable
    confidence: float
    reads: int  # how many frames gave any text
    agreeing: int  # how many of those gave the winning text
    image: np.ndarray | None = None
    reason: str = ""  # why it is unreadable, when it is

    @property
    def readable(self) -> bool:
        return self.text is not None


@dataclass
class PlateVoter:
    """Collects reads of one vehicle's plate and decides what, if anything, it says."""
    min_agreeing: int = 2
    min_confidence: float = 0.7
    pattern: str = PLATE_PATTERN
    _reads: list[PlateRead] = field(default_factory=list)

    def add(self, read: PlateRead | None) -> None:
        if read is not None and read.text:
            self._reads.append(read)

    @property
    def settled(self) -> bool:
        """True once more reads could not plausibly change the answer."""
        return self.result().agreeing >= self.min_agreeing + 1

    def result(self) -> PlateResult:
        if not self._reads:
            return PlateResult(None, 0.0, 0, 0, reason="no plate found")

        groups: dict[str, list[PlateRead]] = defaultdict(list)
        for read in self._reads:
            groups[read.text].append(read)
        # Most votes wins; total confidence breaks a tie in votes.
        ranked = sorted(
            groups.values(),
            key=lambda group: (len(group), sum(r.confidence for r in group)),
            reverse=True,
        )
        winner = ranked[0]
        text = winner[0].text
        confidence = sum(r.confidence for r in winner) / len(winner)
        best = max(winner, key=lambda r: r.confidence)
        # Even when unreadable, keep the clearest picture for the officer.
        clearest = max(self._reads, key=lambda r: r.confidence).image

        def unreadable(reason: str) -> PlateResult:
            return PlateResult(None, confidence, len(self._reads), len(winner), clearest, reason)

        if len(winner) < self.min_agreeing:
            return unreadable("reads did not agree")
        if len(ranked) > 1 and len(ranked[1]) == len(winner):
            return unreadable("two different readings were equally common")
        if not looks_like_plate(text, self.pattern):
            return unreadable("text does not look like a plate")
        if confidence < self.min_confidence:
            return unreadable("reader was not confident enough")
        return PlateResult(text, round(confidence, 3), len(self._reads), len(winner), best.image)


def crop_vehicle(frame: np.ndarray, box, scale: float = 1.0, margin: float = 0.06) -> np.ndarray | None:
    """Cut a vehicle out of the full-size frame.

    ``box`` is in the coordinates of the resized picture the detector saw;
    ``scale`` converts it back to the full-size frame. A small margin is added
    because plates sit at the very edge of the vehicle's box.
    """
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = (v * scale for v in box)
    pad_x, pad_y = (x2 - x1) * margin, (y2 - y1) * margin
    left, top = max(0, int(x1 - pad_x)), max(0, int(y1 - pad_y))
    right, bottom = min(width, int(x2 + pad_x)), min(height, int(y2 + pad_y))
    if right - left < 16 or bottom - top < 16:
        return None
    return frame[top:bottom, left:right]


def split_row(plate: np.ndarray) -> int:
    """The row that separates the top line of a two-line plate from the bottom.

    Looks for the emptiest row near the middle. On a one-line plate this still
    returns a row; whether the plate really has two lines is decided afterwards
    from what each half reads as.
    """
    grey = plate if plate.ndim == 2 else plate.mean(axis=2)
    height, width = grey.shape[:2]
    # Ink is whichever side of the mid-level is rarer: dark on a light plate,
    # light on a dark one.
    dark = grey < (float(grey.min()) + float(grey.max())) / 2
    ink = dark if dark.mean() < 0.5 else ~dark
    profile = ink[:, int(width * 0.25):].sum(axis=1)  # skip the emblem strip on the left
    low, high = int(height * 0.38), max(int(height * 0.62), int(height * 0.38) + 1)
    return low + int(np.argmin(profile[low:high]))


#: Top line of a two-line plate: the letters, perhaps followed by a year badge.
_TOP_LINE = re.compile(r"[A-Z]{1,4}[0-9]{0,2}")
#: Bottom line of a two-line plate: the number.
_BOTTOM_LINE = re.compile(r"[0-9]{1,4}[A-Z]?")


def combine_two_line(
    full: list[tuple[str, float]],
    top_text: str,
    bottom_text: str,
    bottom_confidence: float,
    override_confidence: float = 0.9,
) -> tuple[str, float] | None:
    """Correct a reading of a two-line plate using its bottom line.

    Punjab plates carry a small two-digit year beside the letters ("ABC·17"
    over "357"). Read whole, the year is taken for the start of the number
    ("ABC1735"). The bottom line read on its own has only the number.

    ``full`` is the whole-plate reading as (character, score) pairs. Returns
    (text, confidence), or None when the plate does not look two-line, in
    which case the whole-plate reading stands.

    * Letters come from the whole-plate reading: they are read better there
      than from a thin strip.
    * If the top line and the whole plate disagree on the number of letters,
      the confidence is set to 0.
    * If the bottom line agrees with the whole-plate number, nothing changes.
    * If it disagrees, the bottom line wins only when its own reading is very
      sure. Otherwise the confidence is set to 0: two readings that disagree
      are not a reading.
    """
    if not _TOP_LINE.fullmatch(top_text) or not _BOTTOM_LINE.fullmatch(bottom_text):
        return None
    letters = []
    for char, score in full:
        if not char.isalpha():
            break
        letters.append((char, score))
    if not letters:
        return None
    text = "".join(c for c, _ in full)
    top_letters = len(top_text.rstrip("0123456789"))
    if top_letters != len(letters):
        # The two readings disagree on how many letters there are, so one of
        # them dropped or invented a letter ("LE" for "LEB"). Not a reading.
        return text, 0.0
    if text[len(letters):] == bottom_text:
        return text, min(score for _, score in full)
    combined = "".join(c for c, _ in letters) + bottom_text
    if bottom_confidence < override_confidence:
        return combined, 0.0
    return combined, min(min(score for _, score in letters), bottom_confidence)


class PlateReader:
    """Finds a plate in a vehicle crop and reads it.

    Uses the open-source fast-alpr models, which run on a plain CPU: a small
    detector to find the plate and a character reader trained on plates from
    many countries. They were not trained on Pakistani plates specifically, so
    accuracy must be measured (tools/evaluate_plates.py), not assumed.
    """

    def __init__(self, min_plate_confidence: float = 0.4):
        from fast_alpr import ALPR  # imported here so tests need no models

        self._alpr = ALPR(detector_conf_thresh=min_plate_confidence)

    def _read_strip(self, strip: np.ndarray) -> tuple[str, float]:
        """Read one line of a plate on its own: (text, weakest character)."""
        if strip.size == 0 or strip.shape[0] < 6:
            return "", 0.0
        result = self._alpr.ocr.predict(strip)
        if result is None or not result.text:
            return "", 0.0
        scores = result.confidence
        if isinstance(scores, (list, tuple)):
            used = [float(v) for v in scores][: len(result.text)] or [0.0]
            return normalise(result.text), min(used)
        return normalise(result.text), float(scores)

    def read(self, vehicle: np.ndarray | None) -> PlateRead | None:
        if vehicle is None or vehicle.size == 0:
            return None
        results = [r for r in self._alpr.predict(vehicle) if r.ocr is not None]
        if not results:
            return None
        best = max(results, key=lambda r: r.detection.confidence)

        raw = best.ocr.text or ""
        scores = best.ocr.confidence
        if isinstance(scores, (list, tuple)):
            per_char = [float(v) for v in scores][: len(raw)]
        else:
            per_char = [float(scores)] * len(raw)
        per_char += [0.0] * (len(raw) - len(per_char))
        # One score per character. A plate is wrong if any single character is
        # wrong, so the weakest character sets the confidence.
        full = [(c, v) for c, v in zip(raw.upper(), per_char) if c.isascii() and c.isalnum()]
        text = "".join(c for c, _ in full)
        if not text:
            return None
        confidence = min(v for _, v in full)

        box = best.detection.bounding_box
        height, width = vehicle.shape[:2]
        top, bottom = max(0, box.y1), min(height, box.y2)
        left, right = max(0, box.x1), min(width, box.x2)
        image = vehicle[top:bottom, left:right].copy() if bottom > top and right > left else None

        if image is not None and image.shape[0] >= 16:
            row = split_row(image)
            top_text, _ = self._read_strip(image[:row])
            bottom_text, bottom_confidence = self._read_strip(image[row:])
            better = combine_two_line(full, top_text, bottom_text, bottom_confidence)
            if better is not None:
                text, confidence = better
        return PlateRead(text, confidence, image)
