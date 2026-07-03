"""检查新代码是否引用冻结目录。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Iterable

TP_ROOT = Path(__file__).resolve().parents[1]

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
    ".codex_tmp",
    ".idea",
    "__pycache__",
    "99_archive",
    "99_backtest_gui_legacy",
    "99_backtest_web_app_legacy",
    "99_optimiseur_legacy",
}

SKIP_DIR_MARKERS = {
    "_quarantine_20260629",
}

SKIP_RELATIVE_FILES = {
    Path("01_tp_core/legacy_policy.py"),
}

FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
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
    parts = set(path.parts)
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return True
    return any(marker in parts for marker in SKIP_DIR_MARKERS)


def _iter_candidate_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            relative_path = path.relative_to(root)
        except ValueError:
            relative_path = path
        if relative_path in SKIP_RELATIVE_FILES:
            continue
        if _should_skip_dir(path.parent):
            continue
        yield path


def scan_legacy_references(root: Path = TP_ROOT) -> list[LegacyReference]:
    """扫描代码和配置文件中的冻结目录引用。"""

    findings: list[LegacyReference] = []
    for path in _iter_candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in FORBIDDEN_PATTERNS:
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
    parser = argparse.ArgumentParser(description="检查新代码是否引用冻结目录")
    parser.add_argument("--root", default=str(TP_ROOT), help="扫描根目录，默认 TP 根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    findings = scan_legacy_references(Path(args.root))
    if args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    else:
        if findings:
            print("发现冻结目录引用：")
            for item in findings:
                print(f"{item.file}:{item.line} [{item.pattern}] {item.text}")
        else:
            print("未发现新代码引用冻结目录。")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
