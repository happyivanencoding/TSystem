from __future__ import annotations

import json
from argparse import Namespace
from importlib import import_module
from pathlib import Path

import pandas as pd

from tp_core.supplemental_data import (
    build_shadow_sidecar,
    coverage_by_market_field_year,
    materialize_point_in_time,
    normalize_records,
    provider_acceptance_gate,
    validate_resolved_values,
)
from tp_data.providers import (
    AlphaVantageEstimatesProvider,
    DbnomicsSeriesProvider,
    EsefFilingsProvider,
    FredProvider,
    HttpClient,
    ProviderBatch,
    SdmxCsvProvider,
    SecCompanyFactsProvider,
)


refresh = import_module("tp_pipelines.refresh_supplemental_data")
run_all_module = import_module("tp_pipelines.run_all")


def _fundamental_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ISIN": "US1",
                "period_end": "2025-12-31",
                "available_at": "2026-01-15",
                "source": "sec_companyfacts",
                "field": "revenue_reported",
                "value": 90.0,
                "retrieved_at": "2026-03-01",
                "unit": "USD",
                "currency": "USD",
                "availability_method": "filing_date",
            },
            {
                "ISIN": "US1",
                "period_end": "2025-12-31",
                "available_at": "2026-02-05",
                "source": "factset_manual",
                "field": "revenue_reported",
                "value": 100.0,
                "retrieved_at": "2026-02-05",
                "unit": "USD",
                "currency": "USD",
                "availability_method": "manual_refresh",
            },
        ]
    )


def test_point_in_time_uses_available_source_priority_without_lookahead() -> None:
    resolved = materialize_point_in_time(
        _fundamental_rows(),
        "fundamental",
        [pd.Timestamp("2026-01-31"), pd.Timestamp("2026-02-28")],
        {"*": ["factset_manual", "sec_companyfacts"]},
    )

    january = resolved.loc[resolved["Date"].eq(pd.Timestamp("2026-01-31"))].iloc[0]
    february = resolved.loc[resolved["Date"].eq(pd.Timestamp("2026-02-28"))].iloc[0]
    assert january["resolved_source"] == "sec_companyfacts"
    assert january["resolved_value"] == 90.0
    assert february["resolved_source"] == "factset_manual"
    assert february["resolved_value"] == 100.0
    assert validate_resolved_values(resolved, "ISIN")["ok"]


def test_shadow_sidecar_keeps_manual_value_and_flags_conflict() -> None:
    screen = pd.DataFrame(
        {
            "ISIN": ["US1"],
            "Date": ["2026-01-31"],
            "Sales": [100.0],
        }
    )
    resolved = materialize_point_in_time(
        _fundamental_rows().iloc[[0]],
        "fundamental",
        [pd.Timestamp("2026-01-31")],
    )
    sidecar = build_shadow_sidecar(
        screen,
        resolved,
        {
            "revenue_reported": {
                "family": "fundamental",
                "reference_screen_column": "Sales",
                "promote_to_screen_column": "Sales",
                "tolerance": 0.01,
            }
        },
    )

    assert sidecar["selected_value"].item() == 100.0
    assert sidecar["selected_source"].item() == "canonical_manual"
    assert bool(sidecar["conflict"].item())


def test_normalize_excludes_unknown_available_time() -> None:
    rows = _fundamental_rows()
    rows.loc[0, "available_at"] = None

    normalized = normalize_records(rows, "fundamental")

    assert len(normalized) == 1
    assert normalized["source"].item() == "factset_manual"


def test_coverage_and_provider_gate_use_percentage_point_uplift() -> None:
    screen = pd.DataFrame(
        {
            "ISIN": ["A", "B"],
            "Date": pd.to_datetime(["2026-01-31", "2026-01-31"]),
            "Weight in SP500": [0.5, 0.5],
            "Sales": [10.0, None],
        }
    )
    sidecar = pd.DataFrame(
        {
            "ISIN": ["A", "B"],
            "Date": pd.to_datetime(["2026-01-31", "2026-01-31"]),
            "field": ["revenue_reported", "revenue_reported"],
            "manual_value": [10.0, None],
            "auto_value": [10.0, 20.0],
            "auto_source": ["candidate_api", "candidate_api"],
            "valid_auto": [True, True],
            "conflict": [False, False],
        }
    )
    mappings = {
        "revenue_reported": {
            "reference_screen_column": "Sales",
            "family": "fundamental",
        }
    }

    coverage = coverage_by_market_field_year(
        screen,
        sidecar,
        mappings,
        source="candidate_api",
    )
    gate = provider_acceptance_gate(coverage, sidecar, "candidate_api")

    all_years = coverage.loc[coverage["year"].eq("ALL")].iloc[0]
    assert all_years["baseline_coverage"] == 0.5
    assert all_years["shadow_coverage"] == 1.0
    assert gate["coverage_uplift"] == 0.5
    assert gate["consistency"] == 1.0
    assert gate["passed"]


