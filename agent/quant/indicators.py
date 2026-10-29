"""Indicadores determinísticos sobre séries de fechamento diário.

`rsi_wilder` reproduz a fórmula de `trader-scanner/scan.py` do day-trader-skill
(MIT, Jake Schincariol), para que os resultados possam ser comparados com a referência.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n, min_periods=n).mean()


def rsi_wilder(closes: list[float] | pd.Series, n: int = 14) -> float | None:
    """RSI de Wilder do último ponto. None se houver menos de n + 1 fechamentos."""
    c = list(closes)
    if len(c) < n + 1:
        return None
    gains = [max(0.0, c[i] - c[i - 1]) for i in range(1, len(c))]
    losses = [max(0.0, c[i - 1] - c[i]) for i in range(1, len(c))]
    avg_gain, avg_loss = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def ewma_volatility(close: pd.Series, lam: float = 0.94, annualize: bool = False) -> pd.Series:
    """Volatilidade EWMA (estilo RiskMetrics) dos retornos logarítmicos diários."""
    r = log_returns(close)
    var = (r**2).ewm(alpha=1 - lam, adjust=False).mean()
    vol = np.sqrt(var)
    return vol * math.sqrt(252) if annualize else vol


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range de Wilder sobre candles com colunas high, low, close."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
