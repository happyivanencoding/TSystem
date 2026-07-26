from pathlib import Path

from tp_core.legacy_policy import scan_legacy_references


def test_retired_entrypoint_file_is_reported(tmp_path: Path) -> None:
    entrypoint = tmp_path / "00_screen" / "monthly_update.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("raise SystemExit(0)\n", encoding="utf-8")

    findings = scan_legacy_references(tmp_path)

    assert any(item.pattern == "retired_entrypoint_exists" for item in findings)


def test_retired_command_in_markdown_is_reported(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("python C:/GoogleDrive/TP/16_news_market_signal/run.py build-daily\n", encoding="utf-8")

    findings = scan_legacy_references(tmp_path)

    assert any(item.pattern == "retired_file_entrypoint" for item in findings)


def test_current_package_command_is_allowed(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("python -m tp_models.news.run build-daily\n", encoding="utf-8")

    assert scan_legacy_references(tmp_path) == []


def test_archived_source_provenance_is_allowed(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "Source: C:/GoogleDrive/TP/99_archive/frozen_20260629/factsetProd第一版/model.xlsm\n",
        encoding="utf-8",
    )

    assert scan_legacy_references(tmp_path) == []


def test_generated_artifacts_are_pruned_before_text_scan(tmp_path: Path) -> None:
    generated = tmp_path / "artifacts" / "research" / "old.md"
    generated.parent.mkdir(parents=True)
    generated.write_text(
        "python C:/GoogleDrive/TP/16_news_market_signal/run.py build-daily\n",
        encoding="utf-8",
    )

    assert scan_legacy_references(tmp_path) == []
