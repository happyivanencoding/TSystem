"""Plot US 2022+ regime-risk model predictions against realized risk."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

import matplotlib
import pandas as pd
from matplotlib.dates import YearLocator
from matplotlib.ticker import FuncFormatter

from tp_models.regime import vol_compare

matplotlib.use("Agg")
from matplotlib import pyplot as plt

EXPERIMENT_VERSION = "tp.regime.direct_risk_model_plots:1.0.0"
DEFAULT_PREDICTIONS = Path(
    "artifacts/research/runs/regime-direct-risk-challengers-v3/"
    "20260726T221731Z-7244585e/results/"
    "walkforward_predictions.parquet"
)
TARGETS = ("fwd_vol", "fwd_mdd")
LEVEL_MODELS = {
    "fwd_vol": (
        "volatility_persistence",
        "current_hmm",
        "ridge",
        "elastic_net",
        "stacked_meta_model",
    ),
    "fwd_mdd": (
        "current_hmm",
        "ridge",
        "elastic_net",
        "stacked_meta_model",
    ),
}
PERCENTILE_MODELS = (
    "volatility_persistence",
    "current_hmm",
    "ridge",
    "elastic_net",
    "logistic",
    "ridge_logistic_ensemble",
    "stacked_meta_model",
)
LABELS = {
    "actual": "实际",
    "volatility_persistence": "波动持续性",
    "current_hmm": "当前 HMM",
    "ridge": "Ridge",
    "elastic_net": "Elastic Net",
    "logistic": "Logistic",
    "ridge_logistic_ensemble": "Ridge＋Logistic",
    "stacked_meta_model": "Stack",
}
STYLES = {
    "actual": {"color": "#23262D", "linestyle": "-", "linewidth": 2.8},
    "stacked_meta_model": {
        "color": "#246BCE",
        "linestyle": "-",
        "linewidth": 2.2,
    },
    "elastic_net": {
        "color": "#C58A08",
        "linestyle": "--",
        "linewidth": 1.8,
    },
    "ridge": {
        "color": "#D66B22",
        "linestyle": ":",
        "linewidth": 1.6,
    },
    "volatility_persistence": {
        "color": "#6F7D32",
        "linestyle": "-.",
        "linewidth": 1.6,
    },
    "current_hmm": {
        "color": "#C04E86",
        "linestyle": (0, (5, 3)),
        "linewidth": 1.5,
    },
    "logistic": {
        "color": "#7A7F89",
        "linestyle": (0, (2, 2)),
        "linewidth": 1.4,
    },
    "ridge_logistic_ensemble": {
        "color": "#A5A9B0",
        "linestyle": (0, (7, 3)),
        "linewidth": 1.4,
    },
}


def _prepare_comparison_data(
    predictions_path: Path,
    *,
    region: str,
    start: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    predictions = pd.read_parquet(predictions_path)
    predictions["Date"] = pd.to_datetime(predictions["Date"])
    predictions = predictions[
        predictions["region"].eq(region)
        & predictions["Date"].ge(start)
    ].copy()
    actual = vol_compare.fwd_risk(region)
    actual.index = pd.to_datetime(actual.index)

    rows: list[dict[str, object]] = []
    checks: dict[str, object] = {}
    for target in TARGETS:
        selected = predictions[predictions["target"].eq(target)]
        pivot = selected.pivot(
            index="Date",
            columns="model",
            values="prediction",
        )
        joined = pivot.join(actual[target].rename("actual"), how="inner")
        joined = joined.loc[joined.index >= pd.Timestamp(start)]
        actual_values = joined["actual"].dropna()
        checks[target] = {
            "actual_months": len(actual_values),
            "start": str(actual_values.index.min().date()),
            "end": str(actual_values.index.max().date()),
        }

        for model_name in ("actual", *LEVEL_MODELS[target]):
            for date, value in joined[model_name].dropna().items():
                rows.append(
                    {
                        "Date": date,
                        "target": target,
                        "view": "risk_level",
                        "model": model_name,
                        "series": LABELS[model_name],
                        "value": float(value) * 100,
                        "raw_value": float(value),
                        "actual_raw": float(joined.loc[date, "actual"]),
                    }
                )

        for model_name in ("actual", *PERCENTILE_MODELS):
            values = joined[model_name].dropna()
            percentiles = values.rank(method="average", pct=True) * 100
            for date, percentile in percentiles.items():
                rows.append(
                    {
                        "Date": date,
                        "target": target,
                        "view": "sample_percentile",
                        "model": model_name,
                        "series": LABELS[model_name],
                        "value": float(percentile),
                        "raw_value": float(values.loc[date]),
                        "actual_raw": float(joined.loc[date, "actual"]),
                    }
                )
    return pd.DataFrame(rows), checks


def _plot_panel(
    axis: plt.Axes,
    data: pd.DataFrame,
    *,
    title: str,
    subtitle: str,
    y_label: str,
    y_limits: tuple[float, float] | None = None,
) -> None:
    for model_name in data["model"].drop_duplicates():
        series = data[data["model"].eq(model_name)].sort_values("Date")
        style = STYLES[model_name]
        axis.plot(
            series["Date"],
            series["value"],
            label=LABELS[model_name],
            markevery=4 if model_name in ("actual", "stacked_meta_model") else None,
            marker="o" if model_name in ("actual", "stacked_meta_model") else None,
            markersize=2.8,
            **style,
        )
    axis.set_title(title, loc="left", fontsize=13, weight="bold", pad=20)
    axis.text(
        0,
        1.015,
        subtitle,
        transform=axis.transAxes,
        fontsize=9,
        color="#626873",
        va="bottom",
    )
    axis.set_ylabel(y_label)
    axis.grid(axis="y", color="#E3E6EA", linewidth=0.8)
    axis.grid(axis="x", visible=False)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#B9BEC6")
    axis.xaxis.set_major_locator(YearLocator())
    axis.tick_params(axis="both", colors="#555B65", labelsize=9)
    if y_limits is not None:
        axis.set_ylim(*y_limits)
    axis.legend(
        loc="upper right",
        frameon=False,
        fontsize=8,
        ncol=2,
    )


def _render_figure(
    comparison: pd.DataFrame,
    output_path: Path,
    *,
    region: str,
    checks: dict[str, object],
) -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Microsoft YaHei",
                "SimHei",
                "Arial",
                "DejaVu Sans",
            ],
            "axes.labelcolor": "#353A43",
            "text.color": "#252A32",
        }
    )
    figure, axes = plt.subplots(2, 2, figsize=(20, 13), dpi=160)
    figure.patch.set_facecolor("#FAFBFC")
    for axis in axes.flat:
        axis.set_facecolor("#FFFFFF")

    _plot_panel(
        axes[0, 0],
        comparison[
            comparison["target"].eq("fwd_vol")
            & comparison["view"].eq("risk_level")
        ],
        title="下一月已实现波动：预测与实际",
        subtitle="原始风险水平；概率/分数模型不放入本图",
        y_label="年化波动率（%）",
    )
    _plot_panel(
        axes[0, 1],
        comparison[
            comparison["target"].eq("fwd_mdd")
            & comparison["view"].eq("risk_level")
        ],
        title="下一月最大回撤：预测与实际",
        subtitle="原始风险水平；波动持续性因量纲不同不放入本图",
        y_label="最大回撤（%）",
    )
    _plot_panel(
        axes[1, 0],
        comparison[
            comparison["target"].eq("fwd_vol")
            & comparison["view"].eq("sample_percentile")
        ],
        title="下一月已实现波动：统一百分位比较",
        subtitle="各序列按自身 2022+ 样本排名，仅用于形态对比",
        y_label="样本百分位",
        y_limits=(0, 102),
    )
    _plot_panel(
        axes[1, 1],
        comparison[
            comparison["target"].eq("fwd_mdd")
            & comparison["view"].eq("sample_percentile")
        ],
        title="下一月最大回撤：统一百分位比较",
        subtitle="各序列按自身 2022+ 样本排名，仅用于形态对比",
        y_label="样本百分位",
        y_limits=(0, 102),
    )
    axes[1, 0].yaxis.set_major_formatter(
        FuncFormatter(lambda value, _: f"{value:.0f}")
    )
    axes[1, 1].yaxis.set_major_formatter(
        FuncFormatter(lambda value, _: f"{value:.0f}")
    )

    start = checks["fwd_vol"]["start"]
    end = checks["fwd_vol"]["end"]
    months = checks["fwd_vol"]["actual_months"]
    figure.suptitle(
        f"{region} Regime 风险模型：预测与实际",
        x=0.055,
        y=0.985,
        ha="left",
        fontsize=21,
        weight="bold",
    )
    figure.text(
        0.055,
        0.952,
        f"{start} 至 {end}｜月频｜{months} 个已有实际结果的月份",
        fontsize=10.5,
        color="#606671",
    )
    figure.text(
        0.945,
        0.976,
        "TP RESEARCH",
        ha="right",
        va="top",
        fontsize=9,
        weight="bold",
        color="#246BCE",
    )
    figure.text(
        0.055,
        0.018,
        (
            "注：预测月 t 的模型仅使用当时可见信息；实际值为其后一月实现风险。"
            "MS-AR 因固定版本未可靠收敛而不作为正常候选线。百分位使用完整"
            " 2022+ 样本，仅供回溯可视化，不是训练输入或新的 OOS 证据。"
        ),
        fontsize=9,
        color="#656B75",
    )
    figure.tight_layout(rect=(0.045, 0.055, 0.96, 0.925), h_pad=3.2, w_pad=2.2)
    figure.savefig(output_path, bbox_inches="tight")
    plt.close(figure)


def run(
    output_dir: Path,
    *,
    predictions_path: Path,
    region: str,
    start: str,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = predictions_path.resolve()
    if not predictions_path.is_file():
        raise FileNotFoundError(predictions_path)
    comparison, checks = _prepare_comparison_data(
        predictions_path,
        region=region,
        start=start,
    )
    if any(checks[target]["actual_months"] < 8 for target in TARGETS):
        raise ValueError("At least eight actual monthly points are required")

    data_path = output_dir / "model_prediction_actual_chart_data.csv"
    image_path = output_dir / "us_2022_model_prediction_actual_comparison.png"
    comparison.to_csv(data_path, index=False, encoding="utf-8-sig")
    _render_figure(
        comparison,
        image_path,
        region=region,
        checks=checks,
    )
    manifest = {
        "status": "complete",
        "experiment_version": EXPERIMENT_VERSION,
        "source_predictions": str(predictions_path),
        "region": region,
        "start": start,
        "checks": checks,
        "rows": len(comparison),
        "plots": [image_path.name],
        "data": data_path.name,
        "interpretation_boundary": (
            "post_hoc_visualization_only_not_new_model_selection_evidence"
        ),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--predictions",
        type=Path,
        default=DEFAULT_PREDICTIONS,
    )
    parser.add_argument("--region", default="US")
    parser.add_argument("--start", default="2022-01-01")
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest = run(
        Path(args.output_dir),
        predictions_path=args.predictions,
        region=args.region,
        start=args.start,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
