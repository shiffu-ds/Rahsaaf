"""The vehicle classes the local model is trained to recognise.

The order is the class number in every label file. Never reorder or remove an
entry once labelling has started; only add new ones at the end.
"""

CLASSES = [
    "car",
    "motorcycle",
    "rickshaw",       # three-wheeled auto rickshaw
    "qingqi",         # motorcycle rickshaw with a passenger carriage
    "van",            # Hiace, Suzuki Bolan and similar
    "bus",
    "truck",
    "pickup_loader",  # Suzuki pickup, Shehzore and other small loaders
]

#: Stock-model (COCO) class number -> our class number, for pre-labelling.
COCO_TO_LOCAL = {2: 0, 3: 1, 5: 5, 7: 6}
