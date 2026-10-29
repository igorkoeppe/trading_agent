"""Conversão de ordens da Alpaca para OrderInfo, sem rede e sem o pacote alpaca-py."""
from types import SimpleNamespace

from agent.execution.alpaca_paper import to_order_info


def enum(v):
    return SimpleNamespace(value=v)


def test_enum_status_and_numeric_strings_are_normalized():
    raw = SimpleNamespace(
        id="abc", client_order_id="A1-20261029-SPY-B-1234abcd", symbol="SPY",
        side=enum("buy"), status=enum("partially_filled"), order_type=enum("market"),
        qty=None, notional="3.00", filled_qty="0.012", filled_avg_price="250.00", stop_price=None,
    )
    o = to_order_info(raw)
    assert (o.side, o.status, o.type) == ("buy", "partially_filled", "market")
    assert o.notional == 3.0 and o.filled_qty == 0.012 and o.filled_avg_price == 250.0
    assert o.is_open and not o.is_stop


def test_stop_order_and_none_filled_qty():
    raw = SimpleNamespace(
        id="d", client_order_id="c", symbol="SPY", side="sell", status="new", order_type="stop",
        qty="0.03", notional=None, filled_qty=None, filled_avg_price=None, stop_price="95.00",
    )
    o = to_order_info(raw)
    assert o.is_stop and o.stop_price == 95.0 and o.filled_qty == 0.0 and o.qty == 0.03
