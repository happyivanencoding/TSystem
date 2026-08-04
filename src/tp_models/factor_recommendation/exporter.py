"""推荐结果导出与固定 lineage manifest。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .contracts import RecommendationContract
from .persistence import DEFAULT_KEY_COLUMNS, upsert_frame


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def export_recommendations(
    frame: pd.DataFrame,
    output_dir: str | Path,
    *,
    stem: str = "factor_recommendations",
    key_columns: Iterable[str] = DEFAULT_KEY_COLUMNS,
    formats: Iterable[str] = ("parquet", "csv", "json"),
    contract: RecommendationContract | None = None,
) -> dict[str, str]:
    """以逻辑键幂等写出 parquet/csv/json，并返回实际路径。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    persisted = frame.copy()
    contract = contract or RecommendationContract()
    if "schema_version" not in persisted.columns:
        persisted["schema_version"] = contract.schema_version
    if "probability_available" not in persisted.columns:
        persisted["probability_available"] = False
    paths: dict[str, str] = {}
    for fmt in tuple(formats):
        suffix = fmt.lower().lstrip(".")
        path = output / f"{stem}.{suffix}"
        if suffix in {"parquet", "csv", "json", "jsonl"}:
            upserted = upsert_frame(path, persisted, key_columns=key_columns)
            paths[suffix] = str(path)
            if suffix == "json":
                # upsert_frame already wrote JSON; this branch only documents the format.
                _ = upserted
        else:
            raise ValueError(f"unsupported export format: {fmt}")
    manifest = {
        "schema_version": contract.schema_version,
        "model_version": contract.model_version,
        "row_count": int(len(persisted)),
        "key_columns": list(key_columns),
        "probability_semantics": contract.probability_semantics,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "outputs": paths,
    }
    manifest_path = output / f"{stem}.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
    )
    paths["manifest"] = str(manifest_path)
    return paths


def export_frame(frame: pd.DataFrame, output_dir: str | Path, **kwargs: Any) -> dict[str, str]:
    return export_recommendations(frame, output_dir, **kwargs)


__all__ = ["export_frame", "export_recommendations"]
