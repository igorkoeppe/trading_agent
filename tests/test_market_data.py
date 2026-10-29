"""Regra do candle incompleto, testada com calendário simulado (sem rede)."""
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from agent.data import market_data

SESSIONS = [
    {"date": date(2026, 10, 26), "open": datetime(2026, 10, 26, 9, 30), "close": datetime(2026, 10, 26, 16, 0)},
    {"date": date(2026, 10, 27), "open": datetime(2026, 10, 27, 9, 30), "close": datetime(2026, 10, 27, 16, 0)},
    {"date": date(2026, 10, 28), "open": datetime(2026, 10, 28, 9, 30), "close": datetime(2026, 10, 28, 16, 0)},
]


@pytest.fixture(autouse=True)
def fake_calendar(monkeypatch):
    monkeypatch.setattr(market_data, "trading_sessions", lambda settings, start, end: SESSIONS)


def utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_during_session_today_is_not_complete():
    # 14:00 UTC = 10:00 em Nova York (horário de verão até 1 nov 2026)
    assert market_data.last_complete_session(None, now=utc(2026, 10, 28, 14, 0)) == date(2026, 10, 27)


def test_right_after_close_waits_for_data_delay():
    # 20:10 UTC = 16:10 em Nova York: fechou, mas ainda dentro da margem de 20 minutos
    assert market_data.last_complete_session(None, now=utc(2026, 10, 28, 20, 10)) == date(2026, 10, 27)
    assert market_data.last_complete_session(None, now=utc(2026, 10, 28, 20, 25)) == date(2026, 10, 28)


def test_drop_after_removes_partial_bar():
    idx = pd.DatetimeIndex(
        [pd.Timestamp(s["date"]).tz_localize("America/New_York").tz_convert("UTC") for s in SESSIONS]
    )
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=idx)
    out = market_data.drop_after(df, date(2026, 10, 27))
    assert list(out["close"]) == [1.0, 2.0]
