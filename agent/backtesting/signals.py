"""Sinais da Configuração A, vetorizados.

Mesmas regras de `agent.quant.setups.find_setups` para `breakout_20d` e `reclaim_ma20`
(um teste confere a equivalência ponto a ponto). O valor no dia t usa só fechamentos até t.
"""
from __future__ import annotations

import pandas as pd

from agent.quant.setups import MIN_CLOSES

SETUPS_A = ("breakout_20d", "reclaim_ma20")


def setup_signals(close: pd.Series) -> pd.DataFrame:
    c = close.astype(float)
    high20_prev = c.shift(1).rolling(20, min_periods=20).max()
    ma20 = c.rolling(20, min_periods=20).mean()
    ma20_prev = ma20.shift(1)
    out = pd.DataFrame(index=c.index)
    out["breakout_20d"] = c > high20_prev
    out["reclaim_ma20"] = (c.shift(1) < ma20_prev) & (c > ma20)
    enough = pd.Series(range(1, len(c) + 1), index=c.index) >= MIN_CLOSES
    return out & enough.to_numpy()[:, None]


def entry_signal(close: pd.Series, setups=SETUPS_A) -> pd.Series:
    sig = setup_signals(close)
    return sig[list(setups)].any(axis=1)
