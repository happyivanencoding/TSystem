from __future__ import annotations

from datetime import datetime, timezone

from tp_data.providers import NewsStandardModel
from tp_models.news.glm51_features import (
    Glm51NewsFeatureExtractor,
    NewsFeature,
    evaluate_repeat_stability,
    sanitize_news,
)


def _record(text: str = "The Federal Reserve held rates unchanged.") -> NewsStandardModel:
    timestamp = datetime(2026, 7, 1, tzinfo=timezone.utc)
    return NewsStandardModel(
        source="okf_card_box",
        field="news_text",
        value="Fed decision",
        available_at=timestamp,
        retrieved_at=timestamp,
        unit="text",
        record_id="record-1",
        title="Fed decision",
        text=text,
        observation_date=timestamp,
        captured_at=timestamp,
        privacy_level="public_internal",
        content_sha256="a" * 64,
    )


class FakeClient:
    model = "glm-5.1"

    def complete_json(self, system_prompt, user_prompt):
        return (
            {
                "sentiment_label": "neutral",
                "sentiment_score": 0.0,
                "confidence": 0.8,
                "event_type": "central_bank",
                "impact_horizon": "days",
                "affected_regions": [],
                "affected_sectors": [],
                "affected_entities": ["Federal Reserve"],
                "uncertainty": 0.2,
                "evidence_spans": ["Federal Reserve held rates unchanged"],
                "no_signal": False,
            },
            {"request_id": "fake-1", "actual_model": "glm-5.1"},
        )


def test_sanitizer_removes_local_and_private_context() -> None:
    record = _record(
        "Source C:\\GoogleDrive\\private\\news.md\n"
        "Customer watchlist: SECRET\n"
        "[[Fed|Federal Reserve]] held rates unchanged."
    )

    sanitized = sanitize_news(record)

    assert "C:\\GoogleDrive" not in sanitized["text"]
    assert "SECRET" not in sanitized["text"]
    assert "Federal Reserve" in sanitized["text"]
    assert set(sanitized) == {
        "record_id",
        "title",
        "text",
        "source_url",
        "observed_at",
        "available_at",
        "region",
        "subject",
        "privacy_level",
    }


def test_extractor_validates_grounding_and_writes_append_only_cache(tmp_path) -> None:
    extractor = Glm51NewsFeatureExtractor(
        FakeClient(),
        root=tmp_path / "features",
        repeat_rate=0,
    )

    first = extractor.extract(_record(), market="US")
    second = extractor.extract(_record(), market="US")

    assert first == second
    assert first["status"] == "research_only"
    assert first["model"] == "glm-5.1"
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_repeat_stability_gate_marks_drift_as_research_only() -> None:
    result = evaluate_repeat_stability(
        [
            {
                "feature": {"sentiment_label": "positive", "sentiment_score": 0.8},
                "repeat": {
                    "feature": {"sentiment_label": "negative", "sentiment_score": -0.5}
                },
            }
        ]
    )

    assert result["status"] == "unstable_research_only"


def test_no_signal_requires_none_event_type() -> None:
    feature = NewsFeature(
        sentiment_label="neutral",
        sentiment_score=0,
        confidence=0.1,
        event_type="none",
        impact_horizon="unclear",
        uncertainty=0.9,
        no_signal=True,
    )

    assert feature.no_signal is True
