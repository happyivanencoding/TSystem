from __future__ import annotations

from importlib import import_module
from pathlib import Path


refresh_data = import_module("02_pipelines.refresh_data")


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
