# small_cap

## 定位

`small_cap` 是小盘研究相关片段目录。目前主要文档是 `cols.md`，它更像一次字段列表快照，不是 canonical 字段字典。

## 数据来源

若继续维护该研究，应统一读取 TP canonical 数据：

- `00_screen/screen_aggregate.parquet`
- `00_screen/returns.parquet`

字段语义以 [`../DATA_CONTRACT.md`](../DATA_CONTRACT.md) 和 [`../00_screen/说明文档/Screen_Agg数据库字典.md`](../00_screen/说明文档/Screen_Agg数据库字典.md) 为准。

## 文档

- [`cols.md`](cols.md)：历史字段列表快照，缺少生成日期和数据版本，不应单独作为字段字典使用。

## 维护状态

辅助研究。若继续使用，建议补充研究目标、universe、信号字段和输出位置；否则可以在下一轮整理中归档。
