"""Versioned GLM-5.1 news sentiment/event features for shadow research only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tp_core.workspace import RESEARCH_FEATURES_DIR
from tp_data.providers import NewsStandardModel

FEATURE_SET_ID = "glm51_news_sentiment_event_v1"
PROMPT_VERSION = "news_feature_extraction_v1"
FEATURE_SCHEMA_VERSION = 1
CONTROLLED_EVENT_TYPES = {
    "central_bank",
    "earnings",
    "fiscal_policy",
    "geopolitics",
    "inflation",
    "labor",
    "market_stress",
    "merger_acquisition",
    "regulation",
    "technology",
    "other",
    "none",
}


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class NewsFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentiment_label: Literal["negative", "neutral", "positive"]
    sentiment_score: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    event_type: str
    impact_horizon: Literal["intraday", "days", "weeks", "months", "unclear"]
    affected_regions: list[str] = Field(default_factory=list)
    affected_sectors: list[str] = Field(default_factory=list)
    affected_entities: list[str] = Field(default_factory=list)
    uncertainty: float = Field(ge=0, le=1)
    evidence_spans: list[str] = Field(default_factory=list)
    no_signal: bool = False

    @model_validator(mode="after")
    def validate_controlled_values(self):
        if self.event_type not in CONTROLLED_EVENT_TYPES:
            raise ValueError(f"event_type 不在受控词表：{self.event_type}")
        if self.no_signal and self.event_type != "none":
            raise ValueError("no_signal=true 时 event_type 必须为 none")
        return self


@dataclass(frozen=True)
class GlmClientConfig:
    base_url: str
    api_key: str
    model: str = "glm-5.1"
    timeout_seconds: int = 60
    retries: int = 3

    @classmethod
    def from_environment(cls) -> "GlmClientConfig":
        model = os.environ.get("AI_MODEL", "glm-5.1").strip()
        if model != "glm-5.1":
            raise ValueError("新闻特征固定使用 AI_MODEL=glm-5.1")
        return cls(
            base_url=os.environ.get("AI_BASE_URL", "").strip(),
            api_key=os.environ.get("AI_API_KEY", "").strip(),
            model=model,
        )


class FeatureClient(Protocol):
    model: str

    def complete_json(self, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]: ...


class Glm51Client:
    def __init__(self, config: GlmClientConfig):
        if not config.base_url or not config.api_key:
            raise ValueError("AI_BASE_URL 和 AI_API_KEY 必须配置")
        if config.model != "glm-5.1":
            raise ValueError("Glm51Client 只允许 model=glm-5.1")
        self.config = config
        self.model = config.model

    def _url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        request = Request(
            self._url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        last_error: BaseException | None = None
        for attempt in range(self.config.retries):
            try:
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    result = json.loads(response.read().decode("utf-8"))
                content = result["choices"][0]["message"]["content"]
                if isinstance(content, str):
                    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
                    parsed = json.loads(content)
                else:
                    parsed = content
                metadata = {
                    "request_id": result.get("id"),
                    "actual_model": result.get("model") or self.model,
                    "usage": result.get("usage"),
                }
                return parsed, metadata
            except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError) as error:
                last_error = error
                if attempt + 1 < self.config.retries:
                    time.sleep(min(2**attempt, 8))
        raise RuntimeError("GLM-5.1 JSON 请求失败") from last_error


SENSITIVE_LINE = re.compile(
    r"(?im)^.*\b(?:customer|client|user|watchlist|holding|portfolio position|账户|客户|持仓|观察名单)\b.*$"
)
WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:\\[^\s<>\"']+")
LOCAL_LINK = re.compile(r"(?i)(?:file|chrome-extension)://\S+")


def sanitize_news(record: NewsStandardModel, *, max_characters: int = 12_000) -> dict[str, Any]:
    """Return the only fields permitted to leave TP for feature extraction."""

    if record.privacy_level != "public_internal":
        raise ValueError("仅允许发送 privacy_level=public_internal 的新闻")
    title = WINDOWS_PATH.sub("[removed-path]", record.title)
    text = WINDOWS_PATH.sub("[removed-path]", record.text)
    text = LOCAL_LINK.sub("", text)
    text = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^]]+)\]\]", r"\1", text)
    text = SENSITIVE_LINE.sub("[removed-private-line]", text)
    return {
        "record_id": record.record_id,
        "title": title[:500],
        "text": text[:max_characters],
        "source_url": record.source_url,
        "observed_at": record.observation_date.isoformat(),
        "available_at": record.available_at.isoformat(),
        "region": record.region,
        "subject": record.subject,
        "privacy_level": "public_internal",
    }


SYSTEM_PROMPT = """You extract auditable market news features.
Return one JSON object matching the requested schema. Use only the supplied article.
Sentiment is expected market impact, not prose tone. If evidence is insufficient,
set no_signal=true, event_type="none", neutral sentiment and low confidence.
Every evidence_spans item must be copied exactly from the supplied title or text.
Do not infer entities, regions, sectors, dates, or numbers absent from the input."""


def _user_prompt(news: dict[str, Any], *, repair: str | None = None) -> str:
    schema = NewsFeature.model_json_schema()
    prompt = (
        f"prompt_version={PROMPT_VERSION}\n"
        f"schema_version={FEATURE_SCHEMA_VERSION}\n"
        f"controlled_event_types={sorted(CONTROLLED_EVENT_TYPES)}\n"
        f"schema={json.dumps(schema, ensure_ascii=False)}\n"
        f"news={json.dumps(news, ensure_ascii=False)}"
    )
    if repair:
        prompt += f"\nPrevious output was invalid: {repair}\nReturn corrected JSON only."
    return prompt


def _validate_grounding(feature: NewsFeature, news: dict[str, Any]) -> None:
    corpus = f"{news['title']}\n{news['text']}"
    missing_spans = [span for span in feature.evidence_spans if span not in corpus]
    missing_entities = [
        entity
        for entity in feature.affected_entities
        if entity.casefold() not in corpus.casefold()
    ]
    if missing_spans or missing_entities:
        raise ValueError(
            f"输出未被输入支撑：spans={missing_spans[:3]}, entities={missing_entities[:3]}"
        )


class Glm51NewsFeatureExtractor:
    def __init__(
        self,
        client: FeatureClient,
        *,
        root: str | Path = RESEARCH_FEATURES_DIR / "news" / FEATURE_SET_ID,
        repeat_rate: float = 0.1,
    ):
        self.client = client
        self.root = Path(root)
        self.repeat_rate = repeat_rate

    def _extract_once(self, news: dict[str, Any]) -> tuple[NewsFeature, dict[str, Any]]:
        repair = None
        for _attempt in range(2):
            raw, metadata = self.client.complete_json(
                SYSTEM_PROMPT,
                _user_prompt(news, repair=repair),
            )
            try:
                feature = NewsFeature.model_validate(raw)
                _validate_grounding(feature, news)
                return feature, metadata
            except (ValidationError, ValueError) as error:
                repair = str(error)
        raise ValueError(f"GLM-5.1 输出在一次修复后仍无效：{repair}")

    def extract(self, record: NewsStandardModel, *, market: str = "UNMAPPED") -> dict[str, Any]:
        news = sanitize_news(record)
        cache_key = _digest(
            {
                "news": news,
                "model": self.client.model,
                "feature_set": FEATURE_SET_ID,
                "prompt": PROMPT_VERSION,
                "schema": FEATURE_SCHEMA_VERSION,
            }
        )
        year = record.observation_date.year
        target = self.root / f"market={market}" / f"year={year}" / f"{cache_key}.json"
        if target.is_file():
            return json.loads(target.read_text(encoding="utf-8"))
        started = time.perf_counter()
        feature, metadata = self._extract_once(news)
        payload: dict[str, Any] = {
            "feature_set_id": FEATURE_SET_ID,
            "prompt_version": PROMPT_VERSION,
            "schema_version": FEATURE_SCHEMA_VERSION,
            "status": "research_only",
            "cache_key": cache_key,
            "input_sha256": _digest(news),
            "request_sha256": _digest(_user_prompt(news)),
            "model": self.client.model,
            "record_id": record.record_id,
            "observed_at": record.observation_date.isoformat(),
            "available_at": record.available_at.isoformat(),
            "feature": feature.model_dump(),
            "provider_metadata": metadata,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        repeat_selected = int(cache_key[:8], 16) / 0xFFFFFFFF < self.repeat_rate
        if repeat_selected:
            repeated, repeat_metadata = self._extract_once(news)
            payload["repeat"] = {
                "feature": repeated.model_dump(),
                "provider_metadata": repeat_metadata,
            }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if target.exists():
            temporary.unlink()
            return json.loads(target.read_text(encoding="utf-8"))
        os.replace(temporary, target)
        return payload


def evaluate_repeat_stability(records: list[dict[str, Any]]) -> dict[str, Any]:
    repeated = [record for record in records if record.get("repeat")]
    if not repeated:
        return {"status": "insufficient", "repeat_count": 0}
    agreements = []
    score_errors = []
    for record in repeated:
        first = record["feature"]
        second = record["repeat"]["feature"]
        agreements.append(first["sentiment_label"] == second["sentiment_label"])
        score_errors.append(abs(first["sentiment_score"] - second["sentiment_score"]))
    agreement = sum(agreements) / len(agreements)
    mae = sum(score_errors) / len(score_errors)
    stable = agreement >= 0.9 and mae <= 0.15
    return {
        "status": "stable" if stable else "unstable_research_only",
        "repeat_count": len(repeated),
        "label_agreement": agreement,
        "score_mae": mae,
        "thresholds": {"label_agreement": 0.9, "score_mae": 0.15},
    }


__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "FEATURE_SET_ID",
    "PROMPT_VERSION",
    "Glm51Client",
    "Glm51NewsFeatureExtractor",
    "GlmClientConfig",
    "NewsFeature",
    "evaluate_repeat_stability",
    "sanitize_news",
]
