# FactSet 数据库字段字典（正式版）

## 文档定位

本文档为Scrren Aggregate月度数据库更新模板的正式字段字典版本，按 `Ref`、`Heading`、中文业务定义、公式摘要、字段属性、时间口径、比较组、备注和复核标识统一整理。本文档用于数据库落库说明、研究框架对齐、团队交接和后续模板治理。

## 字段定义规则

- **Ref**：模板内部引用名，建议作为技术字段名优先保留。
- **Heading**：最终数据库列名 / 展示名。
- **Business Definition**：基于公式反推后的中文业务定义。
- **Formula Summary**：对公式逻辑的简要摘要，强调取数方式、聚合方式、回退逻辑或排序逻辑。
- **Raw or Derived**：区分原始字段与衍生字段；分位数、聚合分和行业分流字段通常定义为衍生字段。
- **Horizon**：统一标记为 FY0 / FY1 / NTM / LTM / Hist / Spot / Static/Spot。
- **Compare Group**：若为分位类或分档类字段，则说明横向比较组；非比较类字段记为 `N/A`。
- **Notes**：保留口径说明、回退逻辑、行业适配逻辑，并加入经济含义备注。
- **Review Flag**：标记是否建议人工复核。

## 优先复核字段

| Ref | Heading | Review Flag | 原因 |
|---|---|---|---|
| M_ERR | EPS Revision Ratio | Yes | 公式存在括号优先级歧义，需确认是否为净上修数除以估计样本数。 |
| V_PB_PTANGB_NTM | PB / PTangibleBook NTM | Yes | 行业分流逻辑与 LTM / FY1 版本不完全一致。 |
| VALUE_AVGP_HIST | Value_Spot_Avg Percentile | Yes | 聚合时引用的底层别名与显式列名存在不完全对齐。 |
| G_HIST_EPS | PCT Hist EPS | Yes | Heading 似为分位值，但公式语义更像原始趋势稳定度。 |
| PCT_G_HIST_EPS | PCT Hist EPS | Yes | 命名与上游依赖字段存在遗留不一致风险。 |


## 一、基础识别与公司概览

| Ref | Heading | Business Definition | Formula Summary | Raw or Derived | Horizon | Compare Group | Notes | Review Flag |
|---|---|---|---|---|---|---|---|---|
| FZCOL1 | Symbol | 证券代码 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | Static/Spot | N/A | 优先取 `PSYM`，缺失时回退 `CUSIP`。 主键识别字段，用于证券层级去重与映射。 | No |
| FZCOL2 | Name | 公司名称 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | Static/Spot | N/A | 优先取 `PROPER_NAME`，缺失时回退 `CN`。 名称字段主要用于人工校验、展示和合并报表。 | No |
| P60 | Exchange Country Name | 上市交易所所属国家名称 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | Static/Spot | N/A | 表示交易地国家，不一定等同经营地或注册地。 交易地国家常用于市场归属、交易规则和区域统计，不代表收入暴露。 | No |
| P57 | Company SEDOL | 公司 / 证券 SEDOL（含校验位） | 直接读取证券标识字段，用于映射和识别。 | Raw | Static/Spot | N/A | 识别字段。 - | No |
| P58 | ISIN | 证券 ISIN 编码 | 直接读取证券标识字段，用于映射和识别。 | Raw | Static/Spot | N/A | 识别字段。 - | No |
| P59 | FactSet Ind | FactSet 行业分类 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | Static/Spot | N/A | FactSet 自有行业分类字段。 可作为 FactSet 口径行业标签，与 ICB 可并行使用。 | No |
| P66 | FactSet Economy | FactSet 经济体 / 国家归属分类 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | Static/Spot | N/A | 用于国家或经济体维度归属。 用于国家/经济体维度聚合分析。 | No |
| P110 | Curncy Iso | 证券或公司主货币的 ISO 代码 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Static/Spot | N/A | 例如 EUR、USD。 - | No |
| REGION | Exchange Country Region | 交易所所属国家的大区 / 区域 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | Static/Spot | N/A | 用于区域分组。 - | No |
| P62 | Benchmark Country English | 基准 universe 下的英文国家归属 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | Static/Spot | N/A | 更偏基准归属口径，不完全等同上市地。 - | No |
| ICB_10 | Benchmark ICB Industry | 基准 universe 下的 ICB 一级行业 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | Static/Spot | N/A | 由 `CLASS1` 返回。 - | No |
| ICB_19 | Benchmark ICB Supersector | 基准 universe 下的 ICB 二级超级行业 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | Static/Spot | N/A | 由 `CLASS2` 返回。 - | No |
| P144 | Benchmark Market Value Millions in EUR | 公司总市值（百万欧元） | 读取评价日市值或相关规模字段。 | Raw | Spot | N/A | 评价日市值口径。 市值是规模、权重和流动性分析的核心底层变量。 | No |
| P89 | Date | 评价日日期 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 数据快照日期。 - | No |
| P61 | Benchmark Identifier - SEDOLCHK | 基准 universe 使用的 SEDOLCHK 标识 | 直接读取证券标识字段，用于映射和识别。 | Raw | Static/Spot | N/A | 基准成份识别字段。 - | No |
| P117 | Exchange Country Iso2 | 交易所所属国家 ISO2 代码 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | Static/Spot | N/A | 如 FR、US。 - | No |
| IPCM_E | ESG_E | 环境维度分析师评分 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Static/Spot | N/A | 来源于 `ES_ANALYST_SCORE`。 反映环境管理与环境风险暴露质量。 | No |
| IPCM_S | ESG_S | 社会维度分析师评分 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Static/Spot | N/A | 来源于 `HC_ANALYST_SCORE`。 反映员工、客户、供应链与社会责任管理。 | No |
| IPCM_G | ESG_G | 治理维度分析师评分 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Static/Spot | N/A | 来源于 `OC_ANALYST_SCORE`。 反映治理结构、董事会质量与股东保护。 | No |
| IPCM_ESG | ESG_ANALYST_SCORE | 综合 ESG 分析师评分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Static/Spot | 继承底层分位比较组（通常为 ICB + Region） | 综合评分字段。 常用于可持续投资筛选和多因子约束。 | No |
| IPCM_CARBIMPACT | CARBON_IMPACT_SCORE | 碳影响评分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Static/Spot | 继承底层分位比较组（通常为 ICB + Region） | 碳相关综合评价。 常用于气候风险与减排转型能力评估。 | No |
| CARBON_TO_SALES | CarbonIntensity_Sales | 碳排放强度（销售额口径） | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 以销售额为分母的碳排放强度。 衡量单位收入对应的排放强度，越低通常代表经营更“轻碳”。 | No |
| P112 | CarbonIntensity_EV | Scope 1+2 排放 / 企业价值 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 本质是排放相对 EV 的强度。 把排放与企业价值挂钩，可理解为资本占用层面的碳负担。 | No |
| DECILE_CARBON_INTENSITY | Decile_CarbIntensity | 碳强度十分位分档 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 按 ICB Supersector 横向比较，且因取负号，数值方向对应“碳强度越低越优”。 用于同业内部的碳强度排序，不是绝对排放规模。 | No |
| P154 | Book Value Per Share | 每股账面价值 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 使用 semi、评价日前一年、EUR 口径。 是 PB、ROE 等估值和盈利质量指标的底层支撑。 | No |

