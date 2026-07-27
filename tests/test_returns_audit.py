import pandas as pd

from tp_core.returns_audit import audit_returns_extremes


def test_audit_returns_extremes_passes_when_no_values_are_flagged() -> None:
    returns = pd.DataFrame(
        {"ABC123": [0.01, -0.02]},
        index=pd.to_datetime(["2026-07-23", "2026-07-24"]),
    )

    report = audit_returns_extremes(returns)

    assert report["flagged_cells"] == 0
    assert report["governance_status"] == "passed"
    assert report["top"] == []
