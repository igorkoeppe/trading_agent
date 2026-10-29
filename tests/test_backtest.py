"""Motor de backtest: execução, sinais, métricas e trava do pré-registro. Sem rede."""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from agent.backtesting import engine as eng
from agent.backtesting.engine import SimParams, simulate
from agent.backtesting.guard import PreregError, assert_dev_only, open_final_test, verify_hashes
from agent.backtesting.metrics import (bootstrap_ci, evaluate_gates_A, max_drawdown, oos_windows,
                                       profit_factor, report)
from agent.backtesting.signals import setup_signals
from agent.quant.setups import find_setups

SLIP = 5 / 10_000


def flat(n=60, start="2020-01-01", px=100.0):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"open": px, "high": px + 1, "low": px - 1, "close": px}, index=idx)


def force_signal(monkeypatch, days):
    days = set(pd.Timestamp(d) for d in days)
    monkeypatch.setattr(eng, "entry_signal", lambda close: pd.Series(close.index.isin(days), index=close.index))


def run(bars, **kw):
    df0 = next(iter(bars.values()))
    return simulate(bars, SimParams(**kw), df0.index[0].date(), df0.index[-1].date(), list(bars))


# ---------- sinais ----------
def test_vectorized_signals_match_find_setups():
    rng = np.random.default_rng(7)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300))))
    sig = setup_signals(close)
    for i in range(29, len(close)):
        tags, _ = find_setups(close.iloc[: i + 1].tolist())
        assert sig["breakout_20d"].iloc[i] == ("breakout_20d" in tags), i
        assert sig["reclaim_ma20"].iloc[i] == ("reclaim_ma20" in tags), i
    assert not sig.iloc[:29].any().any()


def test_signals_do_not_look_ahead():
    rng = np.random.default_rng(3)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 200))))
    altered = close.copy()
    altered.iloc[120:] *= 1.5
    assert setup_signals(close).iloc[:120].equals(setup_signals(altered).iloc[:120])


# ---------- execução ----------
def test_entry_next_open_with_slippage_and_atr_stop(monkeypatch):
    df = flat()
    force_signal(monkeypatch, [df.index[20]])
    t = run({"X": df}).trades[0]
    assert t.entry_date == df.index[21].date()
    assert t.entry == pytest.approx(100 * (1 + SLIP))
    assert t.stop == pytest.approx(t.entry - 2 * 2.0, rel=1e-3)   # ATR de candles com amplitude 2


def test_entry_uses_next_open_and_signal_day_atr_only(monkeypatch):
    """O dia da entrada abre acima do fechamento do sinal e tem amplitude grande:
    o preço deve ser a abertura de t+1, e o ATR do stop deve ser o de t (sem olhar o candle de t+1)."""
    df = flat()
    df.loc[df.index[21], ["open", "high", "low", "close"]] = [103, 110, 102, 104]
    force_signal(monkeypatch, [df.index[20]])
    t = run({"X": df}).trades[0]
    assert t.entry == pytest.approx(103 * (1 + SLIP))
    atr_signal_day = eng.atr(df, 14).iloc[20]
    assert t.stop == pytest.approx(t.entry - 2 * atr_signal_day)


def test_positions_never_exceed_cash(monkeypatch):
    bars = {s: flat() for s in "ABC"}
    force_signal(monkeypatch, [bars["A"].index[20]])
    res = run(bars, risk_per_trade=0.5, max_exposure_per_asset=0.4)
    notional = sum(t.shares * t.entry for t in res.trades)
    assert len(res.trades) == 3
    assert notional == pytest.approx(10_000, rel=1e-9)   # 40% + 40% + só os 20% de caixa que sobram


def test_gap_below_stop_fills_at_open(monkeypatch):
    df = flat()
    df.loc[df.index[22], ["open", "high", "low", "close"]] = [90, 91, 89, 90]
    force_signal(monkeypatch, [df.index[20]])
    t = run({"X": df}).trades[0]
    assert t.reason == "stop_gap" and t.exit == pytest.approx(90 * (1 - SLIP))
    assert t.r_multiple < -1   # gap custa mais que 1 R


def test_intraday_touch_fills_at_stop(monkeypatch):
    df = flat()
    df.loc[df.index[23], "low"] = 90
    force_signal(monkeypatch, [df.index[20]])
    t = run({"X": df}).trades[0]
    assert t.reason == "stop" and t.exit == pytest.approx(t.stop * (1 - SLIP))
    assert t.r_multiple == pytest.approx(-1 - t.stop * SLIP / t.risk_per_share)   # -1 R menos o slippage


def test_time_exit_on_close_of_tenth_session(monkeypatch):
    df = flat()
    force_signal(monkeypatch, [df.index[20]])
    t = run({"X": df}).trades[0]
    assert t.reason == "tempo" and t.exit_date == df.index[30].date()   # dias 21..30
    assert t.exit == pytest.approx(100 * (1 - SLIP))


