"""factor recommendation CLI。

常用入口：

``python -m tp_models.factor_recommendation.cli inspect``

会生成固定的五个 audit artifacts；``features`` 和 ``latest`` 只在显式
传入输出路径时写模型产物。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import LAST_SCREEN_PATH, RETURNS_PATH, SCREEN_AGGREGATE_PATH
from tp_core.io import read_screen_aggregate

from .audit import DEFAULT_AUDIT_DIR, write_audit_artifacts
from .config import load_runtime_config
from .factor_definitions import load_factor_definitions
from .features import build_monthly_features, latest_month_features
from .universe import load_region_universes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monthly factor recommendation core package")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect", help="生成固定 repository/data/universe/factor 审计")
    inspect.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH))
    inspect.add_argument("--returns", default=str(RETURNS_PATH))
    inspect.add_argument("--audit-dir", default=str(DEFAULT_AUDIT_DIR))
    inspect.add_argument("--factor-definitions", default=None)
    inspect.add_argument("--region-universes", default=None)

    features = subparsers.add_parser("features", help="构建 PIT 区域月度特征")
    features.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH))
    features.add_argument("--region", required=True)
    features.add_argument("--output", required=True)
    features.add_argument("--pit-lag-months", type=int, default=1)
    features.add_argument("--include-unlabeled-latest", action="store_true")
    features.add_argument("--factor-definitions", default=None)

    latest = subparsers.add_parser("latest", help="输出最新可用的 PIT 特征 JSON")
    latest.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH))
    latest.add_argument("--region", required=True)
    latest.add_argument("--output", required=True)
    latest.add_argument("--pit-lag-months", type=int, default=1)
    latest.add_argument("--factor-definitions", default=None)

    return parser


def _load_definitions(path: str | None):
    return load_factor_definitions(path) if path else load_factor_definitions()


def _model_screen_columns(screen_path: str | Path, region: str, definitions) -> list[str]:
    columns = {"ISIN", "Date", "Company SEDOL"}
    for definition in definitions:
        columns.update(definition.source_columns)
    regions = load_region_universes()
    region_name = str(region).upper()
    spec = regions.get(region_name)
    specs = [spec] if spec is not None else list(regions.values())
    for region_spec in specs:
        for component in region_spec.components:
            columns.add(component.weight_column)
            if component.country_column:
                columns.add(component.country_column)
    try:
        import pyarrow.parquet as pq

        available = set(pq.ParquetFile(screen_path).schema_arrow.names)
        return sorted(column for column in columns if column in available)
    except ImportError:  # pragma: no cover - pyarrow is a project dependency
        return sorted(columns)


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "inspect":
        config = load_runtime_config(
            factor_definitions_path=args.factor_definitions,
            region_universes_path=args.region_universes,
        )
        paths = write_audit_artifacts(
            output_dir=Path(args.audit_dir),
            screen_path=Path(args.screen),
            returns_path=Path(args.returns),
            definitions_path=config.factor_definitions_path,
            regions_path=config.region_universes_path,
        )
        print(json.dumps(paths, ensure_ascii=False, indent=2))
        return 0
    definitions = _load_definitions(args.factor_definitions)
    if args.command == "features":
        screen = read_screen_aggregate(
            Path(args.screen),
            columns=_model_screen_columns(args.screen, args.region, definitions),
        )
        result = build_monthly_features(
            screen,
            args.region,
            definitions=definitions,
            pit_lag_months=args.pit_lag_months,
            include_unlabeled_latest=args.include_unlabeled_latest,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        result.to_parquet(output, index=False)
        print(json.dumps({"output": str(output), "rows": int(len(result))}, ensure_ascii=False))
        return 0
    if args.command == "latest":
        screen = read_screen_aggregate(
            Path(args.screen),
            columns=_model_screen_columns(args.screen, args.region, definitions),
        )
        result = latest_month_features(
            screen,
            args.region,
            definitions=definitions,
            pit_lag_months=args.pit_lag_months,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            result.to_json(orient="records", date_format="iso"), encoding="utf-8"
        )
        print(json.dumps({"output": str(output), "rows": int(len(result))}, ensure_ascii=False))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
