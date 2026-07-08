# Europe Small Cap Raw-Gated QVM Model

This module promotes the MSCI EUR SMALL raw-gated factor research into a
production-refreshable model.

## Scope

- Universe: `Weight in MSCI EUR SMALL > 0`
- Source data: `00_screen/screen_aggregate.parquet`
- Canonical signal: `04_signals/small_cap_model_signals.parquet`
- Model output directory: `15_small_cap_model/outputs`
- Pipeline step: `python -m 02_pipelines.refresh_small_cap`

## Construction

Every raw variable is transformed so that a higher score is better:

1. direction-adjust raw values;
2. winsorize by month at 1% / 99% when enough observations exist;
3. rank by month and ICB supersector into a 0-10 percentile score;
4. average variables within each subfactor with no missing-value fill;
5. combine only subfactors whose raw variables passed the official Top/Worst
   gate:

| Subfactor | Weight |
| --- | ---: |
| Quality | 40% |
| Value | 30% |
| Momentum | 30% |

The current production default is `eu_small_validated_qvm_v1`. It comes from
the supplemental raw-gate official Top/Worst package completed on 2026-07-08:
`07_backtest_code/runs/ad_hoc/eu_small_validated_gate_20260708_official`.
LowVol is intentionally excluded because no low-volatility raw variable passed
the default raw validation gate.

## Commands

```powershell
python 15_small_cap_model/src/small_cap_model.py
python -m 02_pipelines.refresh_small_cap
python -m 02_pipelines.refresh_small_cap --inspect-only
```