## 二、风格总分与回报字段

| Ref | Heading | Business Definition | Formula Summary | Raw or Derived | Horizon | Compare Group | Notes | Review Flag |
|---|---|---|---|---|---|---|---|---|
| SCORE_DVD_AVG_D | Dividend Avg Percentile | 分红风格综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | FY1 | ICB + Region | 由 DPS 趋势、FY1 股息率、派息率、FY1 DPS 增长加权而成。 本质是“分红质量 + 分红吸引力 + 分红成长”的综合评分。 | No |
| VALUE_AVGP | Value Avg Percentile | Value 综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Hist | ICB + Region | 以前瞻 value 与历史 value 加权平均。 不是单一倍数，而是多种估值视角的加权汇总。 | No |
| QUALITY_AVGP | Quality Avg Percentile | Quality 综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Spot | ICB + Region | 由 ROE、营业利润率、资产周转率、净债务 / EBITDA、Tier1、ROTE、Combined Ratio 等分数组成。 体现盈利能力、资本结构、经营效率和金融稳健性的综合质量。 | No |
| GROWTH_AVGP | Growth Avg Percentile | Growth 综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Hist | ICB + Region | 由前瞻增长与历史增长加权平均。 同时看未来增长与历史增长稳定性，避免只看单期高增速。 | No |
| MOM_AVGP | Mom Avg Percentile | Momentum 综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Spot | ICB + Region | 当前定义下实质上对应动量总分的平均。 反映价格趋势与盈利预期修正是否同向强化。 | No |
| SIZE_AVGP | Size Avg Percentile | Size 综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Spot | ICB + Region | 直接等于市值分位数。 实质是规模暴露，不一定代表质量或收益。 | No |
| LOWVOL_AVGP | LowVol Avg Percentile | Low Volatility 综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Spot | ICB + Region | 由 60 日、90 日、1 年波动率分位平均而成。 低波因子常被视为防御性风格暴露。 | No |
| P105 | Total Return | 历史 1 个月总回报率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 区间为 `DATEFY-1CM` 到 `DATEFY`。 可用于近期表现回顾，也可作为风格漂移观察窗口。 | No |
| P108 | TTR_Fwd1M | 未来 1 个月总回报率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 区间为 `DATEFY` 到 `DATEFY+1CM`，更适合回测标签使用。 更像回测中的未来收益标签，不宜与解释变量混用。 | No |
| P102 | Constituent Weight SOM | 评价日基准成份权重 | 读取评价日在对应基准中的成份权重。 | Raw | Spot | N/A | 基准权重，已除以 100。 是指数归因、主动权重偏离和组合复制的重要基础字段。 | No |
| SCORE_DVD_AVG_NTM | Dividend_NTM Avg Percentile | NTM 分红综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | NTM | ICB + Region | 与 FY1 分红分逻辑一致，但采用 NTM 分红口径。 - | No |
| VALUE_AVGP_NTM | Value_NTM Avg Percentile | NTM Value 综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | NTM | ICB + Region | 前瞻部分改为 NTM，历史部分保留历史 value。 - | No |
| QUALITY_AVGP_NTM | Quality_NTM Avg Percentile | NTM Quality 综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | NTM | ICB + Region | Combined Ratio 等关键保险指标改为 NTM 口径。 - | No |
| GROWTH_AVGP_NTM | Growth_NTM Avg Percentile | NTM Growth 综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | NTM | ICB + Region | 前瞻增长改为 NTM，历史部分保持不变。 适合中短期前瞻成长排序。 | No |

