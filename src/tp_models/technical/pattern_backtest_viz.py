from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .pattern_backtest_engine import build_next_date_map, get_selection_reason


def make_backtest_figure(result: Any, show_drawdown: bool = True) -> go.Figure:
    nav_df = result.nav_df.copy()
    if nav_df.empty:
        raise ValueError("没有可展示的净值数据。")

    if show_drawdown:
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.7, 0.3],
            subplot_titles=("净值", "回撤"),
        )
    else:
        fig = make_subplots(rows=1, cols=1)

    for col in nav_df.columns:
        fig.add_trace(go.Scatter(x=nav_df.index, y=nav_df[col], mode="lines", name=col), row=1, col=1)

    if nav_df.shape[1] >= 2:
        excess = nav_df.iloc[:, 0] / nav_df.iloc[:, 1] * 100.0
        fig.add_trace(
            go.Scatter(
                x=excess.index,
                y=excess,
                mode="lines",
                name="Relative Strength",
                line=dict(dash="dot"),
            ),
            row=1,
            col=1,
        )

    if show_drawdown:
        for col in nav_df.columns:
            drawdown = nav_df[col] / nav_df[col].cummax() - 1.0
            fig.add_trace(
                go.Scatter(x=drawdown.index, y=drawdown, mode="lines", name=f"{col} Drawdown", showlegend=False),
                row=2,
                col=1,
            )

    fig.update_layout(title="回测表现", height=700 if show_drawdown else 450, hovermode="x unified", template="plotly_white")
    fig.update_yaxes(title_text="Base 100", row=1, col=1)
    if show_drawdown:
        fig.update_yaxes(title_text="Drawdown", tickformat=".0%", row=2, col=1)
    return fig


def make_company_pattern_figure(
    patterns: pd.DataFrame,
    company_sedol: str,
    pattern_columns: Sequence[str],
    pattern_values: dict[str, Any] | None = None,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
) -> go.Figure:
    pattern_values = pattern_values or {}
    df = patterns.reset_index().copy()
    df = df[df["Company SEDOL"] == company_sedol].copy()
    if df.empty:
        raise ValueError(f"未找到公司 {company_sedol} 的 patterns 数据。")

    df["Date"] = pd.to_datetime(df["Date"])
    if start_date is not None:
        df = df[df["Date"] >= pd.to_datetime(start_date)].copy()
    if end_date is not None:
        df = df[df["Date"] <= pd.to_datetime(end_date)].copy()
    if df.empty:
        raise ValueError("筛选日期后没有可展示数据。")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["Date"],
            y=df["Close"],
            mode="lines",
            name="Weekly Close",
            line=dict(color="#1f77b4"),
        )
    )

    for col in pattern_columns:
        if col not in df.columns:
            continue
        hit_mask = _pattern_hit_mask(df[col], pattern_values.get(col))
        hits = df.loc[hit_mask, ["Date", "Close", col]].copy()
        if hits.empty:
            continue
        hits["label"] = hits[col].astype(str)
        fig.add_trace(
            go.Scatter(
                x=hits["Date"],
                y=hits["Close"],
                mode="markers",
                name=col,
                marker=dict(size=9),
                text=hits["label"],
                hovertemplate="Date=%{x}<br>Close=%{y:.2f}<br>Signal=%{text}<extra></extra>",
            )
        )

    fig.update_layout(title=f"{company_sedol} 的 pattern 时间点", template="plotly_white", hovermode="x unified")
    fig.update_yaxes(title_text="Weekly Close")
    return fig


