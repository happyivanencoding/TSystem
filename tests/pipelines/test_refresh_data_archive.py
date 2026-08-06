from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pandas as pd

refresh_data = import_module("tp_pipelines.refresh_data")


def test_transco_factset_icb_inspect_reads_mapping_sheet(tmp_path: Path, monkeypatch) -> None:
    workbook = tmp_path / "Transco_FactSet_ICB.xlsx"
    pd.DataFrame({"FactSet Ind": [1], "ICB19": [2]}).to_excel(
        workbook,
        sheet_name="Mapping",
        index=False,
    )
    monkeypatch.setattr(refresh_data, "TRANSCO_FACTSET_ICB_PATH", workbook)

    inspected = refresh_data._inspect_transco_factset_icb()

    assert inspected["path"] == str(workbook)
    assert "Mapping" in inspected["sheet_names"]


def test_archive_processed_input_batch_moves_batch_and_matching_loose_original(
    tmp_path: Path,
    monkeypatch,
) -> None:
    incoming = tmp_path / "incoming"
    batch = incoming / "202607"
    ciq_dir = batch / "ciq"
    ciq_dir.mkdir(parents=True)
    (ciq_dir / "download (11)").write_bytes(b"ciq-history")
    loose_original = incoming / "download (11)"
    loose_original.write_bytes(b"ciq-history")

    monkeypatch.setattr(refresh_data, "PRODUCTION_INCOMING_DIR", incoming)

    result = refresh_data._archive_processed_input_batch(str(batch), dry_run=False)

    target = Path(result["target_path"])
    assert result["action"] == "moved"
    assert result["reason"] == "prod_success"
    assert result["file_count"] == 1
    assert not batch.exists()
    assert not loose_original.exists()
    assert (target / "ciq" / "download (11)").read_bytes() == b"ciq-history"
    assert (target / "loose_originals" / "download (11)").read_bytes() == b"ciq-history"
