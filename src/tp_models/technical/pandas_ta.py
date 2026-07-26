"""Minimal local pandas_ta compatibility layer for TP technical notebooks.

The original project expected the external `pandas_ta` package.  To keep the
production notebook executable in the managed TP environment, this module
implements only the indicators used by `utils.py`, with pandas-native formulas
and pandas_ta-like column names.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(close: pd.Series, length: int = 10) -> pd.Series:
    return close.astype(float).ewm(span=length, adjust=False, min_periods=length).mean()


def fwma(close: pd.Series, length: int = 10) -> pd.Series:
    weights = np.arange(1, length + 1, dtype=float)
    denom = weights.sum()
    return close.astype(float).rolling(length).apply(lambda x: float(np.dot(x, weights) / denom), raw=True)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    close = close.astype(float)
    macd_line = close.ewm(span=fast, adjust=False, min_periods=fast).mean() - close.ewm(
        span=slow, adjust=False, min_periods=slow
    ).mean()
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    suffix = f"{fast}_{slow}_{signal}"
    return pd.DataFrame(
        {
            f"MACD_{suffix}": macd_line,
            f"MACDh_{suffix}": hist,
            f"MACDs_{suffix}": signal_line,
        },
        index=close.index,
    )


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    close = close.astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def rvi(close: pd.Series, length: int = 14) -> pd.Series:
    close = close.astype(float)
    change = close.diff()
    std = close.rolling(length).std()
    up = std.where(change > 0, 0.0).rolling(length).mean()
    down = std.where(change <= 0, 0.0).rolling(length).mean()
    return 100 * up / (up + down).replace(0, np.nan)


class _Momentum:
    @staticmethod
    def mom(close: pd.Series, length: int = 10) -> pd.Series:
        return close.astype(float).diff(length)


momentum = _Momentum()


def entropy(close: pd.Series, length: int = 10) -> pd.Series:
    close = close.astype(float)
    pct = close.pct_change().abs()

    def _entropy(values: np.ndarray) -> float:
        values = values[np.isfinite(values)]
        total = values.sum()
        if total <= 0:
            return np.nan
        probs = values / total
        return float(-(probs * np.log(probs + 1e-12)).sum())

    return pct.rolling(length).apply(_entropy, raw=True)


def skew(close: pd.Series, length: int = 30) -> pd.Series:
    return close.astype(float).rolling(length).skew()


def psar(
    high: pd.Series,
    low: pd.Series,
    step: float = 0.02,
    maximum: float = 0.2,
) -> pd.DataFrame:
    # Lightweight trend proxy: rolling extrema.  It preserves expected columns
    # for downstream ranking/visualisation without depending on external code.
    high = high.astype(float)
    low = low.astype(float)
    window = max(2, int(round(maximum / step)))
    suffix = f"{step}_{maximum}"
    return pd.DataFrame(
        {
            f"PSARl_{suffix}": low.rolling(window).min(),
            f"PSARs_{suffix}": high.rolling(window).max(),
            f"PSARaf_{suffix}": float(step),
            f"PSARr_{suffix}": 0,
        },
        index=high.index,
    )


def bbands(close: pd.Series, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    close = close.astype(float)
    middle = close.rolling(length).mean()
    sigma = close.rolling(length).std()
    upper = middle + std * sigma
    lower = middle - std * sigma
    bandwidth = (upper - lower) / middle.replace(0, np.nan)
    percent = (close - lower) / (upper - lower).replace(0, np.nan)
    suffix = f"{length}_{std}"
    return pd.DataFrame(
        {
            f"BBL_{suffix}": lower,
            f"BBM_{suffix}": middle,
            f"BBU_{suffix}": upper,
            f"BBB_{suffix}": bandwidth,
            f"BBP_{suffix}": percent,
        },
        index=close.index,
    )


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 14,
) -> pd.Series:
    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def stdev(close: pd.Series, length: int = 10) -> pd.Series:
    return close.astype(float).rolling(length).std()
