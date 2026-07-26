from __future__ import annotations

import pandas as pd

from tp_experiments.artifacts import (
    MINIMAL_HOLDING_COLUMNS,
    ExperimentArtifactPolicy,
    compact_experiment_holdings,
    experiment_artifact_environment,
    experiment_plots_enabled,
    holdings_for_storage,
)


def _holdings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": ["2026-06-30", "2026-06-30"],
            "Weight": [0.6, 0.4],
            "ISIN": ["FR0000000001", "FR0000000002"],
            "Name": ["Example A", "Example B"],
            "Company SEDOL": ["0000001", "0000002"],
        }
    )


def test_default_policy_disables_plots_and_minimizes_holdings(monkeypatch) -> None:
    monkeypatch.delenv("TP_EXPERIMENT_SAVE_PLOTS", raising=False)
    monkeypatch.delenv("TP_EXPERIMENT_HOLDINGS_MODE", raising=False)

    policy = ExperimentArtifactPolicy.from_definition({})

    assert policy == ExperimentArtifactPolicy(
        save_plots=False,
        holdings_mode="minimal",
    )
    assert experiment_plots_enabled() is False
    assert tuple(holdings_for_storage(_holdings()).columns) == MINIMAL_HOLDING_COLUMNS


def test_explicit_full_policy_is_scoped_and_keeps_details(monkeypatch) -> None:
    monkeypatch.setenv("TP_EXPERIMENT_SAVE_PLOTS", "0")
    policy = ExperimentArtifactPolicy.from_definition(
        {
            "artifact_policy": {
                "save_plots": True,
                "holdings_mode": "full",
            }
        }
    )

    with experiment_artifact_environment(policy):
        assert experiment_plots_enabled() is True
        assert "Name" in holdings_for_storage(_holdings()).columns

    assert experiment_plots_enabled() is False


def test_compact_research_holdings_rewrites_nested_artifacts(tmp_path) -> None:
    target = tmp_path / "official_runs" / "smoke" / "sec_list.parquet"
    target.parent.mkdir(parents=True)
    _holdings().to_parquet(target, index=False)

    compacted = compact_experiment_holdings(
        tmp_path,
        policy=ExperimentArtifactPolicy(),
    )

    assert compacted == [target]
    stored = pd.read_parquet(target)
    assert tuple(stored.columns) == MINIMAL_HOLDING_COLUMNS
    assert stored["ISIN"].tolist() == ["FR0000000001", "FR0000000002"]
