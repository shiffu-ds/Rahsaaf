# Model report

- Model: `models/local.pt`
- Data: `data/dataset_hetero_big/split/dataset.yaml`, `test` set
- Date: 2026-11-15
- Overall mAP@50: **0.714**
- Overall precision: 0.778, recall: 0.641

| Class | Vehicles in test set | Precision | Recall | mAP@50 |
|---|---|---|---|---|
| car | 746 | 0.828 | 0.761 | 0.841 |
| motorcycle | 332 | 0.773 | 0.584 | 0.679 |
| rickshaw | 658 | 0.813 | 0.751 | 0.824 |
| van | 101 | 0.680 | 0.485 | 0.550 |
| bus | 342 | 0.883 | 0.708 | 0.819 |
| truck | 182 | 0.784 | 0.643 | 0.714 |
| pickup_loader | 88 | 0.688 | 0.557 | 0.573 |

Not measured (no examples in this set): qingqi.
