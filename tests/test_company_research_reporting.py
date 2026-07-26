from __future__ import annotations

from pathlib import Path

from tp_reporting.company_research import (
    NarrativeDocument,
    NarrativeResponse,
    NarrativeRouter,
    build_snapshot,
    render_markdown,
    validate_narrative,
)


def _snapshot():
    return build_snapshot(
        {
            "ISIN": "FR0000000001",
            "Name": "Example SA",
            "Symbol": "EX",
            "Date": "2026-06-30",
            "Exchange Country Region": "EUROPE",
            "Supersector": "Technology",
            "Quality Score": 8.0,
        },
        {"Quality Score": 6.0},
    )


class InvalidProvider:
    provider_id = "invalid"

    def generate(self, snapshot, *, question=None, repair=None):
        return NarrativeResponse(
            provider="invalid",
            requested_model="invalid",
            actual_model="invalid",
            document=NarrativeDocument(
                title="Example SA",
                sections=[
                    {
                        "heading": "Quality",
                        "text": "Quality is 99.",
                        "claims": [{"claim": "Unsupported", "evidence_ids": ["unknown"]}],
                    }
                ],
            ),
        )


class ValidProvider:
    provider_id = "valid"

    def generate(self, snapshot, *, question=None, repair=None):
        return NarrativeResponse(
            provider="valid",
            requested_model="valid",
            actual_model="valid",
            document=NarrativeDocument(
                title="Example SA",
                sections=[
                    {
                        "heading": "Quality",
                        "text": "The deterministic quality score is 8.",
                        "claims": [
                            {
                                "claim": "Quality is above its peer median.",
                                "evidence_ids": [
                                    "company-quality-score",
                                    "peer-median-quality-score",
                                ],
                            }
                        ],
                    }
                ],
                limitations=["No forecast is inferred."],
            ),
        )


def test_snapshot_contains_deterministic_peer_delta_and_lineage() -> None:
    snapshot = _snapshot()
    facts = {fact.fact_id: fact for fact in snapshot.facts}

    assert facts["company-quality-score"].value == 8
    assert facts["peer-median-quality-score"].value == 6
    assert facts["delta-vs-peer-quality-score"].value == 2
    assert facts["delta-vs-peer-quality-score"].formula
    assert snapshot.snapshot_fingerprint


def test_router_repairs_then_falls_back_and_caches_grounded_output(tmp_path: Path) -> None:
    router = NarrativeRouter(
        InvalidProvider(),
        ValidProvider(),
        enabled=True,
        cache_root=tmp_path / "cache",
    )

    response = router.generate(_snapshot())

    assert response is not None
    assert response.provider == "valid"
    assert len(list(tmp_path.rglob("*.json"))) == 1
    assert router.generate(_snapshot()) == response


def test_deterministic_report_is_available_without_model() -> None:
    report = render_markdown(_snapshot())

    assert "Deterministic facts" in report
    assert "Deterministic-only report" in report
    assert "place trades" in report


def test_validator_accepts_only_known_facts_and_numerals() -> None:
    response = ValidProvider().generate(_snapshot())

    validate_narrative(_snapshot(), response)
