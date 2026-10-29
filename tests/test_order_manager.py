"""Cenários de falha da execução, todos contra a corretora simulada."""
from datetime import date, timedelta

import pytest

from agent.execution.order_manager import OrderManager, OrderManagerError
from agent.risk.kill_switch import trigger_kill_switch
from agent.risk.risk_engine import OrderIntent, RiskEngine, RiskLimits
from tests.fakes import FakeBroker

SESSION = date(2026, 10, 29)


def make(tmp_path, broker=None, **kw):
    broker = broker or FakeBroker()
    mgr = OrderManager(broker, RiskEngine(RiskLimits.from_yaml()), state_dir=tmp_path,
                       sleep=lambda s: None, **kw)
    return broker, mgr


def intent(symbol="SPY", notional=3.0, entry=100.0, stop=95.0):
    return OrderIntent(symbol, "buy", notional, entry, stop)


def entry(mgr, **kw):
    kw.setdefault("data_ok", True)
    return mgr.submit_entry(kw.pop("intent", intent()), "A1", kw.pop("session", SESSION), **kw)


def test_happy_path_fills_and_places_stop(tmp_path):
    broker, mgr = make(tmp_path)
    r = entry(mgr)
    assert r.submitted and not r.blocked
    assert r.order.status == "filled" and r.order.filled_qty == pytest.approx(0.03)
    assert r.stop_order.is_stop and r.stop_order.qty == pytest.approx(0.03)
    assert r.stop_order.stop_price == 95.0
    assert mgr.state.positions["SPY"]["qty"] == pytest.approx(0.03)
    assert mgr.reconcile().ok


def test_same_signal_twice_sends_one_order(tmp_path):
    broker, mgr = make(tmp_path)
    entry(mgr)
    again = entry(mgr)
    assert again.already_existed and not again.submitted
    assert sum(1 for c in broker.submit_calls if c[0] == "market") == 1


def test_network_drop_after_send_does_not_duplicate(tmp_path):
    broker, mgr = make(tmp_path)
    broker.fail_next_submit = ("after", TimeoutError("resposta perdida"))
    r = entry(mgr)
    assert r.order.status == "filled"
    assert sum(1 for c in broker.submit_calls if c[0] == "market") == 1
    assert r.stop_order is not None


def test_network_drop_before_send_is_retried_once(tmp_path):
    broker, mgr = make(tmp_path)
    broker.fail_next_submit = ("before", ConnectionError("sem rede"))
    r = entry(mgr)
    assert r.order.status == "filled"
    assert sum(1 for c in broker.submit_calls if c[0] == "market") == 2   # a 1ª nunca chegou


def test_persistent_failure_raises_and_creates_nothing(tmp_path):
    broker, mgr = make(tmp_path, submit_retries=1)

    def boom(*a, **k):
        raise TimeoutError("fora do ar")

    broker.submit_market_notional = boom
    with pytest.raises(OrderManagerError):
        entry(mgr)
    assert not broker.orders and not mgr.state.positions


def test_rejected_order_leaves_no_position_or_stop(tmp_path):
    broker, mgr = make(tmp_path)
    broker.fill_mode = "reject"
    r = entry(mgr)
    assert r.order.status == "rejected" and r.stop_order is None
    assert not mgr.state.positions and not broker.positions()


def test_partial_fill_cancels_rest_and_stops_only_filled_qty(tmp_path):
    broker, mgr = make(tmp_path, wait_timeout_s=10, poll_s=2)
    broker.fill_mode = "partial"
    t = {"now": 0.0}
    mgr._clock = lambda: t["now"]
    mgr._sleep = lambda s: t.__setitem__("now", t["now"] + s)
    r = entry(mgr)
    assert r.order.status == "canceled"
    assert r.order.filled_qty == pytest.approx(0.012)
    assert any("cancelado" in n for n in r.notes)
    assert r.stop_order.qty == pytest.approx(0.012)
    assert mgr.state.positions["SPY"]["qty"] == pytest.approx(0.012)
    assert mgr.reconcile().ok


def test_order_that_never_fills_is_canceled_without_position(tmp_path):
    broker, mgr = make(tmp_path, wait_timeout_s=6, poll_s=2)
    broker.fill_mode = "never"
    t = {"now": 0.0}
    mgr._clock = lambda: t["now"]
    mgr._sleep = lambda s: t.__setitem__("now", t["now"] + s)
    r = entry(mgr)
    assert r.order.status == "canceled" and r.stop_order is None
    assert not mgr.state.positions


def test_slow_fill_is_waited_for(tmp_path):
    broker, mgr = make(tmp_path)
    broker.polls_until_fill = 3
    r = entry(mgr)
    assert r.order.status == "filled" and r.stop_order is not None


def test_risk_block_never_reaches_broker(tmp_path):
    broker, mgr = make(tmp_path)
    r = entry(mgr, intent=intent(notional=10.0))     # perda até o stop acima de 1% do patrimônio
    assert r.blocked and not r.submitted
    assert broker.submit_calls == []


def test_invalid_data_blocks_entry(tmp_path):
    broker, mgr = make(tmp_path)
    r = entry(mgr, data_ok=False)
    assert r.blocked and "dados" in " ".join(r.blocked_reasons)
    assert broker.submit_calls == []


