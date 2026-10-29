"""Simulador diário de carteira para a Configuração A.

Regras (pré-registro v1, `execucao_simulada`):
- sinal no fechamento do pregão t; compra na ABERTURA de t+1, com slippage contra nós;
- stop = preço de entrada - multiplo x ATR(14) calculado até t;
- stop: se o pregão abre abaixo do stop, sai na abertura (gap); se a mínima toca o stop, sai no stop;
  no dia da entrada, vale a mínima do próprio dia (premissa conservadora);
- saída por tempo no fechamento do N-ésimo pregão em carteira (o dia da entrada conta como 1);
- todas as saídas pagam slippage; comissão zero;
- tamanho: risco de 1% do patrimônio até o stop, limitado a 30% do patrimônio por ativo e ao caixa;
- máximo de 3 posições; sem short; um ativo não entra de novo enquanto estiver em carteira;
- empate de sinais no mesmo dia: ordem do universo (critério sem informação de preço).
Datas: índice diário sem fuso (data do pregão em Nova York).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from agent.backtesting.signals import entry_signal
from agent.quant.indicators import atr


@dataclass(frozen=True)
class SimParams:
    slippage_bps: float = 5.0
    atr_period: int = 14
    atr_mult: float = 2.0
    max_hold_sessions: int = 10
    risk_per_trade: float = 0.01
    max_positions: int = 3
    max_exposure_per_asset: float = 0.30
    initial_equity: float = 10_000.0

    @classmethod
    def from_prereg(cls, raw: dict, slippage_bps: float | None = None) -> "SimParams":
        e = raw["execucao_simulada"]
        assert e["stop"]["tipo"] == "atr" and not e["short"]
        return cls(
            slippage_bps=float(slippage_bps if slippage_bps is not None else e["slippage_bps_por_lado"]),
            atr_period=int(e["stop"]["periodo"]),
            atr_mult=float(e["stop"]["multiplo"]),
            max_hold_sessions=int(e["saida_por_tempo_sessoes"]),
            risk_per_trade=float(e["risco_por_operacao"]),
            max_positions=int(e["max_posicoes"]),
        )


@dataclass
class Trade:
    symbol: str
    signal_date: date
    entry_date: date
    entry: float
    stop: float
    shares: float
    exit_date: date | None = None
    exit: float | None = None
    reason: str = ""
    held: int = 0

    @property
    def risk_per_share(self) -> float:
        return self.entry - self.stop

    @property
    def r_multiple(self) -> float:
        return (self.exit - self.entry) / self.risk_per_share

    @property
    def pnl(self) -> float:
        return (self.exit - self.entry) * self.shares


@dataclass
class SimResult:
    trades: list[Trade]
    equity: pd.Series
    params: SimParams
    open_at_end: list[Trade] = field(default_factory=list)


def _prep(df: pd.DataFrame, p: SimParams) -> pd.DataFrame:
    out = df[["open", "high", "low", "close"]].astype(float).copy()
    out["atr"] = atr(out, p.atr_period)
    out["signal"] = entry_signal(out["close"])
    return out


def simulate(bars: dict[str, pd.DataFrame], params: SimParams, start: date, end: date,
             universe_order: list[str] | None = None) -> SimResult:
    """Simula de `start` a `end` (inclusive). Os dados antes de `start` servem só de aquecimento."""
    order = universe_order or sorted(bars)
    data = {s: _prep(bars[s], params) for s in order if s in bars}
    days = sorted({d for df in data.values() for d in df.index
                   if pd.Timestamp(start) <= d <= pd.Timestamp(end)})
    slip = params.slippage_bps / 10_000.0

    cash = params.initial_equity
    positions: dict[str, Trade] = {}
    pending: list[tuple[str, pd.Timestamp]] = []   # (ativo, dia do sinal)
    trades: list[Trade] = []
    equity_curve = {}
    last_close: dict[str, float] = {}

    def equity_now() -> float:
        return cash + sum(t.shares * last_close.get(s, t.entry) for s, t in positions.items())

    for d in days:
        eq_before = equity_now()

        # 1) entradas na abertura, a partir dos sinais do pregão anterior
        for sym, sig_day in pending:
            df = data[sym]
            if d not in df.index or sym in positions or len(positions) >= params.max_positions:
                continue
            bar = df.loc[d]
            a = df.at[sig_day, "atr"]
            if pd.isna(a) or a <= 0:
                continue
            entry = bar["open"] * (1 + slip)
            stop = entry - params.atr_mult * a
            if stop <= 0:
                continue
            shares = params.risk_per_trade * eq_before / (entry - stop)
            shares = min(shares, params.max_exposure_per_asset * eq_before / entry, cash / entry)
            if shares <= 0:
                continue
            cash -= shares * entry
            positions[sym] = Trade(sym, sig_day.date(), d.date(), entry, stop, shares)
        pending = []

        # 2) stops e saída por tempo
        for sym in list(positions):
            t, df = positions[sym], data[sym]
            if d not in df.index:
                continue
            bar = df.loc[d]
            t.held += 1
            exit_px = reason = None
            if bar["open"] <= t.stop and t.entry_date != d.date():
                exit_px, reason = bar["open"] * (1 - slip), "stop_gap"
            elif bar["low"] <= t.stop:
                exit_px, reason = t.stop * (1 - slip), "stop"
            elif t.held >= params.max_hold_sessions:
                exit_px, reason = bar["close"] * (1 - slip), "tempo"
            if exit_px is not None:
                t.exit_date, t.exit, t.reason = d.date(), exit_px, reason
                cash += t.shares * exit_px
                trades.append(t)
                del positions[sym]

        # 3) marcação a mercado no fechamento
        for sym, df in data.items():
            if d in df.index:
                last_close[sym] = df.at[d, "close"]
        equity_curve[d] = equity_now()

        # 4) sinais do fechamento de d, executados no próximo pregão
        free = params.max_positions - len(positions)
        for sym in order:
            if free <= 0:
                break
            df = data.get(sym)
            if df is None or d not in df.index or sym in positions:
                continue
            if bool(df.at[d, "signal"]):
                pending.append((sym, d))
                free -= 1

    # posições ainda abertas no fim do período: encerradas no último fechamento, com slippage,
    # para não descartar operações (descartar favoreceria quem está perdendo e ainda não bateu o stop)
    open_at_end = []
    if days:
        for sym, t in list(positions.items()):
            px = last_close[sym] * (1 - slip)
            t.exit_date, t.exit, t.reason = days[-1].date(), px, "fim_periodo"
            cash += t.shares * px
            trades.append(t)
            open_at_end.append(t)
        positions.clear()
    return SimResult(trades, pd.Series(equity_curve, dtype=float), params, open_at_end)