def build_event_study_frame(
    patterns: pd.DataFrame,
    returns: pd.DataFrame,
    pattern_column: str,
    pattern_value: Any | None = None,
    event_window: int = 20,
    max_events: int = 200,
    company_sedols: Sequence[str] | None = None,
    start_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    if pattern_column not in patterns.columns:
        raise KeyError(f"patterns.parquet 中不存在列: {pattern_column}")

    df = patterns.reset_index().copy()
    df["Date"] = pd.to_datetime(df["Date"])
    if start_date is not None:
        df = df[df["Date"] >= pd.to_datetime(start_date)].copy()
    if company_sedols is not None:
        company_sedols = {str(x) for x in company_sedols}
        df = df[df["Company SEDOL"].astype(str).isin(company_sedols)].copy()

    df = df[_pattern_hit_mask(df[pattern_column], pattern_value)].copy()
    if df.empty:
        raise ValueError("没有命中的 pattern 事件。")

    next_date_map = build_next_date_map(patterns["Date"])
    events: list[pd.DataFrame] = []
    event_id = 0

    for _, row in df.head(max_events).iterrows():
        signal_date = pd.Timestamp(row["Date"])
        effective_date = next_date_map.get(signal_date, pd.NaT)
        if pd.isna(effective_date):
            continue

        future_dates = returns.index[returns.index > effective_date]
        if len(future_dates) == 0:
            continue
        exec_date = pd.Timestamp(future_dates[0])

        sedol = str(row["Company SEDOL"])
        if sedol not in returns.columns:
            continue

        post_ret = returns.loc[returns.index > exec_date, sedol].dropna().head(event_window)
        path = pd.Series([1.0], index=[0], dtype=float)
        if not post_ret.empty:
            future_path = (1.0 + post_ret.fillna(0.0)).cumprod()
            future_path.index = range(1, len(future_path) + 1)
            path = pd.concat([path, future_path])

        event_frame = pd.DataFrame(
            {
                "event_id": event_id,
                "horizon": path.index,
                "normalized_price": path.values,
                "Company SEDOL": sedol,
                "Signal Date": signal_date,
                "Effective Date": pd.Timestamp(effective_date),
                "Exec Date": exec_date,
            }
        )
        events.append(event_frame)
        event_id += 1

    if not events:
        raise ValueError("没有可构建的事件路径。")
    return pd.concat(events, ignore_index=True)


def make_event_study_figure(event_frame: pd.DataFrame, title: str | None = None) -> go.Figure:
    if event_frame.empty:
        raise ValueError("事件路径为空。")

    fig = go.Figure()
    for event_id, group in event_frame.groupby("event_id"):
        label = f"{group['Company SEDOL'].iloc[0]} | {group['Signal Date'].iloc[0].date()}"
        fig.add_trace(
            go.Scatter(
                x=group["horizon"],
                y=group["normalized_price"],
                mode="lines",
                line=dict(color="rgba(31, 119, 180, 0.15)"),
                showlegend=False,
                hovertemplate=f"{label}<br>T=%{{x}}<br>Price=%{{y:.3f}}<extra></extra>",
            )
        )

    mean_path = event_frame.groupby("horizon")["normalized_price"].mean()
    median_path = event_frame.groupby("horizon")["normalized_price"].median()
    fig.add_trace(go.Scatter(x=mean_path.index, y=mean_path.values, mode="lines", name="Mean", line=dict(width=3)))
    fig.add_trace(
        go.Scatter(
            x=median_path.index,
            y=median_path.values,
            mode="lines",
            name="Median",
            line=dict(width=3, dash="dash"),
        )
    )

    fig.update_layout(title=title or "Pattern 事件后的价格路径", template="plotly_white", hovermode="x unified")
    fig.update_xaxes(title_text="交易日窗口")
    fig.update_yaxes(title_text="归一化价格")
    return fig


def make_selection_reason_figure(
    selection_pool: pd.DataFrame,
    company_sedol: str,
    effective_date: str | pd.Timestamp,
    top_k: int = 10,
) -> go.Figure:
    reason = get_selection_reason(selection_pool, company_sedol, effective_date, top_k=top_k)
    row = reason["row"]
    peers = reason["peers"].copy()

    component_cols = [col for col in row.index if str(col).startswith("Score::")]
    component_df = pd.DataFrame(
        {
            "metric": [col.replace("Score::", "") for col in component_cols],
            "score": [row[col] for col in component_cols],
            "raw_value": [row.get(col.replace("Score::", ""), np.nan) for col in component_cols],
        }
    ).sort_values("score", ascending=True)
    component_df["raw_value_display"] = component_df["raw_value"].map(_format_component_value)

    peers["label"] = peers["Company SEDOL"]
    fig = make_subplots(rows=1, cols=2, subplot_titles=("分项得分", f"Top {top_k} 排名对比"), horizontal_spacing=0.12)
    fig.add_trace(
        go.Bar(
            x=component_df["score"],
            y=component_df["metric"],
            orientation="h",
            name="Component Score",
            customdata=component_df[["raw_value_display"]],
            hovertemplate="Metric=%{y}<br>Score=%{x:.4f}<br>Raw=%{customdata[0]}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=peers["label"],
            y=peers["Total Score"],
            name="Total Score",
            marker_color=["crimson" if x == company_sedol else "steelblue" for x in peers["Company SEDOL"]],
        ),
        row=1,
        col=2,
    )

    rank_text = row.get("Selection Rank", np.nan)
    rank_value = int(rank_text) if pd.notna(rank_text) else "NA"
    score_text = row.get("Total Score", np.nan)
    score_value = f"{score_text:.4f}" if pd.notna(score_text) else "NA"
    fig.update_layout(
        title=(
            f"{company_sedol} 入选原因 | Date={pd.to_datetime(effective_date).date()} | "
            f"Sector={row.get('Sector', 'Unknown')} | Rank={rank_value} | Score={score_value}"
        ),
        template="plotly_white",
        showlegend=False,
    )
    fig.update_yaxes(title_text="Metric", row=1, col=1)
    fig.update_yaxes(title_text="Total Score", row=1, col=2)
    return fig


def _pattern_hit_mask(series: pd.Series, pattern_value: Any | None) -> pd.Series:
    if pattern_value is not None:
        return series == pattern_value
    if pd.api.types.is_bool_dtype(series):
        return series == True
    return series.notna() & (series.astype(str) != "False") & (series.astype(str) != "None")


def _format_component_value(value: Any) -> str:
    if pd.isna(value):
        return "NA"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (float, np.floating)):
        return f"{value:.4f}"
    return str(value)


__all__ = [
    "build_event_study_frame",
    "make_backtest_figure",
    "make_company_pattern_figure",
    "make_event_study_figure",
    "make_selection_reason_figure",
]