## 三、动量因子（MOM）

| Ref | Heading | Business Definition | Formula Summary | Raw or Derived | Horizon | Compare Group | Notes | Review Flag |
|---|---|---|---|---|---|---|---|---|
| M_LT | PMOM 12M1M | 12M1M 价格动量 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 从 12 个月前到 1 个月前的价格变化，剔除最近 1 个月。 经典 12M1M 动量，意在剔除短期反转噪音。 | No |
| PCT_M_LT | PCT MOM 12M1M | 12M1M 动量分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 按行业 + 地区横向比较。 将绝对涨跌幅转成同业相对强弱，更适合横向选股。 | No |
| M_EPS_NTM_3 | EPS Med NTM -3M | 3 个月前的 NTM EPS 一致预期中位数 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | EUR 口径。 - | No |
| M_EPS_NTM_0 | EPS Med NTM 0 | 评价日的 NTM EPS 一致预期中位数 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | EUR 口径。 - | No |
| M_EPS_NTM3M | EPS NTM 3M Growth | 最近 3 个月 NTM EPS 预期变化率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | 衡量盈利预期修正方向。 核心看点是分析师对未来一年盈利预期是否在持续上调。 | No |
| PCT_M_EPSM3M | PCT EPSM3M | NTM EPS 3 个月变化率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| M_FY1_UP | FY1 EPS RevUP 3M Roll | 最近 3 个月 FY1 EPS 上修次数 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | FY1 | N/A | 分析师修正计数。 上修次数越多，通常表示预期改善得到更多分析师确认。 | No |
| M_FY2_UP | FY2 EPS RevUP 3M Roll | 最近 3 个月 FY2 EPS 上修次数 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 分析师修正计数。 比 FY1 更偏中期盈利预期改善。 | No |
| M_FY1_DOWN | FY1 EPS RevDown 3M Roll | 最近 3 个月 FY1 EPS 下修次数 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | FY1 | N/A | 分析师修正计数。 下修次数增加通常意味着基本面预期恶化。 | No |
| M_FY2_DOWN | FY2 EPS RevDown 3M_Roll | 最近 3 个月 FY2 EPS 下修次数 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 分析师修正计数。 反映中期盈利预期走弱。 | No |
| M_FY1_NB | FY1_NbEstimate | FY1 EPS 估计样本数 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | FY1 | N/A | 常作为修正比率分母。 - | No |
| M_FY2_NB | FY2_NbEstimate | FY2 EPS 估计样本数 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 常作为修正比率分母。 - | No |
| M_ERR | EPS Revision Ratio | EPS 修正比率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Derived | Spot | N/A | 字面是上修与下修及估计样本数组合后的净修正指标，建议复核括号优先级。 试图衡量净上修强度，经济含义接近“盈利预期扩散方向”。 | Yes |
| PCT_M_ERR | PCT ERR | EPS 修正比率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| MOM | MOM Score | 动量综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Spot | 继承底层分位比较组（通常为 ICB + Region） | 由价格动量、EPS 预期变化和 EPS 修正比率组合而成。 把价格动量和盈利预期动量合并，可减少纯价格趋势的噪音。 | No |
| PCT_MOM | PCT MOM Score | 动量综合分分位值 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 结果再除以 10 做缩放。 最终用于横向排序的动量得分。 | No |

## 四、估值因子（VALUE）