def test_risk_sizing_and_exposure_cap(monkeypatch):
    df = flat()
    force_signal(monkeypatch, [df.index[20]])
    t = run({"X": df}, risk_per_trade=0.01).trades[0]
    # 1% de 10.000 = 100 de risco; risco por ação = 4 -> 25 ações, abaixo do teto de 30%
    assert t.shares == pytest.approx(100 / t.risk_per_share)
    t2 = run({"X": df}, risk_per_trade=0.10).trades[0]
    assert t2.shares * t2.entry == pytest.approx(0.30 * 10_000, rel=1e-6)


def test_max_three_positions_in_universe_order(monkeypatch):
    bars = {s: flat() for s in "ABCDE"}
    force_signal(monkeypatch, [bars["A"].index[20]])
    res = run(bars)
    assert sorted(t.symbol for t in res.trades) == ["A", "B", "C"]


def test_no_reentry_while_holding(monkeypatch):
    df = flat()
    force_signal(monkeypatch, [df.index[20], df.index[22], df.index[24]])
    assert len(run({"X": df}).trades) == 1


def test_open_position_closed_at_end_of_period(monkeypatch):
    df = flat(n=25)
    force_signal(monkeypatch, [df.index[20]])
    res = run({"X": df})
    assert [t.reason for t in res.trades] == ["fim_periodo"] and len(res.open_at_end) == 1


def test_equity_unchanged_by_round_trip_without_slippage(monkeypatch):
    df = flat()
    force_signal(monkeypatch, [df.index[20]])
    res = run({"X": df}, slippage_bps=0)
    assert res.equity.iloc[-1] == pytest.approx(10_000)


# ---------- métricas ----------
def test_profit_factor_and_drawdown():
    assert profit_factor(np.array([2.0, -1.0, 1.0, -1.0])) == pytest.approx(1.5)
    assert max_drawdown(pd.Series([100, 120, 90, 130])) == pytest.approx(0.25)


def test_bootstrap_is_deterministic_and_brackets_mean():
    r = np.random.default_rng(1).normal(0.2, 1, 150)
    a, b = bootstrap_ci(r), bootstrap_ci(r)
    assert a == b and a[0] < r.mean() < a[1]


def test_windows_and_empty_window_counts_as_not_positive():
    w = oos_windows(date(2019, 1, 1), date(2020, 12, 31))
    assert w[0] == (date(2019, 1, 1), date(2019, 6, 30)) and len(w) == 4
    t = eng.Trade("X", date(2019, 1, 2), date(2019, 1, 3), 100, 96, 1, date(2019, 1, 10), 104, "tempo")
    rep = report([t], pd.Series([1.0, 1.1]), w)
    assert rep.frac_windows_positive == pytest.approx(0.25)


def test_gate_g6_fails_when_too_many_configs():
    t = eng.Trade("X", date(2019, 1, 2), date(2019, 1, 3), 100, 96, 1, date(2019, 1, 10), 104, "tempo")
    rep = report([t] * 120, pd.Series([1.0, 1.1, 1.2]), oos_windows(date(2019, 1, 1), date(2019, 6, 30)))
    g = {"G1_min_operacoes": 100, "G2_expectativa_liquida_R_min": 0.1, "G3_ic90_bootstrap_inferior_R_min": 0,
         "G4_fator_de_lucro_min": 1.3, "G5_max_drawdown_max": 0.2, "G6_janelas_positivas_min": 0.6,
         "G7_expectativa_com_slippage_estresse_R_min": 0}
    assert evaluate_gates_A(g, rep, rep, 0.5, 3, 12)["G6"]["passou"]
    assert not evaluate_gates_A(g, rep, rep, 0.5, 13, 12)["G6"]["passou"]


# ---------- trava do pré-registro ----------
def test_dev_guard_rejects_final_test_data():
    df = flat(start="2024-12-20", n=10)
    with pytest.raises(PreregError):
        assert_dev_only({"X": df}, date(2024, 12, 31))
    assert_dev_only({"X": flat(start="2024-01-01", n=10)}, date(2024, 12, 31))


def test_hash_check_detects_change(tmp_path):
    import hashlib
    f = tmp_path / "a.yaml"
    f.write_text("x: 1")
    hf = tmp_path / "h.sha256"
    hf.write_text(f"{hashlib.sha256(b'x: 1').hexdigest()}  a.yaml\n")
    verify_hashes(hf, tmp_path)
    f.write_text("x: 2")
    with pytest.raises(PreregError):
        verify_hashes(hf, tmp_path)


def test_final_test_opens_only_once(tmp_path):
    class P:
        final_start, final_end = date(2025, 1, 1), date(2026, 9, 30)
    done = tmp_path / "done.json"
    open_final_test(P(), done)
    assert json.loads(done.read_text())["periodo"][0] == "2025-01-01"
    with pytest.raises(PreregError):
        open_final_test(P(), done)


def test_frozen_prereg_in_repo_is_intact():
    verify_hashes()
