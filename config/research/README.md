# 配置化研究

`hypotheses/*.json` 是 Hypothesis Registry，也是可执行研究模板。每个定义固定研究命题、PIT 规则、成本、试验族、版本和唯一正常 Python 包入口。

```powershell
tp-research validate
tp-research list
tp-research run cross-market-lag6-relative -- --market sp500
```

运行器管理输出目录，并将结果和 Run Card v3 写入
`artifacts/research/runs/<hypothesis-id>/<run-id>/`。成功运行默认仍为
`review_required`，不得绕过独立晋升门。
