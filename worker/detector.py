"""Vehicle detection and tracking.

Works with the stock YOLO11n weights (cars, motorcycles, buses, trucks) and
with a model trained on local footage (rickshaws, Qingqis, loaders and the
rest). The class names come from the model itself, so switching is only a
matter of passing different weights.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from ultralytics import YOLO

from worker.parking_state import Observation

#: In the stock (COCO) model only these of its 80 classes are vehicles.
COCO_VEHICLES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def vehicle_classes(model_names: dict[int, str]) -> dict[int, str]:
    """Which of a model's classes to track, and what to call them.

    The stock model knows 80 things, from people to teacups, so only its four
    vehicle classes are used. A model trained on local footage knows nothing
    but vehicles, so all of its classes are used.
    """
    is_stock = len(model_names) == 80 and model_names.get(0) == "person"
    return dict(COCO_VEHICLES) if is_stock else dict(model_names)


TRACKER_SETTINGS = str(Path(__file__).with_name("bytetrack_rahsaaf.yaml"))


class VehicleTracker:
    """Runs detection plus ByteTrack and returns one Observation per vehicle.

    ``weights`` is a ``.pt`` file or an OpenVINO folder made by
    tools/export_openvino.py. ``image_size`` is one number, or (height, width)
    for a model exported at a rectangular size; an OpenVINO model only accepts
    the size it was exported with.
    """

    def __init__(
        self,
        weights: str = "yolo11n.pt",
        image_size: int | tuple[int, int] = 416,
        confidence: float = 0.3,
        keep_confidence: float = 0.15,
    ):
        self.model = YOLO(weights, task="detect")
        self.classes = vehicle_classes(self.model.names)
        self.image_size = image_size
        #: Needed to start following a vehicle. Keep in step with
        #: new_track_thresh in bytetrack_rahsaaf.yaml.
        self.confidence = confidence
        #: Enough to keep following one that is already followed.
        self.keep_confidence = min(keep_confidence, confidence)

    def warm_up(self) -> None:
        """Run the model once on a blank picture.

        The first run of a model takes several seconds while it is compiled
        for this CPU. Doing that before the camera is opened keeps the first
        real frame from going stale while it waits.
        """
        blank = np.zeros((360, 640, 3), np.uint8)
        self.model.predict(
            blank, imgsz=self.image_size, conf=self.confidence, verbose=False
        )

    def track(self, frame: np.ndarray) -> list[Observation]:
        result = self.model.track(
            frame,
            persist=True,  # keep track IDs from one call to the next
            tracker=TRACKER_SETTINGS,
            classes=list(self.classes),
            imgsz=self.image_size,
            # The tracker applies the higher threshold to new vehicles itself.
            conf=self.keep_confidence,
            # One vehicle, one box. Without this a rickshaw the model is unsure
            # about can come back as both "rickshaw" and "car", and would be
            # reported as two violations.
            agnostic_nms=True,
            verbose=False,
        )[0]

        boxes = result.boxes
        if boxes is None or boxes.id is None:
            return []  # nothing tracked in this frame

        return [
            Observation(
                track_id=int(track_id),
                box=tuple(float(v) for v in xyxy),
                vehicle_class=self.classes.get(int(cls), "vehicle"),
                confidence=float(conf),
            )
            for track_id, xyxy, cls, conf in zip(
                boxes.id.tolist(),
                boxes.xyxy.tolist(),
                boxes.cls.tolist(),
                boxes.conf.tolist(),
            )
        ]