def test_coverage_handles_macro_only_run_without_security_sidecar() -> None:
    screen = pd.DataFrame(
        {
            "ISIN": ["A"],
            "Date": pd.to_datetime(["2026-01-31"]),
            "Weight in SP500": [1.0],
            "Sales": [10.0],
        }
    )

    coverage = coverage_by_market_field_year(
        screen,
        pd.DataFrame(),
        {
            "revenue_reported": {
                "reference_screen_column": "Sales",
                "family": "fundamental",
            }
        },
    )

    all_years = coverage.loc[coverage["year"].eq("ALL")].iloc[0]
    assert all_years["baseline_coverage"] == 1.0
    assert all_years["shadow_coverage"] == 1.0
    assert all_years["coverage_uplift"] == 0.0


def test_payload_hash_makes_partition_write_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(refresh, "SUPPLEMENTAL_RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(refresh, "SUPPLEMENTAL_NORMALIZED_DIR", tmp_path / "normalized")
    batch = ProviderBatch(
        family="fundamental",
        source="sec_companyfacts",
        job_key="US1:1",
        records=_fundamental_rows().iloc[[0]],
        raw_payload={"same": "payload"},
    )

    first = refresh._persist_batch(batch)
    second = refresh._persist_batch(batch)

    assert first["normalized_path"] == second["normalized_path"]
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 1
    assert len(list((tmp_path / "normalized").rglob("*.parquet"))) == 1


def test_job_key_ignores_nullable_identifiers() -> None:
    key = refresh._job_key(
        "esef",
        {
            "ISIN": "EU1",
            "CIK": pd.NA,
            "LEI": "LEI123",
            "AlphaSymbol": pd.NA,
        },
    )

    assert key == "EU1:LEI123"


def test_fred_adapter_preserves_source_vintage() -> None:
    class FakeClient(HttpClient):
        def __init__(self) -> None:
            pass

        def get_json(self, url, *, params=None, headers=None):
            assert params["output_type"] == 2
            return {
                "units": "lin",
                "observations": [
                    {
                        "date": "2025-12-01",
                        "realtime_start": "2026-01-10",
                        "realtime_end": "2026-02-01",
                        "value": "123.4",
                    }
                ],
            }

    batch = FredProvider(FakeClient()).fetch(
        {"series_id": "TEST", "field": "TEST_FIELD", "unit": "index"},
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2026-02-28"),
        retrieved_at=pd.Timestamp("2026-03-01"),
        api_key="x" * 32,
    )

    assert batch.family == "macro"
    assert batch.records["available_at"].item() == pd.Timestamp("2026-01-10")
    assert batch.records["availability_method"].item() == "source_vintage"


def test_macro_materialization_does_not_select_future_forecast() -> None:
    records = pd.DataFrame(
        [
            {
                "series_id": "IMF:GDP:USA",
                "observation_date": "2024-12-31",
                "vintage_at": "2025-05-15",
                "available_at": "2025-05-15",
                "retrieved_at": "2025-05-15",
                "source": "dbnomics",
                "field": "GDP_GROWTH:USA",
                "value": 2.8,
                "unit": "percent",
                "availability_method": "dbnomics_dataset_indexed_at",
            },
            {
                "series_id": "IMF:GDP:USA",
                "observation_date": "2030-12-31",
                "vintage_at": "2025-05-15",
                "available_at": "2025-05-15",
                "retrieved_at": "2025-05-15",
                "source": "dbnomics",
                "field": "GDP_GROWTH:USA",
                "value": 2.1,
                "unit": "percent",
                "availability_method": "dbnomics_dataset_indexed_at",
            },
        ]
    )

    resolved = materialize_point_in_time(
        records,
        "macro",
        [pd.Timestamp("2025-06-30")],
    )

    assert resolved["resolved_value"].item() == 2.8
    assert resolved["observed_at"].item() == pd.Timestamp("2024-12-31")
    assert validate_resolved_values(resolved, "series_id")["ok"]


def test_dbnomics_fallback_keeps_original_imf_identity() -> None:
    class FakeClient(HttpClient):
        def __init__(self) -> None:
            pass

        def get_json(self, url, *, params=None, headers=None):
            return {
                "dataset": {"indexed_at": "2025-05-15T11:13:27Z"},
                "series": {
                    "docs": [
                        {
                            "period": ["2024", "2025"],
                            "value": [2.8, 1.8],
                        }
                    ]
                },
            }

    batch = DbnomicsSeriesProvider(FakeClient()).fetch(
        {
            "provider_code": "IMF",
            "dataset_code": "WEO:2025-04",
            "indicator": "NGDP_RPCH",
            "countries": ["USA"],
            "field_prefix": "IMF_REAL_GDP_GROWTH",
            "unit": "percent",
        },
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2026-12-31"),
        retrieved_at=pd.Timestamp("2026-03-01"),
        original_provider="IMF",
    )

    assert batch.source == "dbnomics"
    assert set(batch.records["series_id"]) == {"IMF:NGDP_RPCH:USA"}
    assert set(batch.records["availability_method"]) == {
        "dbnomics_dataset_indexed_at"
    }


def test_sec_adapter_uses_filing_date_and_currency() -> None:
    class FakeClient(HttpClient):
        def __init__(self) -> None:
            pass

        def get_json(self, url, *, params=None, headers=None):
            return {
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "units": {
                                "USD": [
                                    {
                                        "end": "2025-12-31",
                                        "filed": "2026-02-01",
                                        "val": 100000000,
                                        "form": "10-K",
                                        "fp": "FY",
                                        "accn": "1",
                                    }
                                ]
                            }
                        }
                    }
                }
            }

    batch = SecCompanyFactsProvider(FakeClient()).fetch(
        {"ISIN": "US1", "CIK": "123", "Currency": "USD"},
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2026-12-31"),
        retrieved_at=pd.Timestamp("2026-03-01"),
        concepts=[
            {
                "taxonomy": "us-gaap",
                "concept": "Revenues",
                "field": "revenue_reported",
            }
        ],
    )

    assert batch.records["available_at"].item() == pd.Timestamp("2026-02-01")
    assert batch.records["currency"].item() == "USD"
    assert batch.records["value"].item() == 100000000


