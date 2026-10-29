"""Métricas e gates da Configuração A (pré-registro v1, `gates_config_A`).

Convenções fixadas aqui, antes de qualquer resultado:
- janelas de teste de 6 meses a partir do fim do treino inicial (2019-01 em diante);
- uma operação pertence à janela da sua DATA DE ENTRADA;
- janela sem operação conta como NÃO positiva;
- IC 90% por bootstrap da média de R: 10.000 reamostras, semente 12345, percentis 5 e 95;
- Sharpe: retornos diários do patrimônio, sem taxa livre de risco, anualizado por raiz de 252;
- benchmark: SPY comprado e mantido, retornos de fechamento a fechamento no mesmo período.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from agent.backtesting.engine import Trade

BOOT_N, BOOT_SEED = 10_000, 12345


def oos_windows(first_test: date, end: date, months: int = 6) -> list[tuple[date, date]]:
    out, s = [], pd.Timestamp(first_test)
    while s.date() <= end:
        e = s + pd.DateOffset(months=months) - pd.Timedelta(days=1)
        out.append((s.date(), min(e.date(), end)))
        s = s + pd.DateOffset(months=months)
    return out


def bootstrap_ci(r: np.ndarray, lo=5.0, hi=95.0) -> tuple[float, float]:
    if len(r) == 0:
        return (math.nan, math.nan)
    rng = np.random.default_rng(BOOT_SEED)
    means = r[rng.integers(0, len(r), size=(BOOT_N, len(r)))].mean(axis=1)
    return float(np.percentile(means, lo)), float(np.percentile(means, hi))


def profit_factor(r: np.ndarray) -> float:
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return math.inf if losses == 0 and gains > 0 else (gains / losses if losses else math.nan)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return math.nan
    return float((1 - equity / equity.cummax()).max())


def sharpe(equity_or_prices: pd.Series) -> float:
    ret = equity_or_prices.pct_change().dropna()
    if len(ret) < 2 or ret.std() == 0:
        return math.nan
    return float(ret.mean() / ret.std() * math.sqrt(252))


@dataclass
class Report:
    n: int
    mean_r: float
    ci90: tuple[float, float]
    profit_factor: float
    max_dd: float
    windows: list[dict]
    frac_windows_positive: float
    sharpe: float
    win_rate: float
    exits: dict

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def report(trades: list[Trade], equity: pd.Series, windows: list[tuple[date, date]]) -> Report:
    r = np.array([t.r_multiple for t in trades], dtype=float)
    rows = []
    for ws, we in windows:
        rw = np.array([t.r_multiple for t in trades if ws <= t.entry_date <= we], dtype=float)
        rows.append({"inicio": str(ws), "fim": str(we), "n": int(len(rw)),
                     "soma_R": float(rw.sum()) if len(rw) else 0.0,
                     "positiva": bool(len(rw) and rw.sum() > 0)})
    exits = pd.Series([t.reason for t in trades]).value_counts().to_dict() if trades else {}
    return Report(
        n=len(r),
        mean_r=float(r.mean()) if len(r) else math.nan,
        ci90=bootstrap_ci(r),
        profit_factor=profit_factor(r) if len(r) else math.nan,
        max_dd=max_drawdown(equity),
        windows=rows,
        frac_windows_positive=sum(w["positiva"] for w in rows) / len(rows) if rows else math.nan,
        sharpe=sharpe(equity),
        win_rate=float((r > 0).mean()) if len(r) else math.nan,
        exits={k: int(v) for k, v in exits.items()},
    )


def evaluate_gates_A(g: dict, base: Report, stress: Report, spy_sharpe: float,
                     n_configs: int, max_configs: int) -> dict[str, dict]:
    def gate(ok, valor, criterio):
        return {"passou": bool(ok), "valor": valor, "criterio": criterio}

    return {
        "G1": gate(base.n >= g["G1_min_operacoes"], base.n, f">= {g['G1_min_operacoes']}"),
        "G2": gate(base.mean_r >= g["G2_expectativa_liquida_R_min"], base.mean_r,
                   f">= {g['G2_expectativa_liquida_R_min']} R"),
        "G3": gate(base.ci90[0] > g["G3_ic90_bootstrap_inferior_R_min"], base.ci90[0],
                   f"> {g['G3_ic90_bootstrap_inferior_R_min']} R"),
        "G4": gate(base.profit_factor >= g["G4_fator_de_lucro_min"], base.profit_factor,
                   f">= {g['G4_fator_de_lucro_min']}"),
        "G5": gate(base.max_dd <= g["G5_max_drawdown_max"], base.max_dd, f"<= {g['G5_max_drawdown_max']}"),
        "G6": gate(base.frac_windows_positive >= g["G6_janelas_positivas_min"] and n_configs <= max_configs,
                   {"fracao": base.frac_windows_positive, "configs_testadas": n_configs},
                   f">= {g['G6_janelas_positivas_min']} e configs <= {max_configs}"),
        "G7": gate(stress.mean_r >= g["G7_expectativa_com_slippage_estresse_R_min"], stress.mean_r,
                   f">= {g['G7_expectativa_com_slippage_estresse_R_min']} R com slippage de estresse"),
        "G8": gate(base.sharpe > spy_sharpe, {"estrategia": base.sharpe, "SPY": spy_sharpe},
                   "Sharpe > SPY comprado e mantido"),
    }
