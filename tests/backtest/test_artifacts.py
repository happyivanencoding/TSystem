import pandas as pd

from tp_backtest.runner.artifacts import save_dataframe


def test_save_dataframe_skips_excel_backup_when_sheet_is_too_large(tmp_path):
    target = tmp_path / "large.parquet"
    dataframe = pd.DataFrame({"value": range(1_048_577)})

    saved_path = save_dataframe(dataframe, target)

    assert saved_path == target
    assert target.exists()
    assert not (tmp_path / "large.xlsx").exists()
    note_path = tmp_path / "large.xlsx.skipped.txt"
    assert note_path.exists()
    assert "too large" in note_path.read_text(encoding="utf-8")
