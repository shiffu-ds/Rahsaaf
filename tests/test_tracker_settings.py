"""The tracker's two confidence thresholds must agree with the detector's."""
import inspect
from pathlib import Path

import yaml

from worker.detector import TRACKER_SETTINGS, VehicleTracker


def settings() -> dict:
    return yaml.safe_load(Path(TRACKER_SETTINGS).read_text())


def defaults() -> dict:
    return {
        name: p.default
        for name, p in inspect.signature(VehicleTracker.__init__).parameters.items()
        if p.default is not inspect.Parameter.empty
    }


def test_settings_file_exists_and_is_bytetrack():
    assert settings()["tracker_type"] == "bytetrack"


def test_a_weak_detection_cannot_start_a_track():
    cfg = settings()
    assert cfg["new_track_thresh"] == defaults()["confidence"]
    assert cfg["track_high_thresh"] == defaults()["confidence"]


def test_a_followed_vehicle_is_kept_at_lower_confidence():
    cfg = settings()
    assert cfg["track_low_thresh"] == defaults()["keep_confidence"]
    assert cfg["track_low_thresh"] < cfg["new_track_thresh"]