| Ref | Heading | Business Definition | Formula Summary | Raw or Derived | Horizon | Compare Group | Notes | Review Flag |
|---|---|---|---|---|---|---|---|---|
| V_EV | Custom EV last | 自定义企业价值 | 以股权市值加净债务及其他资本项目，构造自定义 EV。 | Derived | Spot | N/A | 股价 × 股数，加优先股、债务、少数股东权益，减现金及银行到期应收。 比单纯市值更接近收购企业需要承担的整体资本成本。 | No |
| V_PE_LTM | PE LTM | 历史市盈率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | LTM | N/A | 优先取 FactSet 直接字段，否则用价格 / EPS 回算；EPS≤0 时返回 NA。 适合看已实现盈利对应的市场定价，但受周期波动影响大。 | No |
| V_PE_FY1 | PE FY1 | FY1 一致预期市盈率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | FY1 | N/A | 前瞻 PE。 更关注未来一年盈利的定价，常用于前瞻估值比较。 | No |
| PCT_PE | PCT PE LTM | LTM PE 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | LTM | ICB + Region | 同行横向分位。 - | No |
| PCT_PE_FY1 | PCT PE FY1 | FY1 PE 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| V_PB_LTM | PB LTM | 历史市净率 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | LTM | N/A | 优先 QTR，再回退 SEMI / ANN。 对金融股和资产型行业尤其重要。 | No |
| V_PB_FY1 | Price to Book FY1 | FY1 一致预期市净率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | FY1 | N/A | 前瞻 PB。 - | No |
| V_PTANGB_LTM | PTangibleBook LTM | 历史价格 / 有形账面价值倍数 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | LTM | N/A | 用于非金融股更常见。 剔除无形资产后更适合比较重资产或并购差异大的公司。 | No |
| V_PB_PTANGB_LTM | PB / PTangBook LTM | 行业适配后的历史 PB / PTB 指标 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | LTM | N/A | 金融股取 PB，非金融股取 PTangibleBook。 通过行业分流提高跨行业比较的可用性。 | No |
| V_PB_PTANGB_FY1 | PB / PTangBook FY1 | 行业适配后的 FY1 PB / PTB 指标 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | FY1 | N/A | 金融股取 FY1 PB，非金融股取 FY1 PTangibleBook。 - | No |
| PCT_PB_LTM | PCT PB LTM | 历史 PB / PTB 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | LTM | ICB + Region | 同行横向分位。 - | No |
| PCT_PB_FY1 | PCT PB FY1 | FY1 PB / PTB 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| V_PFCF_LTM | PFCI LTM | 历史价格 / 自由现金流倍数 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | LTM | N/A | 金融股为 NA。 强调股权投资者为自由现金流支付的价格。 | No |
| V_PFCF_FY1 | Price to FreeCF FY1 | FY1 一致预期价格 / 自由现金流倍数 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | FY1 | N/A | 金融股为 NA。 - | No |
| PCT_PFCF_LTM | PCT PFCF LTM | 历史 P/FCF 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | LTM | ICB + Region | 同行横向分位。 - | No |
| PCT_PFCF_FY1 | PCT PFCF FY1 | FY1 P/FCF 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| V_EVEBITDA_LTM | EV to EBITDA LTM | 历史 EV / EBITDA | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | LTM | N/A | 金融股为 NA。 常用于资本结构不同公司的可比估值。 | No |
| V_EVEBITDA_FY1 | EV to EBITDA FY1 | FY1 EV / EBITDA | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Derived | FY1 | N/A | 使用自定义 EV 除以前瞻 EBITDA 预期。 - | No |
| PCT_EVEBITDA_LTM | PCT EVEBITDA LTM | 历史 EV / EBITDA 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | LTM | ICB + Region | 同行横向分位。 - | No |
| PCT_EVEBITDA_FY1 | PCT EVEBITDA FY1 | FY1 EV / EBITDA 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| V_EVEBIT_FY1 | EV to Ebit FY1 | FY1 EV / EBIT | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | FY1 | N/A | 前瞻 EBIT 倍数。 比 EV/EBITDA 更接近经营利润口径，但更受折旧政策影响。 | No |
| PCT_EVEBIT_FY1 | PCT EVEBIT FY1 | FY1 EV / EBIT 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| V_EVSALES_FY1 | EV to Sales FY1 | FY1 EV / Sales | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | FY1 | N/A | 前瞻销售倍数。 适合盈利不稳定但收入可比的行业。 | No |
| PCT_EVSALES_FY1 | PCT EV to Sales FY1 | FY1 EV / Sales 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| V_EVSALES_LTM | EV to Sales LTM | 历史 EV / Sales | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | LTM | N/A | 历史销售倍数。 - | No |
| PCT_EVSALES_LTM | PCT EV to Sales LTM | 历史 EV / Sales 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | LTM | ICB + Region | 同行横向分位。 - | No |
| VALUE_AVGP_FWD | Value_Forward_Avg Percentile | 前瞻估值综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | FY1 | ICB + Region | 聚合 FY1 PE、PB / PTB、P/FCF、EV / EBIT、EV / Sales、EV / EBITDA 等分位。 更适合做前瞻选股，因为底层大多是 FY1 预期倍数。 | No |
| VALUE_AVGP_HIST | Value_Spot_Avg Percentile | 历史 / 现值估值综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | LTM | ICB + Region | 聚合 LTM / spot 估值分位，建议复核字段别名映射。 更偏“当前交易价格是否昂贵/便宜”的现值判断。 | Yes |
| V_PE_NTM | PE NTM | NTM 一致预期市盈率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | 前瞻 NTM 口径。 - | No |
| PCT_PE_NTM | PCT PE NTM | NTM PE 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| V_PB_NTM | Price to Book NTM | NTM 一致预期市净率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | 前瞻 NTM 口径。 - | No |
| V_PB_PTANGB_NTM | PB / PTangibleBook NTM | 行业适配后的 NTM PB / PTB 指标 | 直接读取静态属性字段，用于分类、分组或展示。 | Raw | NTM | N/A | 当前行业分流逻辑建议单独复核。 如果行业分流逻辑正确，它应服务于跨行业可比估值；当前公式需复核。 | Yes |
| PCT_PB_NTM | PCT PB NTM | NTM PB / PTB 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| V_PFCF_NTM | Price to FreeCF NTM | NTM 一致预期 P/FCF | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | 金融股为 NA。 - | No |
| PCT_PFCF_NTM | PCT PFCF NTM | NTM P/FCF 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| V_EVEBITDA_NTM | EV TO EBITDA NTM | NTM EV / EBITDA | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Derived | NTM | N/A | 自定义 EV 除以 NTM EBITDA 预期。 - | No |
| PCT_EVEBITDA_NTM | PCT EVEBITDA NTM | NTM EV / EBITDA 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| V_EVEBIT_NTM | FE Val Ev_Ebit Mean NTM | NTM EV / EBIT | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | NTM | N/A | NTM EBIT 倍数。 - | No |
| PCT_EVEBIT_NTM | PCT EVEBIT NTM | NTM EV / EBIT 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| V_EVSALES_NTM | EV to Sales NTM | NTM EV / Sales | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | NTM | N/A | NTM 销售倍数。 - | No |
| PCT_EVSALES_NTM | PCT EV to Sales NTM | NTM EV / Sales 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| VALUE_AVGP_FWD_NTM | Value_NTM Avg Percentile | NTM 估值综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | NTM | ICB + Region | 聚合 NTM PE、PB / PTB、P/FCF、EV / EBIT、EV / Sales、EV / EBITDA 等分位。 用于把多种 NTM 估值口径收敛成一个排序信号。 | No |

