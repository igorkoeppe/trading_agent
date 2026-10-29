"""Setups diários portados de `find_setups` em trader-scanner/scan.py do day-trader-skill
(MIT, Jake Schincariol). Mesmas regras, para servir de referência na Configuração A.

Os setups são candidatos, não sinais de compra: a estratégia versionada em strategies/
decide quais usar, e o motor de risco decide se a ordem sai.
"""
from __future__ import annotations

from agent.quant.indicators import rsi_wilder

MIN_CLOSES = 30


def find_setups(closes: list[float]) -> tuple[list[str], dict]:
    """closes: fechamentos diários completos, do mais antigo ao mais recente (>= 30)."""
    c = list(closes)
    if len(c) < MIN_CLOSES:
        raise ValueError(f"são necessários pelo menos {MIN_CLOSES} fechamentos, recebi {len(c)}")
    last = c[-1]
    high20 = max(c[-21:-1])
    ma20 = sum(c[-20:]) / 20.0
    ma20_prev = sum(c[-21:-1]) / 20.0
    run = c[-6] / c[-16] - 1
    range5 = (max(c[-5:]) - min(c[-5:])) / last
    r = rsi_wilder(c)
    r_prev = rsi_wilder(c[:-1])

    tags = []
    if last > high20:
        tags.append("breakout_20d")
    if run > 0.10 and range5 < 0.05:
        tags.append("bull_flag")
    if c[-2] < ma20_prev and last > ma20:
        tags.append("reclaim_ma20")
    if r is not None and r < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        tags.append("oversold_bounce")

    numbers = {
        "rsi": r,
        "rsi_prev": r_prev,
        "high20": high20,
        "ma20": ma20,
        "run_pct": run * 100,
        "range5_pct": range5 * 100,
    }
    return tags, numbers