def test_sdmx_adapter_uses_valid_from_and_month_end() -> None:
    class FakeClient(HttpClient):
        def __init__(self) -> None:
            pass

        def get_text(self, url, *, params=None, headers=None):
            return (
                "TIME_PERIOD,OBS_VALUE,VALID_FROM,UNIT\n"
                "2025-01,2.5,2025-02-24T11:00:00+01:00,PCCH\n"
            )

    batch = SdmxCsvProvider("ecb", FakeClient()).fetch(
        {
            "url": "https://official.example/data",
            "series_id": "ECB:TEST",
            "field": "EU_TEST",
            "available_column": "VALID_FROM",
            "unit": "percent",
        },
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2026-12-31"),
        retrieved_at=pd.Timestamp("2026-03-01"),
    )

    assert batch.records["observation_date"].item() == pd.Timestamp("2025-01-31")
    assert batch.records["available_at"].item() == pd.Timestamp("2025-02-24 11:00:00")
    assert batch.records["availability_method"].item() == "source_update"


def test_esef_adapter_uses_repository_addition_as_conservative_availability() -> None:
    class FakeClient(HttpClient):
        def __init__(self) -> None:
            pass

        def get_json(self, url, *, params=None, headers=None):
            if "/api/entities/" in url:
                return {
                    "data": [
                        {
                            "id": "1",
                            "attributes": {
                                "period_end": "2025-12-31",
                                "date_added": "2026-03-01",
                                "json_url": "/filing.json",
                            },
                        }
                    ]
                }
            return {
                "facts": {
                    "f1": {
                        "value": "25000000",
                        "dimensions": {
                            "concept": "ifrs-full:Revenue",
                            "entity": "lei:LEI1",
                            "period": "2025-01-01T00:00:00/2026-01-01T00:00:00",
                            "unit": "iso4217:EUR",
                        },
                    }
                }
            }

    batch = EsefFilingsProvider(FakeClient()).fetch(
        {"ISIN": "EU1", "LEI": "LEI1", "Currency": "EUR"},
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2026-12-31"),
        retrieved_at=pd.Timestamp("2026-03-02"),
        concepts=[{"concept": "ifrs-full:Revenue", "field": "revenue_reported"}],
    )

    assert batch.records["period_end"].item() == pd.Timestamp("2025-12-31")
    assert batch.records["available_at"].item() == pd.Timestamp("2026-03-01")
    assert batch.records["currency"].item() == "EUR"