## 五、质量因子（QUALITY）

| Ref | Heading | Business Definition | Formula Summary | Raw or Derived | Horizon | Compare Group | Notes | Review Flag |
|---|---|---|---|---|---|---|---|---|
| Q_ROE_0 | ROE avg FY0 | 当前口径 ROE | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | FY0 | N/A | 优先 QTR，再回退 SEMI / ANN。 衡量股东资本使用效率，但会受到杠杆影响。 | No |
| PCT_Q_ROE | PCT ROE | ROE 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| Q_NDEBITDA0 | NetDebt to EBITDA exFIN | 非金融股净债务 / EBITDA | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 金融股为 NA。 债务负担越低，通常意味着财务弹性越强。 | No |
| PCT_Q_NDEBITDA0 | PCT NBEBITDA | 净债务 / EBITDA 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| Q_OM_0 | Oper Margin | 营业利润率 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | LTM | N/A | 优先 LTM，再回退 LTM_SEMI / ANN。 营业利润率体现商业模式定价力与成本控制能力。 | No |
| PCT_Q_OM_0 | PCT OM FY0 | 营业利润率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY0 | ICB + Region | 同行横向分位。 - | No |
| Q_ASTO_0 | Asset TO exFIN | 非金融股资产周转率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 金融股为 NA。 资产周转率体现资产使用效率。 | No |
| PCT_Q_ASTO_0 | PCT Asset TO | 资产周转率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| Q_T1 | TIER1 Ratio FY0 | Tier1 资本充足率 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | FY0 | N/A | 优先前瞻估计，否则回退当前实际值。 是银行资本稳健性的核心约束指标之一。 | No |
| PCT_Q_T1 | PCT TIER1 | Tier1 比率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| Q_ROTE | ROTE avg FY1 | FY1 ROTE 一致预期 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | FY1 | N/A | 主要用于金融股。 对银行更有解释力，因为剔除了无形资产影响。 | No |
| PCT_Q_ROTE | PCT ROTE | ROTE 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| Q_CR | Combined Ratio FY1 | FY1 Combined Ratio 一致预期 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Derived | FY1 | N/A | 主要用于保险股。 保险公司 Combined Ratio 越低通常越好。 | No |
| PCT_Q_CR | PCT CombinedRatio | Combined Ratio 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| Q_CR_NTM | Combined Ratio NTM | NTM Combined Ratio 一致预期 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Derived | NTM | N/A | 主要用于保险股。 用于观察未来承保盈利是否改善。 | No |
| Q_ROTE_NTM | ROTE avg NTM | NTM ROTE 一致预期 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | 主要用于金融股。 - | No |
| PCT_Q_CR_NTM | PCT CombinedRatio NTM | NTM Combined Ratio 分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |

