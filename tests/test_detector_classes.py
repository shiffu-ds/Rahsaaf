from training.classes import CLASSES, COCO_TO_LOCAL
from worker.detector import COCO_VEHICLES, vehicle_classes


def coco_names():
    names = {i: f"thing{i}" for i in range(80)}
    names.update({0: "person", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"})
    return names


def test_stock_model_uses_only_its_vehicle_classes():
    assert vehicle_classes(coco_names()) == COCO_VEHICLES


def test_local_model_uses_all_of_its_classes():
    local = dict(enumerate(CLASSES))
    assert vehicle_classes(local) == local
    assert "rickshaw" in vehicle_classes(local).values()


def test_prelabel_mapping_points_at_the_same_named_classes():
    for coco_id, local_id in COCO_TO_LOCAL.items():
        assert CLASSES[local_id] == COCO_VEHICLES[coco_id]
