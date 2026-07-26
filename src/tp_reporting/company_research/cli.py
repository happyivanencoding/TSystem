"""Build a deterministic company report with optional grounded narrative."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Iterable

import pandas as pd

from presentation_layer import company_analysis
from tp_core.workspace import REPORTS_DIR

from .deterministic import render_markdown
from .narrative import build_default_router
from .snapshot import build_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成确定性公司研究报告")
    parser.add_argument("isin")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--narrative", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    data = company_analysis.get_data()
    selected = data[data["ISIN"] == args.isin]
    if selected.empty:
        raise ValueError(f"Company not found: {args.isin}")
    row = selected.iloc[0]
    region = row.get("Exchange Country Region")
    sector = row.get("Supersector")
    medians = {}
    if pd.notna(region) and pd.notna(sector):
        medians = company_analysis.get_medians_data().get((region, sector), {})
    snapshot = build_snapshot(row.to_dict(), medians)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or (
        REPORTS_DIR / "company_research" / args.isin / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    narrative = build_default_router().generate(snapshot) if args.narrative else None
    snapshot_path = output_dir / "snapshot.json"
    report_path = output_dir / "report.md"
    snapshot_path.write_text(
        snapshot.model_dump_json(indent=2),
        encoding="utf-8",
    )
    report_path.write_text(
        render_markdown(snapshot, narrative),
        encoding="utf-8",
    )
    narrative_path = None
    if narrative is not None:
        narrative_path = output_dir / "narrative.json"
        narrative_path.write_text(narrative.model_dump_json(indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "complete",
                "mode": "grounded_narrative" if narrative else "deterministic_only",
                "snapshot": str(snapshot_path.resolve()),
                "report": str(report_path.resolve()),
                "narrative": str(narrative_path.resolve()) if narrative_path else None,
                "narrative_enabled": os.environ.get("TP_NARRATIVE_ENABLED", "0") == "1",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
