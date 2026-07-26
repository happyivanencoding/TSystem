"""读取 maj cycle macro2.xlsx 的 Europe / US 宏观数据并保存为 parquet 数据源。"""
from pathlib import Path
import pandas as pd

from tp_core.data_sources import TP_ROOT

BASE = TP_ROOT / "03_regime_model"
SRC = TP_ROOT / "00_screen" / "production_inputs" / "maj cycle macro2.xlsx"


def load_sheet(sheet: str, usecols: str) -> pd.DataFrame:
    """读取单个 sheet：第 3 行为列名，按 Date 索引并去除无效行。"""
    df = pd.read_excel(SRC, sheet_name=sheet, header=2, usecols=usecols)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
    return df


def main() -> None:
    europe = load_sheet("Europe", "A:N").add_prefix("EU_")  # A 到 N 栏
    us = load_sheet("US", "A:M").add_prefix("US_")          # A 到 M 栏
    # 按 Date 外连接合并成单一宽表
    macro = europe.join(us, how="outer").sort_index()
    macro.to_parquet(BASE / "macro_data.parquet")
    print(f"Merged: {macro.shape} -> macro_data.parquet")


if __name__ == "__main__":
    main()