## 六、分红因子（DIVIDEND）

| Ref | Heading | Business Definition | Formula Summary | Raw or Derived | Horizon | Compare Group | Notes | Review Flag |
|---|---|---|---|---|---|---|---|---|
| Z_DVDYIELD_0 | DVD Yield FY0 | 当前股息率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | FY0 | N/A | 由 DPS / 价格计算。 直接衡量当前股息回报吸引力。 | No |
| Z_SLOPE | DPS 5Y Slope | 近 5 年 DPS 趋势斜率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 用于刻画分红增长趋势。 斜率越高说明长期分红上升趋势越明显。 | No |
| Z_R2 | DPS 5Y R2 | 近 5 年 DPS 趋势回归拟合优度 | 将趋势斜率与拟合稳定性结合，刻画历史增长质量。 | Derived | Spot | N/A | 为趋势稳定度的一部分。 R2 越高，说明分红路径越平滑、可预测。 | No |
| Z_DPSTREND | DPS TrendStab | DPS 趋势稳定度 | 将趋势斜率与拟合稳定性结合，刻画历史增长质量。 | Derived | Spot | N/A | 通常可理解为斜率 × 稳定度。 把“增长速度”和“稳定性”合并，避免只看高增长但波动大的分红。 | No |
| Z_PAYOUT0 | DVD Payout FY0 | 当前派息率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | FY0 | N/A | 分红可持续性指标。 派息率过高可能意味着分红不可持续。 | No |
| Z_DVDYIELD_FY1 | DVD Yield FY1 | FY1 股息率 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | FY1 | N/A | 缺失时回退 FY0 股息率。 更能代表未来一年股东现金回报。 | No |
| Z_DPS_GR_FY1 | DPS 1Y Growth FY1 | FY1 DPS 增长率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | FY1 | N/A | 一致预期口径。 分红成长性指标，适合收益型策略筛选。 | No |
| Z_DPS_FY1 | DPS FY1 | FY1 DPS 水平 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | FY1 | N/A | 一致预期口径。 - | No |
| PCT_Z_DPSTREND | D_DPS TrendStab | DPS 趋势稳定度分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| PCT_Z_PAYOUT | PCT Payout Ratio | 派息率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| PCT_Z_DPS_GR_FY1 | PCT DPS GR FY1 | FY1 DPS 增长率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| PCT_Z_DVDYIELD_FY1 | PCT DvdYield FY1 | FY1 股息率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| Z_EY_0 | Earns Yield FY0 | 当前收益率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | FY0 | N/A | 近似为 EPS / Price。 收益率高往往意味着估值较低，但也可能反映盈利风险。 | No |
| Z_EY_FY1 | Earns Yield FY1 | FY1 收益率 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | FY1 | N/A | 缺失时回退 FY0。 - | No |
| Z_DVDYIELD_NTM | DVD Yield NTM | NTM 股息率 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | NTM | N/A | 缺失时回退 FY0。 用于把股息视角前移到未来 12 个月。 | No |
| Z_DPS_GR_NTM | DPS 1Y Growth NTM | NTM DPS 增长率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | 一致预期口径。 - | No |
| Z_DPS_NTM | DPS NTM | NTM DPS 水平 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | 一致预期口径。 - | No |
| PCT_Z_DPS_GR_NTM | PCT DPS GR NTM | NTM DPS 增长率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| PCT_Z_DVDYIELD_NTM | PCT DvdYield NTM | NTM 股息率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| Z_EY_NTM | Earns Yield NTM | NTM 收益率 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | NTM | N/A | 缺失时回退 FY0。 与 NTM PE 互为近似倒数。 | No |

## 七、成长因子（GROWTH）

