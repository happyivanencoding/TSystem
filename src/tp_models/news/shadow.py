"""Dry-run/apply entry point for OKF -> GLM-5.1 versioned shadow features."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Iterable

from tp_core.workspace import CONFIG_ROOT, RESEARCH_FEATURES_DIR
from tp_data.providers import OkfNewsProvider, ProviderContext, ProviderQuery

from .glm51_features import (
    FEATURE_SET_ID,
    Glm51Client,
    Glm51NewsFeatureExtractor,
    GlmClientConfig,
    evaluate_repeat_stability,
)

DEFAULT_CONFIG = CONFIG_ROOT / "news" / "glm51_shadow.json"


def _market(region: str | None) -> str:
    normalized = (region or "").strip().upper()
    aliases = {
        "USA": "US",
        "UNITED STATES": "US",
        "EUROPE": "EU",
        "EUROPEAN UNION": "EU",
        "JAPAN": "JP",
        "CHINA": "CN_HK",
        "HONG KONG": "CN_HK",
    }
    return aliases.get(normalized, normalized if normalized in {"US", "EU", "JP", "CN_HK"} else "UNMAPPED")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="构建 GLM-5.1 新闻 shadow 特征")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--apply", action="store_true", help="实际调用 API；默认只做清单预览")
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--from-date")
    parser.add_argument("--to-date")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    provider = OkfNewsProvider()
    result = provider.fetch(
        ProviderQuery(
            source="okf_news",
            job={
                "manifest_path": os.environ.get(
                    "TP_OKF_MANIFEST",
                    config["okf"]["manifest_path"],
                ),
                "notes_root": os.environ.get(
                    "TP_OKF_NOTES_ROOT",
                    config["okf"]["notes_root"],
                ),
            },
        ),
        ProviderContext(retrieved_at=datetime.now(timezone.utc)),
    )
    records = list(result.records)
    if args.from_date:
        records = [
            record
            for record in records
            if record.observation_date.date().isoformat() >= args.from_date
        ]
    if args.to_date:
        records = [
            record
            for record in records
            if record.observation_date.date().isoformat() <= args.to_date
        ]
    records.sort(key=lambda record: (record.observation_date, record.record_id))
    if args.max_records is not None:
        records = records[: args.max_records]
    payload: dict[str, object] = {
        "mode": "apply" if args.apply else "dry-run",
        "feature_set_id": FEATURE_SET_ID,
        "eligible_records": len(records),
        "source_audit": result.raw_payload,
        "predictor_default": False,
    }
    if args.apply:
        extractor = Glm51NewsFeatureExtractor(
            Glm51Client(GlmClientConfig.from_environment())
        )
        features = [
            extractor.extract(record, market=_market(record.region))
            for record in records
        ]
        stability = evaluate_repeat_stability(features)
        payload.update(
            {
                "created_features": len(features),
                "repeat_stability": stability,
                "promotion_status": "research_only",
            }
        )
        batch_root = RESEARCH_FEATURES_DIR / "news" / FEATURE_SET_ID / "batches"
        batch_root.mkdir(parents=True, exist_ok=True)
        batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = batch_root / f"{batch_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        payload["batch_manifest"] = str(target.resolve())
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
