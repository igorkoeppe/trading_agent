from datetime import date

import pytest

from agent.execution.order_ids import client_order_id
from agent.risk.risk_engine import (
    AccountState,
    OrderIntent,
    RiskEngine,
    RiskLimits,
    max_notional_for_risk,
)

LIMITS = RiskLimits.from_yaml()
ENGINE = RiskEngine(LIMITS)
EQUITY = 18.50


def acct(**kw):
    base = dict(equity=EQUITY, cash=EQUITY, positions={})
    base.update(kw)
    return AccountState(**base)


def buy(notional=3.0, entry=100.0, stop=95.0, symbol="SPY"):
    return OrderIntent(symbol=symbol, side="buy", notional=notional, entry_price=entry, stop_price=stop)


def test_limits_file_matches_document():
    assert LIMITS.risk_per_trade_pct == 0.01
    assert LIMITS.max_exposure_per_asset_pct == 0.30
    assert LIMITS.max_open_positions == 3


def test_small_entry_with_stop_is_approved():
    # perda até o stop: 3,00 x 5% = 0,15 <= 1% de 18,50 = 0,185
    v = ENGINE.check(buy(), acct())
    assert v.approved, v.reasons


def test_risk_per_trade_blocks_large_entry():
    v = ENGINE.check(buy(notional=5.0), acct())  # perda 0,25 > 0,185
    assert not v.approved and any("risco por operação" in r for r in v.reasons)


def test_entry_without_stop_is_blocked():
    v = ENGINE.check(buy(stop=None), acct())
    assert any("sem stop" in r for r in v.reasons)


def test_stop_above_entry_is_blocked():
    v = ENGINE.check(buy(stop=101.0), acct())
    assert any("stop acima" in r for r in v.reasons)


def test_exposure_cap_per_asset():
    v = ENGINE.check(buy(notional=2.0, stop=99.5), acct(positions={"SPY": 4.0}, cash=14.5))
    assert any("exposição" in r for r in v.reasons)  # 6,00 > 30% de 18,50 = 5,55


def test_max_open_positions():
    held = {"A": 1.0, "B": 1.0, "C": 1.0}
    v = ENGINE.check(buy(), acct(positions=held, cash=15.5))
    assert any("posições abertas" in r for r in v.reasons)


def test_daily_loss_kill_switch_and_data_block_entries_but_not_exits():
    state = acct(day_pnl=-0.60, kill_switch=True, data_ok=False, reconciled=False, positions={"SPY": 3.0})
    entry = ENGINE.check(buy(), state)
    assert len(entry.reasons) >= 4
    exit_ = ENGINE.check(OrderIntent("SPY", "sell", 3.0, 100.0), state)
    assert exit_.approved, exit_.reasons


def test_short_sale_and_minimum_and_cash():
    assert not ENGINE.check(OrderIntent("SPY", "sell", 3.0, 100.0), acct())  # sem posição
    assert not ENGINE.check(buy(notional=0.5, stop=99.0), acct())
    assert not ENGINE.check(buy(notional=3.0), acct(cash=2.0))


def test_orders_per_day():
    v = ENGINE.check(buy(), acct(orders_today=LIMITS.max_orders_per_day))
    assert any("ordens por dia" in r for r in v.reasons)


def test_max_notional_for_risk():
    n = max_notional_for_risk(EQUITY, 100.0, 95.0, LIMITS)
    assert n == pytest.approx(3.70)
    assert ENGINE.check(buy(notional=round(n, 2)), acct()).approved
    assert max_notional_for_risk(EQUITY, 100.0, 99.0, LIMITS) == pytest.approx(5.55)  # limitado pela exposição
    assert max_notional_for_risk(EQUITY, 100.0, 100.0, LIMITS) == 0.0


def test_client_order_id_is_deterministic_and_short():
    a = client_order_id("A1", date(2026, 10, 28), "spy", "buy")
    assert a == client_order_id("A1", date(2026, 10, 28), "SPY", "BUY")
    assert a != client_order_id("A1", date(2026, 10, 29), "SPY", "buy")
    assert a != client_order_id("A1", date(2026, 10, 28), "SPY", "buy", signal_version="2")
    assert a.startswith("A1-20261028-SPY-B-") and len(a) <= 48
    with pytest.raises(ValueError):
        client_order_id("A1", date(2026, 10, 28), "SPY", "hold")
