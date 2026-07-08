# Europe Small Cap Defensive Tilt Model

This module promotes the MSCI EUR SMALL six-style factor research into a
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
5. combine subfactors with the defensive tilt:

| Subfactor | Weight |
| --- | ---: |
| Low volatility | 25% |
| Quality | 25% |
| Value | 15% |
| Momentum | 15% |
| Growth | 10% |
| Dividend | 10% |

The weights come from the official Top/Worst research package completed on
2026-07-07, where the defensive tilt was preferred for drawdown and volatility
robustness rather than raw CAGR.

## Commands

```powershell
python 15_small_cap_model/src/small_cap_model.py
python -m 02_pipelines.refresh_small_cap
python -m 02_pipelines.refresh_small_cap --inspect-only
```

