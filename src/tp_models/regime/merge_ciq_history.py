"""把 ciq/new 下的历史 CIQ 数据(2009-2019)按 ISIN×年月填入 screen_aggregate。

安全策略：
- 仅对新数据提供的 82 个数据列做"填空"(只填 screen_agg 中为 NaN 的单元), 不覆盖任何已有值。
- 按(ISIN, 年月)对齐(两边月末日不同: 31 vs 30); 仅更新已存在的行, 不新增股票/行。
- 不改动 screen_agg 的 Date 及 ISIN 索引。运行前请确保已备份到 bk。
"""
import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd

from tp_core.data_sources import CIQ_NEW_DIR
from tp_core.data_sources import SCREEN_AGGREGATE_PATH
SA = str(SCREEN_AGGREGATE_PATH)
NEW = [str(path) for path in sorted(CIQ_NEW_DIR.iterdir()) if path.is_file()]


def main() -> None:
    # 1) 新数据：合并、按(ISIN,年月)去重、保留数据列
    nw = pd.concat([pd.read_parquet(p) for p in NEW], ignore_index=True)
    nw = nw.drop(columns=[c for c in ["__index_level_0__"] if c in nw.columns])
    nw["ym"] = pd.to_datetime(nw["Date"]).dt.to_period("M")
    datacols = [c for c in nw.columns if c not in ("ISIN", "Date", "ym")]
    nw = nw.drop_duplicates(["ISIN", "ym"]).set_index(["ISIN", "ym"])[datacols]

    # 2) 读全表(arrow), 构造 screen_agg 行序的(ISIN,年月)键
    #    直接取 arrow 列(避开 ISIN 作为 pandas 索引的元数据)
    table = pq.read_table(SA)
    isin = table.column("ISIN").to_pandas()
    ym = pd.to_datetime(table.column("Date").to_pandas()).dt.to_period("M")
    mi = pd.MultiIndex.from_arrays([isin.values, ym.values], names=["ISIN", "ym"])

    # 3) 把新值按行序对齐到 screen_agg
    fill = nw.reindex(mi)

    # 4) 逐列填空并替换(保持原 arrow 类型)
    filled_cols, n_filled = [], {}
    for c in datacols:
        orig = table.column(c).to_pandas().reset_index(drop=True)
        add = pd.Series(fill[c].values, index=orig.index)
        before = orig.isna().sum()
        merged = orig.fillna(add)
        n_filled[c] = int(before - merged.isna().sum())
        idx = table.schema.get_field_index(c)
        arr = pa.array(merged, type=table.schema.field(c).type)
        table = table.set_column(idx, c, arr)
        filled_cols.append(c)

    # 5) 落地(覆盖)
    pq.write_table(table, SA)

    tot = sum(n_filled.values())
    print(f"完成：填充 {len(filled_cols)} 列, 共 {tot} 个单元。")
    print("填充最多的8列:")
    for c, v in sorted(n_filled.items(), key=lambda x: -x[1])[:8]:
        print(f"  {c:30s} {v}")


if __name__ == "__main__":
    main()
