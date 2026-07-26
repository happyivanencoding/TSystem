"""Small evidence schema shared by TP qualitative research workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import json
from pathlib import Path
from typing import Iterable, Literal


EvidenceStance = Literal["支持", "反驳", "中性", "缺口"]
EvidenceKind = Literal["model", "obsidian", "web", "manual", "gap"]


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    kind: EvidenceKind
    region: str
    subject: str
    view: str
    stance: EvidenceStance
    title: str
    summary: str
    source: str = ""
    source_date: str = ""
    captured_at: str = ""
    links: list[str] = field(default_factory=list)
    related_notes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EvidencePack:
    region: str
    subject: str
    view: str
    model_scores: dict[str, float | str | None]
    items: list[EvidenceItem]
    missing_obsidian: bool
    missing_web_count: int

    def quality_status(self) -> str:
        if self.missing_obsidian or self.missing_web_count > 0:
            return "needs_review"
        return "ready"

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"quality_status": self.quality_status()}


@dataclass(frozen=True)
class SourceManifest:
    run_id: str
    generated_at: str
    model: str
    window_days: int
    output_language: str
    vault_root: str
    sources: list[dict[str, object]]
    notes_written: list[str]

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        model: str,
        window_days: int,
        output_language: str,
        vault_root: Path,
        sources: list[dict[str, object]] | None = None,
        notes_written: list[str] | None = None,
    ) -> "SourceManifest":
        return cls(
            run_id=run_id,
            generated_at=datetime.now().isoformat(timespec="seconds"),
            model=model,
            window_days=window_days,
            output_language=output_language,
            vault_root=str(vault_root),
            sources=sources or [],
            notes_written=notes_written or [],
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            if hasattr(row, "to_dict"):
                row = row.to_dict()
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)
