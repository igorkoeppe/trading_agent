"""Validação de candles diários (OHLCV).

Nenhuma decisão usa um DataFrame que não passou por `validate_daily_bars`.
A função não corrige nada: ela relata problemas, e quem chama decide se bloqueia.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass
class ValidationReport:
    symbol: str
    rows: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        status = "OK" if self.ok else "FALHOU"
        lines = [f"{self.symbol}: {status} ({self.rows} candles)"]
        lines += [f"  erro: {e}" for e in self.errors]
        lines += [f"  aviso: {w}" for w in self.warnings]
        return "\n".join(lines)


def validate_daily_bars(
    df: pd.DataFrame,
    symbol: str,
    expected_sessions: list[date] | None = None,
    last_expected_session: date | None = None,
) -> ValidationReport:
    """Checa estrutura, coerência de preços, duplicatas, ordem, buracos e atraso.

    df: índice de timestamps (um por dia), colunas open/high/low/close/volume.
    expected_sessions: pregões esperados no período (calendário da Alpaca), para achar buracos.
    last_expected_session: último pregão encerrado; se o último candle for anterior, o dado está velho.
    """
    rep = ValidationReport(symbol=symbol, rows=len(df))

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        rep.errors.append(f"colunas ausentes: {missing}")
        return rep
    if df.empty:
        rep.errors.append("nenhum candle")
        return rep

    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        rep.warnings.append("índice sem fuso horário; assumindo datas de Nova York")
        ny_idx = idx
    else:
        ny_idx = idx.tz_convert("America/New_York")
    days = pd.Index([ts.date() for ts in ny_idx])

    if days.has_duplicates:
        rep.errors.append(f"datas duplicadas: {sorted(set(days[days.duplicated()]))[:5]}")
    if not idx.is_monotonic_increasing:
        rep.errors.append("candles fora de ordem cronológica")

    values = df[list(REQUIRED_COLUMNS)]
    if values.isna().any().any():
        bad = values.isna().any(axis=1)
        rep.errors.append(f"valores ausentes em {int(bad.sum())} candles")

    prices = df[["open", "high", "low", "close"]]
    if (prices <= 0).any().any():
        rep.errors.append("preço menor ou igual a zero")
    if (df["volume"] < 0).any():
        rep.errors.append("volume negativo")

    hi_bad = df["high"] < df[["open", "close"]].max(axis=1)
    lo_bad = df["low"] > df[["open", "close"]].min(axis=1)
    if hi_bad.any() or lo_bad.any():
        rep.errors.append(f"máxima/mínima incoerentes em {int((hi_bad | lo_bad).sum())} candles")

    zero_vol = int((df["volume"] == 0).sum())
    if zero_vol:
        rep.warnings.append(f"{zero_vol} candles com volume zero")

    # Variação diária extrema costuma indicar desdobramento não ajustado ou erro de dado.
    jumps = df["close"].pct_change().abs()
    extreme = jumps[jumps > 0.4]
    if not extreme.empty:
        rep.warnings.append(
            f"variação diária acima de 40% em {len(extreme)} datas "
            f"(conferir desdobramentos/ajuste): {[d.date() for d in extreme.index[:3]]}"
        )

    if expected_sessions:
        got = set(days)
        start, end = days.min(), days.max()
        gaps = [d for d in expected_sessions if start <= d <= end and d not in got]
        if gaps:
            rep.errors.append(f"{len(gaps)} pregões sem candle, ex.: {gaps[:5]}")
        extra = sorted(got - set(expected_sessions))
        if extra:
            rep.errors.append(f"candles em dias sem pregão: {extra[:5]}")

    if last_expected_session is not None and days.max() < last_expected_session:
        rep.errors.append(
            f"dado desatualizado: último candle {days.max()}, esperado {last_expected_session}"
        )

    return rep
