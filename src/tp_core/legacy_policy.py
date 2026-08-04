"""检查活跃代码、配置和文档是否恢复冻结路径或退役入口。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Iterable

TP_ROOT = Path(__file__).resolve().parents[2]

FROZEN_DIRS = [
    "ML",
    "ML第一版",
    "回测第一版",
    "factsetProd第一版",
    "技术分析_V1",
    "backtest",
    "cyc",
    "技术分析和深度学习/深度学习",
    "03_ml_enhanced/参考文件_EM",
]

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".ipynb",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".ps1",
    ".bat",
    ".vbs",
}

SKIP_DIR_NAMES = {
    ".git",
    ".agents",
    ".codex",
    ".idea",
    ".trae",
    "__pycache__",
    "archive",
    "archives",
    "artifacts",
    "dist",
    "handoffs",
    "manifests",
    "node_modules",
    "output",
    "outputs",
    "qa",
    "runs",
    "99_archive",
    "99_backtest_gui_legacy",
    "99_backtest_web_app_legacy",
    "99_optimiseur_legacy",
}

SKIP_DIR_MARKERS = {
    "_quarantine_20260629",
}

SKIP_RELATIVE_FILES = {
    Path("src/tp_core/legacy_policy.py"),
    Path("tests/test_legacy_policy.py"),
}

RETIRED_ENTRYPOINTS = (
    Path("00_screen/monthly_update.py"),
    Path("01_tp_core"),
    Path("02_pipelines"),
    Path("06_optimiser"),
    Path("src/backtest_code"),
    Path("03_ml_enhanced/cli.py"),
    Path("03_regime_model/export_risk_budget.py"),
    Path("03_technical_analysis/Main.py"),
    Path("03_technical_analysis/export_technical_signals.py"),
    Path("13_sector_score_model/src"),
    Path("14_country_model/src"),
    Path("15_small_cap_model/src"),
    Path("16_news_market_signal/run.py"),
    Path("07_backtest_code"),
)

FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "retired_backtest_workspace",
        re.compile(r"(?:^|[\"'` =:(])07_backtest_code(?:[\\/]|$)", re.IGNORECASE),
    ),
    (
        "retired_python_module",
        re.compile(
            r"\bpython(?:\.exe)?\s+-m\s+(?:01_tp_core|02_pipelines|pipelines|backtest_code)(?:[.\s]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "retired_file_entrypoint",
        re.compile(
            r"\bpython(?:\.exe)?\s+[^\r\n`]*(?:"
            r"00_screen[\\/]monthly_update\.py|"
            r"03_regime_model[\\/](?:build_features|train_regime|walkforward|export_dashboard|export_risk_budget)\.py|"
            r"03_technical_analysis[\\/](?:Main|export_technical_signals)\.py|"
            r"13_sector_score_model[\\/]src[\\/][^\s`]+\.py|"
            r"16_news_market_signal[\\/]run\.py"
            r")",
            re.IGNORECASE,
        ),
    ),
    (
        "retired_package_import",
        re.compile(r"(?:from|import)\s+(?:pipelines|backtest_code)(?:\.|\s|$)", re.IGNORECASE),
    ),
    (
        "absolute_path_to_frozen_ML",
        re.compile(r"C:[\\/]GoogleDrive[\\/]TP[\\/]ML(?:[\\/]|$)", re.IGNORECASE),
    ),
    (
        "relative_path_to_frozen_ML",
        re.compile(r"(?:^|[\"'=:(])(?:\.\.[\\/])*ML[\\/](?!Enhanced)(?=[A-Za-z0-9_.-])", re.IGNORECASE),
    ),
    ("frozen_ML_import", re.compile(r"(?:from|import)\s+ML(?:\.|\s|$)")),
    ("frozen_ML第一版", re.compile(r"ML第一版")),
    ("frozen_回测第一版", re.compile(r"回测第一版")),
    ("frozen_factsetProd第一版", re.compile(r"factsetProd第一版")),
    ("frozen_技术分析_V1", re.compile(r"技术分析_V1")),
    (
        "absolute_path_to_frozen_backtest",
        re.compile(r"C:[\\/]GoogleDrive[\\/]TP[\\/]backtest(?:[\\/]|$)", re.IGNORECASE),
    ),
    (
        "absolute_path_to_frozen_cyc",
        re.compile(r"C:[\\/]GoogleDrive[\\/]TP[\\/]cyc(?:[\\/]|$)", re.IGNORECASE),
    ),
    (
        "absolute_path_to_frozen_deep_learning",
        re.compile(r"C:[\\/]GoogleDrive[\\/]TP[\\/]技术分析和深度学习[\\/]深度学习(?:[\\/]|$)", re.IGNORECASE),
    ),
    (
        "absolute_path_to_frozen_em_reference",
        re.compile(r"C:[\\/]GoogleDrive[\\/]TP[\\/]ML_Enhanced[\\/]参考文件_EM(?:[\\/]|$)", re.IGNORECASE),
    ),
    (
        "path_to_numbered_em_reference",
        re.compile(r"(?:C:[\/]GoogleDrive[\/]TP[\/])?03_ml_enhanced[\/]参考文件_EM(?:[\/]|$)", re.IGNORECASE),
    ),
]


@dataclass
class LegacyReference:
    file: str
    line: int
    pattern: str
    text: str


def _should_skip_dir(path: Path) -> bool:
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return True
    parts = set(path.parts)
    return any(marker in parts for marker in SKIP_DIR_MARKERS)


def _iter_candidate_files(root: Path) -> Iterable[Path]:
    for current, directory_names, file_names in os.walk(root):
        current_path = Path(current)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not _should_skip_dir(current_path / name)
        )
        for file_name in sorted(file_names):
            path = current_path / file_name
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                relative_path = path.relative_to(root)
            except ValueError:
                relative_path = path
            if relative_path in SKIP_RELATIVE_FILES:
                continue
            yield path


def scan_legacy_references(root: Path = TP_ROOT) -> list[LegacyReference]:
    """扫描活跃代码、配置、文档和物理路径中的旧入口。"""

    findings: list[LegacyReference] = []
    for relative_path in RETIRED_ENTRYPOINTS:
        if (root / relative_path).exists():
            findings.append(
                LegacyReference(
                    file=relative_path.as_posix(),
                    line=0,
                    pattern="retired_entrypoint_exists",
                    text="退役入口仍存在于活跃工作区",
                )
            )
    for path in _iter_candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in FORBIDDEN_PATTERNS:
                normalized_line = line.replace("\\", "/")
                if name.startswith("frozen_") and "99_archive/" in normalized_line:
                    continue
                if pattern.search(line):
                    findings.append(
                        LegacyReference(
                            file=str(path.relative_to(root)),
                            line=line_number,
                            pattern=name,
                            text=line.strip()[:240],
                        )
                    )
    return findings


def main(argv: Iterable[str] | None = None) -> int:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="检查活跃代码、配置和文档是否恢复冻结路径或退役入口")
    parser.add_argument("--root", default=str(TP_ROOT), help="扫描根目录，默认 TP 根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    findings = scan_legacy_references(Path(args.root))
    if args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    else:
        if findings:
            print("发现冻结路径或退役入口：")
            for item in findings:
                print(f"{item.file}:{item.line} [{item.pattern}] {item.text}")
        else:
            print("未发现活跃内容引用冻结路径或退役入口。")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
