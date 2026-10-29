"""Acesso a dados de mercado e calendário pela Alpaca (alpaca-py).

O calendário vem da própria Alpaca (/v2/calendar e /v2/clock), o que cobre feriados,
pregões de meio período e anos futuros sem manter listas fixas no código.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from agent.config.settings import Settings

# No plano gratuito, dados históricos SIP só podem ser consultados com atraso de 15 minutos.
SIP_SAFETY_DELAY = timedelta(minutes=20)
NY = ZoneInfo("America/New_York")


def _trading_client(settings: Settings):
    from alpaca.trading.client import TradingClient

    return TradingClient(settings.key_id, settings.secret_key, paper=True)


def _data_client(settings: Settings):
    from alpaca.data.historical import StockHistoricalDataClient

    return StockHistoricalDataClient(settings.key_id, settings.secret_key)


def trading_sessions(settings: Settings, start: date, end: date) -> list[dict]:
    """Pregões entre start e end, com horário de abertura e fechamento (Nova York)."""
    from alpaca.trading.requests import GetCalendarRequest

    cal = _trading_client(settings).get_calendar(GetCalendarRequest(start=start, end=end))
    return [{"date": c.date, "open": c.open, "close": c.close} for c in cal]


def market_clock(settings: Settings):
    """Estado do mercado agora: is_open, next_open, next_close."""
    return _trading_client(settings).get_clock()


def daily_bars(
    settings: Settings,
    symbols: list[str],
    start: date,
    end: date | None = None,
    feed: str | None = None,
    complete_only: bool = True,
) -> dict[str, pd.DataFrame]:
    """Candles diários ajustados (desdobramentos e dividendos), um DataFrame por ativo.

    O índice de cada DataFrame é o timestamp do candle; colunas open, high, low, close,
    volume, trade_count, vwap. Com complete_only=True (padrão), o candle do pregão em
    andamento é descartado.
    """
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    feed = (feed or settings.data_feed).lower()
    end_dt = datetime.now(timezone.utc) - SIP_SAFETY_DELAY
    if end is not None:
        end_dt = min(end_dt, datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc))

    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
        end=end_dt,
        adjustment=Adjustment.ALL,
        feed=DataFeed.SIP if feed == "sip" else DataFeed.IEX,
    )
    df = _data_client(settings).get_stock_bars(req).df
    out: dict[str, pd.DataFrame] = {}
    if df.empty:
        return out
    cutoff = last_complete_session(settings) if complete_only else None
    for sym in symbols:
        if sym in df.index.get_level_values(0):
            bars = df.xs(sym, level=0).sort_index()
            if cutoff is not None:
                bars = drop_after(bars, cutoff)
            out[sym] = bars
    return out


def drop_after(bars: pd.DataFrame, last_day: date) -> pd.DataFrame:
    """Remove candles com data (Nova York) posterior a last_day."""
    days = pd.DatetimeIndex(bars.index)
    if days.tz is not None:
        days = days.tz_convert(NY)
    keep = [d.date() <= last_day for d in days]
    return bars[keep]


def last_complete_session(settings: Settings, now: datetime | None = None) -> date:
    """Último pregão cujo candle diário já está completo.

    O pregão de hoje só conta depois do fechamento mais a margem de atraso dos dados;
    antes disso, o candle de hoje é parcial e entraria na decisão com informação incompleta.
    """
    now_ny = (now or datetime.now(timezone.utc)).astimezone(NY)
    sessions = trading_sessions(settings, now_ny.date() - timedelta(days=10), now_ny.date())
    for s in reversed(sessions):
        close = s["close"]
        close_dt = close if isinstance(close, datetime) else datetime.combine(s["date"], close)
        if close_dt.tzinfo is None:
            close_dt = close_dt.replace(tzinfo=NY)
        if now_ny >= close_dt + SIP_SAFETY_DELAY:
            return s["date"]
    raise RuntimeError("nenhum pregão completo nos últimos 10 dias")
