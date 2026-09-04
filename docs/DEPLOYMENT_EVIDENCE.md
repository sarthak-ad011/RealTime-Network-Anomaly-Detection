# Deployment evidence — captured 2026-09-04 11:13:03Z

## Model results (full CIC-IDS2017, 565,553-row held-out test split, 19.7% attacks)

| model | AUC-PR | AUC-ROC | precision | recall | F1 |
|---|---|---|---|---|---|
| LSTM autoencoder (champion) | 0.6319 | 0.7727 | 0.9918 | 0.2528 | 0.4029 |
| Isolation Forest (baseline) | 0.3357 | 0.6633 | 0.0592 | 0.0030 | 0.0057 |
| LSTM 4-epoch (challenger)   | 0.5882 | 0.7039 | 0.9876 | 0.2489 | 0.3976 |

## Canary analysis — PASSED (AnalysisRun anomaly-inference-578f4b756-6-2)
```
phase: Successful
  p99-latency        phase=Successful successful=4
    measurements: ['[0.00495]', '[0.00495]', '[0.00495]', '[0.00495]']
  anomaly-flag-rate  phase=Successful successful=4
    measurements: ['[0.06598984771573604]', '[0.06490872210953347]', '[0.05583756345177665]', '[0.05679513184584179]']
```

## Promotion gate — challenger correctly REJECTED
```
champion  v1: auc_pr=0.6319 recall=0.2528 f1=0.4029
candidate v2: auc_pr=0.5882 recall=0.2489 f1=0.3976

PROMOTE: False  (AUC-PR insufficient: 0.5882 vs 0.6319)
candidate rejected; champion retained
```

## Drift detection — negative control (no drift on in-distribution traffic)
```
2026-09-04 11:09:12.437 | INFO     | __main__:load_recent:60 - loaded 20000 recent predictions from 20000 objects
2026-09-04 11:09:15.490 | INFO     | __main__:main:97 - drift summary: {'number_of_columns': 15, 'number_of_drifted_columns': 4, 'share_of_drifted_columns': 0.26666666666666666, 'dataset_drift': False}
2026-09-04 11:09:15.490 | INFO     | __main__:main:106 - no significant drift
```

## Rollout
```
Name:            anomaly-inference
Namespace:       mlops
Status:          ✔ Healthy
Strategy:        Canary
  Step:          8/8
  SetWeight:     100
  ActualWeight:  100
Images:          170420138680.dkr.ecr.ap-south-1.amazonaws.com/anomaly-mlops:553ec6c (stable)
Replicas:
  Desired:       4
  Current:       4
  Updated:       4
  Ready:         4
  Available:     4
```

## Argo CD
```
NAME            SYNC STATUS   HEALTH STATUS
anomaly-mlops   Synced        Healthy
```

## Analysis run history (Errors were config faults, later fixed; final run Successful)
```
NAME                                 STATUS       AGE
anomaly-inference-64cf87bf6b-4-2     Error        121m
anomaly-inference-757d6b6cc8-5-2     Error        41m
anomaly-inference-757d6b6cc8-5-2.1   Error        33m
anomaly-inference-757d6b6cc8-5-2.2   Error        29m
anomaly-inference-578f4b756-6-2      Successful   13m
```

## Pods
```
NAME                                READY   STATUS      RESTARTS   AGE
anomaly-inference-578f4b756-5wkt6   1/1     Running     0          16m
anomaly-inference-578f4b756-fct2k   1/1     Running     0          6m21s
anomaly-inference-578f4b756-ms8pg   1/1     Running     0          8m34s
anomaly-inference-578f4b756-xclsc   1/1     Running     0          8m34s
drift-check-sk7t7                   0/1     Completed   0          4m41s
loadgen-79c595cc4-2ktn8             1/1     Running     0          3m10s
mlflow-d49f7c57f-lb8vs              1/1     Running     0          128m
promotion-gate-6p97l                0/1     Completed   0          2m7s
```