| Ref | Heading | Business Definition | Formula Summary | Raw or Derived | Horizon | Compare Group | Notes | Review Flag |
|---|---|---|---|---|---|---|---|---|
| G_SALESGR_FY1 | Sales Growth FY1 | FY1 销售增长率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | FY1 | N/A | 一致预期口径。 销售增长反映需求扩张与份额变化。 | No |
| PCT_G_SALESGR_FY1 | PCT Sales Growth FY1 | FY1 销售增长率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| G_GI_CHECK | Gross Income check | 毛利 / EBIT 可用性检查值 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 用于决定优先使用毛利还是 EBIT 增长。 用于决定增长指标应优先锚定毛利还是经营利润。 | No |
| G_GIGR_FY1 | Gross Income Growth FY1 | FY1 毛利 / 营业利润增长率 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | FY1 | N/A | 毛利不可用时回退 EBIT 增长。 比销售增长更接近经营杠杆释放情况。 | No |
| PCT_G_GIGR_FY1 | PCT Gross Income Grow | FY1 毛利 / 营业利润增长率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| G_EPSGR_FY1_CHECK | EPS Growth FY1 check | EPS FY1 增长检查值 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | FY1 | N/A | 用于判断异常值或负基数问题。 - | No |
| G_EPSGR_FY1 | EPS Growth FY1 | FY1 EPS 增长率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | FY1 | N/A | 一致预期口径，异常值时可置 NA。 直接反映股东层面盈利增长预期。 | No |
| PCT_G_EPSGR_FY1 | PCT EPS Growth FY1 | FY1 EPS 增长率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY1 | ICB + Region | 同行横向分位。 - | No |
| G_HIST_EPS_SLOPE | 5Y_Hist EPS TrendStab Slope | 历史 EPS 趋势斜率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 历史增长稳定度构件。 - | No |
| G_HIST_EPS_R2 | 5Y_Hist EPS TrendStab R2 | 历史 EPS 趋势拟合优度 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 历史增长稳定度构件。 - | No |
| G_HIST_EPS | PCT Hist EPS | 历史 EPS 趋势稳定度原值 | 将趋势斜率与拟合稳定性结合，刻画历史增长质量。 | Derived | Hist | N/A | 并非严格 percentile，建议复核命名。 用趋势斜率与稳定性近似刻画“历史盈利成长质量”。 | Yes |
| PCT_G_HIST_EPS | PCT Hist EPS | 历史 EPS 趋势稳定度分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Hist | ICB + Region | 依赖字段命名建议复核。 - | Yes |
| G_HIST_GI_SLOPE | 5Y_Hist GrossInc TrendStab Slope | 历史毛利 / EBIT 趋势斜率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 历史增长稳定度构件。 - | No |
| G_HIST_GI_R2 | 5Y_Hist GrossInc TrendStab R2 | 历史毛利 / EBIT 趋势拟合优度 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 历史增长稳定度构件。 - | No |
| G_OIPS_CHECK | Op Income per share chg | 营业利润每股变化检查值 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 用于历史毛利 / EBIT 趋势判断。 - | No |
| G_HIST_GI | 5Y_Hist GrossInc TrendStab | 历史毛利 / EBIT 趋势稳定度原值 | 将趋势斜率与拟合稳定性结合，刻画历史增长质量。 | Derived | Hist | N/A | 通常为 slope × R2，特殊情况下可直接返回检查值。 衡量历史经营利润增长是否持续且稳定。 | No |
| PCT_G_HIST_GI | PCT Hist GrossInc | 历史毛利 / EBIT 趋势稳定度分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Hist | ICB + Region | 同行横向分位。 - | No |
| G_HIST_SALES_SLOPE | 5Y_Hist Sales Slope | 历史销售趋势斜率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 历史增长稳定度构件。 - | No |
| G_HIST_SALES_R2 | 5Y_Hist Sales TrendStab R2 | 历史销售趋势拟合优度 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 历史增长稳定度构件。 - | No |
| G_CGR_CHECK | cgr check | 历史销售 CAGR 检查值 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 校验列。 - | No |
| G_HIST_SALES | 5Y_Hist Sales TrendStab | 历史销售趋势稳定度原值 | 将趋势斜率与拟合稳定性结合，刻画历史增长质量。 | Derived | Hist | N/A | 通常为 slope × R2。 衡量历史收入扩张是否平滑可持续。 | No |
| PCT_G_HIST_SALES | PCT Hist Sales | 历史销售趋势稳定度分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Hist | ICB + Region | 同行横向分位。 - | No |
| GROWTH_AVGP_FWD | Growth_Forward_Avg Percentile | FY1 前瞻成长综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | FY1 | ICB + Region | 聚合 FY1 销售、毛利 / EBIT、EPS 增长分位。 把收入、利润和 EPS 三个层面的前瞻增长整合成单一信号。 | No |
| GROWTH_AVGP_HIST | Growth_Historical_Avg Percentile | 历史成长综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | Hist | ICB + Region | 聚合历史 EPS、销售、毛利 / EBIT 趋势分位。 强调历史增长质量，而不是单年高增长。 | No |
| G_SALESGR_NTM | Sales Growth NTM | NTM 销售增长率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | 一致预期口径。 更短视角地观察未来一年收入扩张。 | No |
| G_EPSGR_NTM | EPS Growth NTM | NTM EPS 增长率 | 基于 FactSet 一致预期数据计算对应前瞻指标。 | Raw | NTM | N/A | 一致预期口径，异常值时可置 NA。 - | No |
| PCT_G_SALESGR_NTM | PCT Sales Growth NTM | NTM 销售增长率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| G_GIGR_NTM | Gross Income Growth NTM | NTM 毛利 / 营业利润增长率 | 按可得性优先级取数，主字段缺失时回退至备用字段。 | Derived | NTM | N/A | 毛利不可用时回退 EBIT 增长。 观察未来一年利润端改善。 | No |
| PCT_G_GIGR_NTM | PCT Gross Income Grow | NTM 毛利 / 营业利润增长率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| PCT_G_EPSGR_NTM | PCT EPS Growth NTM | NTM EPS 增长率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | NTM | ICB + Region | 同行横向分位。 - | No |
| GROWTH_AVGP_NTM | Growth_NTM_Avg Percentile | NTM 前瞻成长综合分 | 对多个底层分项进行平均或加权平均，形成综合因子分数。 | Derived | NTM | ICB + Region | 聚合 NTM 销售、毛利 / EBIT、EPS 增长分位。 适合中短期前瞻成长排序。 | No |

