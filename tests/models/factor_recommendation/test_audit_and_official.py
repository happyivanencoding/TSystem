from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tp_models.factor_recommendation.audit import write_audit_artifacts
from tp_models.factor_recommendation.inputs import load_research_inputs
from tp_models.factor_recommendation.sleeve_engine import OfficialSleeveAdapter, run_official_sleeve


def _screen_for_io() -> pd.DataFrame:
    dates = pd.date_range("2020-01-31", periods=3, freq="ME")
    rows = []
    for date in dates:
        rows.append(
            {
                "ISIN": "JP1",
                "Date": date,
                "Company SEDOL": "JP1",
                "Exchange Country Iso2": "JP",
                "Weight in NIKKEI": 0.5,
                "Weight in MSCI EM": 0.0,
                "Weight in SP500": 0.0,
                "Weight in STOXX EUROPE 600": 0.0,
                "Weight in MSCI WORLD": 0.5,
                "Value Avg Percentile": 6.0,
                "Size Avg Percentile": 8.0,
            }
        )
        rows.append(
            {
                "ISIN": "CN1",
                "Date": date,
                "Company SEDOL": "CN1",
                "Exchange Country Iso2": "CN",
                "Weight in NIKKEI": 0.0,
                "Weight in MSCI EM": 0.4,
                "Weight in SP500": 0.0,
                "Weight in STOXX EUROPE 600": 0.0,
                "Weight in MSCI WORLD": 0.5,
                "Value Avg Percentile": 7.0,
                "Size Avg Percentile": 2.0,
            }
        )
    return pd.DataFrame(rows).set_index("ISIN")


class _FakeOfficial:
    calls: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeOfficial.calls.append(kwargs)
        self.sec_list_historical = pd.DataFrame()

    def build_monthly_security_list(self, screen_agg_monthly=None):
        return pd.DataFrame({"Date": [screen_agg_monthly["Date"].iloc[0]], "Weight": [1.0]}), pd.DataFrame()

    def run_portfolio_nav(self, sec_list=None):
        return pd.Series([1.0]), pd.DataFrame({"weight": [1.0]})


def test_official_sleeve_uses_unique_tp_adapter_and_asia_is_not_aggregated() -> None:
    _FakeOfficial.calls = []
    adapter = OfficialSleeveAdapter(factory=_FakeOfficial)
    screen = _screen_for_io().reset_index()
    returns = pd.DataFrame({"JP1": [0.01], "CN1": [0.02]}, index=pd.to_datetime(["2020-02-03"]))
    result = run_official_sleeve(
        screen=screen,
        returns=returns,
        region="ASIA",
        factor="Value Avg Percentile",
        screen_date="2020-01-31",
        adapter=adapter,
    )
    assert result.research_only is True
    assert result.benchmark_approved is False
    assert result.nav is None
    assert len(result.component_results) == 2
    assert all(item.adapter_id == "tp_core.backtesting.OfficialPortfolioBacktest" for item in result.component_results)
    assert {call["bench"] for call in _FakeOfficial.calls} == {"NIKKEI", "MSCI EM"}


def test_inspect_writes_fixed_artifacts_and_loader_is_public(tmp_path: Path) -> None:
    screen_path = tmp_path / "screen.parquet"
    returns_path = tmp_path / "returns.parquet"
    screen = _screen_for_io()
    screen.to_parquet(screen_path)
    returns = pd.DataFrame({"JP1": [0.01, 0.02], "CN1": [0.02, 0.01]}, index=pd.to_datetime(["2020-02-03", "2020-03-03"]))
    returns.to_parquet(returns_path)
    output = tmp_path / "audit"
    paths = write_audit_artifacts(
        output_dir=output,
        screen_path=screen_path,
        returns_path=returns_path,
    )
    expected = {
        "repository_audit.json",
        "data_audit.json",
        "universe_audit.csv",
        "factor_column_audit.csv",
        "integration_map.json",
    }
    assert {Path(path).name for path in paths.values()} == expected
    data = json.loads((output / "data_audit.json").read_text(encoding="utf-8"))
    assert data["screen"]["key_columns"] == ["ISIN", "Date"]
    assert data["region_contracts"]["ASIA"]["approval_status"] == "research_only_benchmark_unapproved"
    universe = pd.read_csv(output / "universe_audit.csv")
    asia_japan = universe.loc[(universe.region == "ASIA") & (universe.component == "JAPAN")].iloc[0]
    assert asia_japan["country_allowlist"] == "JP"
    assert asia_japan["component_aggregation_weight"] == 0.5

    inputs = load_research_inputs(
        screen_path=screen_path,
        returns_path=returns_path,
        screen_columns=["Date", "Value Avg Percentile", "Size Avg Percentile"],
        return_columns=[],
    )
    assert {"screen", "returns", "universe", "factors", "model", "components"} <= set(inputs.__dict__)
    assert inputs.universe["ASIA"].production_eligible is False
