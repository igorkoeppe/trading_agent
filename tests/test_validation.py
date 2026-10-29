from datetime import date

import pandas as pd

from agent.data.validation import validate_daily_bars

DAYS = [date(2026, 10, d) for d in (19, 20, 21, 22, 23)]


def bars(days=DAYS, edits=None):
    idx = pd.DatetimeIndex([pd.Timestamp(d).tz_localize("America/New_York").tz_convert("UTC") for d in days])
    df = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
        index=idx,
    )
    for (row, col), value in (edits or {}).items():
        df.iloc[row, df.columns.get_loc(col)] = value
    return df


def test_clean_bars_pass():
    rep = validate_daily_bars(bars(), "SPY", expected_sessions=DAYS, last_expected_session=DAYS[-1])
    assert rep.ok, rep.summary()


def test_missing_session_is_an_error():
    rep = validate_daily_bars(bars(days=[DAYS[0], DAYS[1], DAYS[3], DAYS[4]]), "SPY", expected_sessions=DAYS)
    assert not rep.ok and "sem candle" in rep.summary()


def test_stale_data_is_an_error():
    rep = validate_daily_bars(bars(days=DAYS[:3]), "SPY", last_expected_session=DAYS[-1])
    assert not rep.ok and "desatualizado" in rep.summary()


def test_incoherent_high_low_and_bad_prices():
    rep = validate_daily_bars(bars(edits={(1, "high"): 90.0, (2, "close"): 0.0}), "SPY")
    text = rep.summary()
    assert "incoerentes" in text and "menor ou igual a zero" in text


def test_duplicates_and_order():
    df = bars()
    df = pd.concat([df, df.iloc[[0]]])
    rep = validate_daily_bars(df, "SPY")
    assert "duplicadas" in rep.summary() and "fora de ordem" in rep.summary()


def test_missing_columns():
    rep = validate_daily_bars(bars().drop(columns=["volume"]), "SPY")
    assert not rep.ok and "colunas ausentes" in rep.summary()


def test_split_like_jump_is_a_warning():
    rep = validate_daily_bars(bars(edits={(4, "close"): 50.0, (4, "low"): 49.0, (4, "open"): 50.0}), "SPY")
    assert rep.ok and rep.warnings
