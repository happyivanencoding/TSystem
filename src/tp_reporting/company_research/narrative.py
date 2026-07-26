"""Grounded narrative routing: free local router first, GLM-5.1 fallback."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Protocol

from pydantic import ValidationError

from tp_core.workspace import REPORTS_DIR
from tp_models.news.glm51_features import Glm51Client, GlmClientConfig

from .models import (
    CompanyResearchSnapshot,
    NarrativeDocument,
    NarrativeResponse,
)

NARRATIVE_PROMPT_VERSION = "company_grounded_narrative_v1"
MODEL_NUMERAL = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?")

SYSTEM_INSTRUCTION = """You are a read-only company research narrator.
Use only the supplied deterministic snapshot. Return JSON matching the schema.
Every claim must cite one or more exact fact_id or evidence_id values.
Do not introduce any numeral not present as a deterministic fact, identity, or date.
Do not claim access to files, tools, portfolios, orders, customers, or private data.
If evidence is insufficient, state the limitation instead of inferring."""


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _content_json(value: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", value.strip())
    return json.loads(cleaned)


def _prompt(
    snapshot: CompanyResearchSnapshot,
    *,
    question: str | None,
    repair: str | None,
) -> str:
    payload = {
        "prompt_version": NARRATIVE_PROMPT_VERSION,
        "instruction": SYSTEM_INSTRUCTION,
        "question": question,
        "schema": NarrativeDocument.model_json_schema(),
        "snapshot": snapshot.public_payload(),
    }
    text = json.dumps(payload, ensure_ascii=False)
    if repair:
        text += f"\nPrevious response was invalid: {repair}\nReturn corrected JSON only."
    return text


class NarrativeProvider(Protocol):
    provider_id: str

    def generate(
        self,
        snapshot: CompanyResearchSnapshot,
        *,
        question: str | None = None,
        repair: str | None = None,
    ) -> NarrativeResponse: ...


@dataclass
class FreeRouterNarrativeProvider:
    script_path: Path
    timeout_seconds: int = 150
    provider_id: str = "free_token_router"

    @classmethod
    def from_environment(cls) -> "FreeRouterNarrativeProvider":
        configured = os.environ.get("TP_FREE_TOKEN_ROUTER_SCRIPT", "").strip()
        if not configured:
            raise ValueError("TP_FREE_TOKEN_ROUTER_SCRIPT 未配置")
        return cls(Path(configured).resolve())

    def generate(
        self,
        snapshot: CompanyResearchSnapshot,
        *,
        question: str | None = None,
        repair: str | None = None,
    ) -> NarrativeResponse:
        if not self.script_path.is_file():
            raise FileNotFoundError(f"免费模型路由脚本不存在：{self.script_path}")
        result = subprocess.run(
            [sys.executable, str(self.script_path), "--json"],
            input=_prompt(snapshot, question=question, repair=repair),
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError(f"免费模型路由失败：{result.stderr.strip()[:500]}")
        envelope = json.loads(result.stdout)
        document = NarrativeDocument.model_validate(_content_json(envelope["content"]))
        return NarrativeResponse(
            provider=self.provider_id,
            requested_model=envelope["requested_model"],
            actual_model=envelope["actual_model"],
            document=document,
            audit={
                "router_script_sha256": hashlib.sha256(
                    self.script_path.read_bytes()
                ).hexdigest(),
                "prompt_version": NARRATIVE_PROMPT_VERSION,
            },
        )


class Glm51NarrativeProvider:
    provider_id = "glm-5.1"

    def __init__(self, client: Glm51Client):
        self.client = client

    @classmethod
    def from_environment(cls) -> "Glm51NarrativeProvider":
        return cls(Glm51Client(GlmClientConfig.from_environment()))

    def generate(
        self,
        snapshot: CompanyResearchSnapshot,
        *,
        question: str | None = None,
        repair: str | None = None,
    ) -> NarrativeResponse:
        raw, metadata = self.client.complete_json(
            SYSTEM_INSTRUCTION,
            _prompt(snapshot, question=question, repair=repair),
        )
        return NarrativeResponse(
            provider=self.provider_id,
            requested_model="glm-5.1",
            actual_model=str(metadata.get("actual_model") or "glm-5.1"),
            document=NarrativeDocument.model_validate(raw),
            audit={
                "request_id": metadata.get("request_id"),
                "usage": metadata.get("usage"),
                "prompt_version": NARRATIVE_PROMPT_VERSION,
            },
        )


def validate_narrative(
    snapshot: CompanyResearchSnapshot,
    response: NarrativeResponse,
) -> None:
    valid_ids = {fact.fact_id for fact in snapshot.facts}
    valid_ids.update(item.evidence_id for item in snapshot.evidence)
    unknown = {
        evidence_id
        for section in response.document.sections
        for claim in section.claims
        for evidence_id in claim.evidence_ids
        if evidence_id not in valid_ids
    }
    if unknown:
        raise ValueError(f"叙述引用未知证据：{sorted(unknown)}")

    identity_numbers = {
        token.rstrip("%")
        for value in (snapshot.name, snapshot.symbol, snapshot.isin, snapshot.as_of)
        if value
        for token in MODEL_NUMERAL.findall(value)
    }
    fact_values = [fact.value for fact in snapshot.facts]
    texts = [
        response.document.title,
        *(
            value
            for section in response.document.sections
            for value in [section.heading, section.text, *(claim.claim for claim in section.claims)]
        ),
        *response.document.limitations,
    ]
    unsupported: list[str] = []
    for token in MODEL_NUMERAL.findall("\n".join(texts)):
        raw = token.rstrip("%")
        if raw in identity_numbers:
            continue
        value = float(raw)
        candidates = [value / 100.0] if token.endswith("%") else [value]
        supported = any(
            abs(candidate - fact_value)
            <= max(1e-8, abs(fact_value) * 0.005)
            for candidate in candidates
            for fact_value in fact_values
        )
        if not supported:
            unsupported.append(token)
    if unsupported:
        raise ValueError(f"叙述包含无确定性依据的数字：{unsupported[:10]}")


class NarrativeRouter:
    def __init__(
        self,
        primary: NarrativeProvider | None,
        fallback: NarrativeProvider | None,
        *,
        enabled: bool | None = None,
        cache_root: str | Path = REPORTS_DIR / "company_research" / "narrative_cache",
    ):
        self.primary = primary
        self.fallback = fallback
        self.enabled = (
            os.environ.get("TP_NARRATIVE_ENABLED", "0") == "1"
            if enabled is None
            else enabled
        )
        self.cache_root = Path(cache_root)

    def generate(
        self,
        snapshot: CompanyResearchSnapshot,
        *,
        question: str | None = None,
    ) -> NarrativeResponse | None:
        if not self.enabled:
            return None
        cache_key = _digest(
            {
                "snapshot": snapshot.snapshot_fingerprint,
                "question": question,
                "prompt_version": NARRATIVE_PROMPT_VERSION,
            }
        )
        target = self.cache_root / snapshot.isin / f"{cache_key}.json"
        if target.is_file():
            return NarrativeResponse.model_validate_json(target.read_text(encoding="utf-8"))
        for provider in (self.primary, self.fallback):
            if provider is None:
                continue
            repair = None
            for _attempt in range(2):
                try:
                    response = provider.generate(snapshot, question=question, repair=repair)
                    validate_narrative(snapshot, response)
                    self._cache(target, response)
                    return response
                except (
                    RuntimeError,
                    OSError,
                    subprocess.SubprocessError,
                    json.JSONDecodeError,
                    ValidationError,
                    ValueError,
                ) as error:
                    repair = str(error)
        return None

    @staticmethod
    def _cache(target: Path, response: NarrativeResponse) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        if target.exists():
            temporary.unlink()
            return
        os.replace(temporary, target)


def build_default_router() -> NarrativeRouter:
    primary = None
    fallback = None
    if os.environ.get("TP_FREE_TOKEN_ROUTER_SCRIPT", "").strip():
        primary = FreeRouterNarrativeProvider.from_environment()
    if os.environ.get("AI_BASE_URL", "").strip() and os.environ.get("AI_API_KEY", "").strip():
        fallback = Glm51NarrativeProvider.from_environment()
    return NarrativeRouter(primary, fallback)


__all__ = [
    "FreeRouterNarrativeProvider",
    "Glm51NarrativeProvider",
    "NarrativeProvider",
    "NarrativeRouter",
    "build_default_router",
    "validate_narrative",
]