def test_kill_switch_blocks_entries_and_cancels_buys_but_keeps_stops(tmp_path):
    broker, mgr = make(tmp_path)
    entry(mgr)                                        # posição aberta com stop
    broker.fill_mode = "never"
    pending = broker.submit_market_notional("QQQ", "buy", 2.0, "pendente-1")
    assert pending.is_open
    canceled = trigger_kill_switch(mgr.kill_switch, broker, "teste")
    assert canceled == [pending.id]
    stops = [o for o in broker.open_orders() if o.is_stop]
    assert len(stops) == 1                            # proteção da posição continua
    assert broker.positions()["SPY"].qty > 0          # posição não foi tocada
    r = entry(mgr, intent=intent("QQQ"), session=SESSION + timedelta(days=1))
    assert r.blocked and any("kill switch" in x for x in r.blocked_reasons)
    mgr.kill_switch.deactivate()
    assert not mgr.kill_switch.active


def test_kill_switch_survives_restart(tmp_path):
    broker, mgr = make(tmp_path)
    mgr.kill_switch.activate("manual")
    _, mgr2 = make(tmp_path, broker)
    assert mgr2.kill_switch.active and mgr2.kill_switch.reason == "manual"


def test_stop_expires_overnight_and_is_resent_next_session(tmp_path):
    broker, mgr = make(tmp_path)
    entry(mgr)
    broker.expire_day_orders()
    assert not any(o.is_stop for o in broker.open_orders())
    placed = mgr.ensure_stops(SESSION + timedelta(days=1))
    assert len(placed) == 1 and placed[0].stop_price == 95.0
    assert mgr.ensure_stops(SESSION + timedelta(days=1)) == []      # já protegido: não duplica


def test_stop_hit_closes_position_and_state_settles(tmp_path):
    broker, mgr = make(tmp_path)
    entry(mgr)
    broker.trigger_stop("SPY")
    assert not broker.positions()
    report = mgr.reconcile()
    assert report.ok and "SPY" not in mgr.state.positions
    r = entry(mgr, intent=intent("QQQ"), session=SESSION + timedelta(days=1))
    assert r.submitted                                # estado limpo: pode operar de novo


def test_unknown_position_blocks_entries(tmp_path):
    broker, mgr = make(tmp_path)
    broker.set_position("TSLA", 0.01)                 # criada fora do agente
    r = entry(mgr)
    assert r.blocked and any("diverge" in x for x in r.blocked_reasons)
    assert broker.submit_calls == []


def test_missing_position_blocks_entries(tmp_path):
    broker, mgr = make(tmp_path)
    entry(mgr)
    broker.qty["SPY"] = 0.0                           # sumiu sem stop executado
    r = entry(mgr, intent=intent("QQQ"), session=SESSION + timedelta(days=1))
    assert r.blocked


def test_quantity_mismatch_blocks_entries(tmp_path):
    broker, mgr = make(tmp_path)
    entry(mgr)
    broker.qty["SPY"] = 0.5
    rep = mgr.reconcile()
    assert not rep.ok and any(i.kind == "quantidade_diverge" for i in rep.issues)


def test_exit_cancels_stop_sells_all_and_clears_state(tmp_path):
    broker, mgr = make(tmp_path)
    entry(mgr)
    out = mgr.submit_exit("SPY", SESSION, "teste")
    assert out.status == "filled" and out.side == "sell"
    assert not broker.positions() and "SPY" not in mgr.state.positions
    assert not [o for o in broker.open_orders() if o.is_stop]
    assert mgr.reconcile().ok


def test_failed_exit_restores_protection(tmp_path):
    broker, mgr = make(tmp_path, wait_timeout_s=4, poll_s=2)
    entry(mgr)
    broker.fill_mode = "never"
    t = {"now": 0.0}
    mgr._clock = lambda: t["now"]
    mgr._sleep = lambda s: t.__setitem__("now", t["now"] + s)
    out = mgr.submit_exit("SPY", SESSION, "teste")
    assert out.status == "canceled"
    assert "SPY" in mgr.state.positions
    assert any(o.is_stop and o.is_open for o in broker.open_orders())   # stop novo, ID diferente


def test_orders_today_counts_only_submitted_orders(tmp_path):
    broker, mgr = make(tmp_path)
    entry(mgr)
    entry(mgr)                                        # duplicata: não conta
    assert mgr.orders_today(SESSION) == 1
    assert mgr.orders_today(SESSION + timedelta(days=1)) == 0


def test_daily_order_limit_blocks(tmp_path):
    broker, mgr = make(tmp_path)
    mgr.risk.limits = RiskLimits(**{**RiskLimits.from_yaml().__dict__, "max_orders_per_day": 1})
    entry(mgr)
    r = entry(mgr, intent=intent("QQQ", notional=1.0, stop=99.0))
    assert r.blocked and any("ordens por dia" in x for x in r.blocked_reasons)


def test_state_file_survives_restart(tmp_path):
    broker, mgr = make(tmp_path)
    entry(mgr)
    _, mgr2 = make(tmp_path, broker)
    assert mgr2.state.positions["SPY"]["stop_price"] == 95.0
    assert mgr2.reconcile().ok