def test_alpha_estimates_are_collection_snapshots_not_fabricated_history() -> None:
    class FakeClient(HttpClient):
        def __init__(self) -> None:
            pass

        def get_json(self, url, *, params=None, headers=None):
            return {
                "symbol": "ABC",
                "estimates": [
                    {
                        "date": "2026-12-31",
                        "horizon": "annual",
                        "eps_estimate_average": "5.25",
                        "eps_estimate_analyst_count": "12",
                    }
                ],
            }

    batch = AlphaVantageEstimatesProvider(FakeClient()).fetch(
        {"ISIN": "US1", "AlphaSymbol": "ABC", "Currency": "USD"},
        retrieved_at=pd.Timestamp("2026-03-01 12:00:00"),
        api_key="key",
        field_map={"eps_estimate_average": "eps_estimate_average"},
    )

    assert batch.records["estimate_as_of"].item() == pd.Timestamp("2026-03-01")
    assert batch.records["available_at"].item() == pd.Timestamp("2026-03-01 12:00:00")
    assert batch.records["availability_method"].item() == "retrieval_snapshot"
    assert batch.records["currency"].item() == "USD"


def test_promotion_requires_three_periods_and_only_fills_nulls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    qa_dir = tmp_path / "qa"
    status_dir = qa_dir / "period_status"
    status_dir.mkdir(parents=True)
    config_hash = "same-config"
    for period in ("2026-01", "2026-02", "2026-03"):
        (status_dir / f"{period.replace('-', '')}.json").write_text(
            json.dumps(
                {
                    "period": period,
                    "passed": True,
                    "config_hash": config_hash,
                    "provider_gates": [
                        {"source": "sec_companyfacts", "passed": True}
                    ],
                }
            ),
            encoding="utf-8",
        )

    screen_path = tmp_path / "screen.parquet"
    pd.DataFrame(
        {
            "ISIN": ["A", "B"],
            "Date": pd.to_datetime(["2026-03-31", "2026-03-31"]),
            "Company SEDOL": ["1", "2"],
            "Sales": [10.0, None],
        }
    ).set_index("ISIN").to_parquet(screen_path, index=True)
    sidecar = pd.DataFrame(
        {
            "ISIN": ["A", "B"],
            "Date": pd.to_datetime(["2026-03-31", "2026-03-31"]),
            "field": ["revenue_reported", "revenue_reported"],
            "auto_value": [99.0, 20.0],
            "auto_source": ["sec_companyfacts", "sec_companyfacts"],
            "valid_auto": [True, True],
        }
    )
    mappings = {
        "revenue_reported": {
            "promote_enabled": True,
            "promote_to_screen_column": "Sales",
        }
    }
    monkeypatch.setattr(refresh, "SUPPLEMENTAL_QA_DIR", qa_dir)
    monkeypatch.setattr(refresh, "SCREEN_AGGREGATE_PATH", screen_path)

    result = refresh._promote_to_canonical(
        sidecar,
        mappings,
        config_hash=config_hash,
        required_periods=3,
    )

    promoted = pd.read_parquet(screen_path)
    assert promoted.index.name == "ISIN"
    assert promoted.loc["A", "Sales"] == 10.0
    assert promoted.loc["B", "Sales"] == 20.0
    assert result["promoted_cells"] == {"Sales": 1}


def test_run_all_calls_supplemental_stage_only_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    orchestration = import_module("tp_pipelines.orchestration")
    calls: list[Namespace] = []

    class FakeManifest:
        def __init__(self, step: str, parameters: dict[str, object]) -> None:
            self.details: dict[str, object] = {}
            self.validations: list[dict[str, object]] = []

        def add_validation(self, name, ok, message="", details=None):
            self.validations.append({"name": name, "ok": ok})

        def write(self, status: str, *, error=None) -> Path:
            return tmp_path / "run_all_manifest.json"

    def fake_refresh(args: Namespace) -> Path:
        calls.append(args)
        return tmp_path / "refresh_supplemental_manifest.json"

    monkeypatch.setattr(run_all_module, "StepManifest", FakeManifest)
    monkeypatch.setattr(orchestration, "run_refresh_supplemental_data", fake_refresh)
    args = run_all_module.build_parser().parse_args(
        [
            "--skip-refresh-data",
            "--refresh-supplemental-data",
            "--supplemental-source",
            "fred",
            "--supplemental-dry-run",
            "--skip-refresh-technical",
            "--skip-export-signals",
            "--skip-refresh-small-cap",
            "--skip-build-candidates",
            "--skip-optimize-portfolio",
            "--skip-backtest",
            "--skip-report",
            "--experiment-root",
            str(tmp_path / "experiments"),
        ]
    )

    run_all_module.run_all(args)

    assert len(calls) == 1
    assert calls[0].source == ["fred"]
    assert calls[0].dry_run is True
    assert calls[0].promote_to_canonical is False
    experiment_records = list((tmp_path / "experiments").rglob("run.json"))
    assert len(experiment_records) == 1
    experiment = json.loads(experiment_records[0].read_text(encoding="utf-8"))
    assert experiment["run"]["status"] == "success"
    assert experiment["hypothesis"]["hypothesis_id"] == "production-pipeline"
    assert "child_manifest_001" in experiment["artifacts"]