## 八、低波与规模因子

| Ref | Heading | Business Definition | Formula Summary | Raw or Derived | Horizon | Compare Group | Notes | Review Flag |
|---|---|---|---|---|---|---|---|---|
| V_60J | Daily Vol 60J | 约 60 日 / 3 个月历史波动率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 基于周频总回报标准差年化。 反映短期价格波动，易受事件冲击影响。 | No |
| PCT_V_60J | PCT DVol 60J | 60 日 / 3 个月波动率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| V_90J | Daily Vol 90J | 约 90 日 / 6 个月历史波动率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 基于周频总回报标准差年化。 中短期波动率，比 60J 更平滑。 | No |
| PCT_V_90J | PCT DVol 90J | 90 日 / 6 个月波动率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| V_1Y | Daily Vol 260J | 约 1 年历史波动率 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Hist | N/A | 基于周频总回报标准差年化。 更接近长期历史风险水平。 | No |
| PCT_V_1Y | PCT DVol 260J | 1 年波动率分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 同行横向分位。 - | No |
| MK_SALES | Log Sales | 销售额对数值 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 规模原始值之一。 对数化后可降低超大市值或超大收入公司的极端影响。 | No |
| PCT_MK_SALES | PCT Sales FY0 | 销售规模分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY0 | ICB + Region | 同行横向分位。 - | No |
| MK_ASSETS | Log Assets | 总资产对数值 | 根据对应 FactSet 字段或组合逻辑生成该列。 | Raw | Spot | N/A | 规模原始值之一。 适合金融和重资产行业的规模比较。 | No |
| PCT_MK_ASSETS | PCT Assets FY0 | 资产规模分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | FY0 | ICB + Region | 同行横向分位。 - | No |
| MKVAL | Log Market Value | 市值对数值 | 读取评价日市值或相关规模字段。 | Raw | Spot | N/A | 规模原始值之一。 是规模风格暴露最直接的代理变量。 | No |
| PCT_MKVAL | PCT Mkt Value | 市值规模分位分数 | 将底层指标按同业组转换为横向分位得分。 | Derived | Spot | ICB + Region | 亦作为最终 Size 总分使用。 常用于构建大盘/小盘风格排序。 | No |

## 九、基准权重字段

| Ref | Heading | Business Definition | Formula Summary | Raw or Derived | Horizon | Compare Group | Notes | Review Flag |
|---|---|---|---|---|---|---|---|---|
| DJ_BROOKFIELD_WGT | Weight in DJ BROOKFIELD | DJ BROOKFIELD 中的权重 | 读取评价日在对应基准中的成份权重。 | Raw | Spot | N/A | 评价日成份权重。 用于识别标的在特定基础设施基准中的重要性。 | No |
| GLOBAL_INFRA_WGT | Weight in GLOBAL INFRA | GLOBAL INFRA 中的权重 | 读取评价日在对应基准中的成份权重。 | Raw | Spot | N/A | 评价日成份权重。 可用于基础设施主题暴露分析。 | No |
| GLOBAL_REIT_WGT | Weight in GLOBAL REIT | GLOBAL REIT 中的权重 | 读取评价日在对应基准中的成份权重。 | Raw | Spot | N/A | 评价日成份权重。 可用于 REIT 暴露及地产主题分析。 | No |
| MSCI_ACWI_WGT | Weight in MSCI ACWI | MSCI ACWI 中的权重 | 读取评价日在对应基准中的成份权重。 | Raw | Spot | N/A | 评价日成份权重。 可作为全球广义基准的权重锚。 | No |
| MSCI_EM_WGT | Weight in MSCI EM | MSCI EM 中的权重 | 读取评价日在对应基准中的成份权重。 | Raw | Spot | N/A | 评价日成份权重。 可用于新兴市场暴露识别。 | No |
| MSCI_EUR_SMALL_WGT | Weight in MSCI EUR SMALL | MSCI EUR SMALL 中的权重 | 读取评价日在对应基准中的成份权重。 | Raw | Spot | N/A | 评价日成份权重。 可用于欧洲小盘暴露识别。 | No |
