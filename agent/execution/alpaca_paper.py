"""Adaptador da Alpaca (paper) para a interface `Broker`.

Só conversa com o endereço de paper. Detalhes que valem lembrar:
- ordens fracionadas aceitam apenas validade "day" e não aceitam ordem composta;
- ordens por valor (notional) servem para compras; vendas e stops usam quantidade;
- o status volta como enum; aqui ele é normalizado para texto em minúsculas.
"""
from __future__ import annotations

from agent.config.settings import Settings
from agent.execution.broker_api import AccountSnapshot, OrderInfo, PositionInfo


def _f(x) -> float | None:
    return None if x is None else float(x)


def _enum(x) -> str:
    return str(getattr(x, "value", x)).lower()


def to_order_info(o) -> OrderInfo:
    return OrderInfo(
        id=str(o.id),
        client_order_id=str(o.client_order_id),
        symbol=str(o.symbol),
        side=_enum(o.side),
        status=_enum(o.status),
        type=_enum(getattr(o, "order_type", None) or getattr(o, "type", "market")),
        qty=_f(getattr(o, "qty", None)),
        notional=_f(getattr(o, "notional", None)),
        filled_qty=_f(getattr(o, "filled_qty", None)) or 0.0,
        filled_avg_price=_f(getattr(o, "filled_avg_price", None)),
        stop_price=_f(getattr(o, "stop_price", None)),
    )


class PaperBroker:
    def __init__(self, settings: Settings):
        if not settings.paper:
            raise RuntimeError("PaperBroker só funciona em modo paper.")
        from alpaca.trading.client import TradingClient

        self._client = TradingClient(settings.key_id, settings.secret_key, paper=True)

    # ---------- leitura ----------
    def raw_account(self):
        return self._client.get_account()

    def account(self) -> AccountSnapshot:
        a = self._client.get_account()
        return AccountSnapshot(equity=float(a.equity), last_equity=float(a.last_equity), cash=float(a.cash))

    def positions(self) -> dict[str, PositionInfo]:
        return {p.symbol: PositionInfo(p.symbol, float(p.qty), float(p.market_value))
                for p in self._client.get_all_positions()}

    def open_orders(self) -> list[OrderInfo]:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        orders = self._client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        return [to_order_info(o) for o in orders]

    def find_order(self, client_order_id: str) -> OrderInfo | None:
        from alpaca.common.exceptions import APIError

        try:
            return to_order_info(self._client.get_order_by_client_id(client_order_id))
        except APIError as exc:
            if getattr(exc, "status_code", None) == 404 or "not found" in str(exc).lower():
                return None
            raise

    # ---------- escrita ----------
    def submit_market_notional(self, symbol, side, notional, client_order_id) -> OrderInfo:
        from alpaca.trading.enums import TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        req = MarketOrderRequest(symbol=symbol, notional=round(notional, 2), side=_side(side),
                                 time_in_force=TimeInForce.DAY, client_order_id=client_order_id)
        return to_order_info(self._client.submit_order(req))

    def submit_market_qty(self, symbol, side, qty, client_order_id) -> OrderInfo:
        from alpaca.trading.enums import TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        req = MarketOrderRequest(symbol=symbol, qty=qty, side=_side(side),
                                 time_in_force=TimeInForce.DAY, client_order_id=client_order_id)
        return to_order_info(self._client.submit_order(req))

    def submit_stop_qty(self, symbol, qty, stop_price, client_order_id) -> OrderInfo:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import StopOrderRequest

        req = StopOrderRequest(symbol=symbol, qty=qty, side=OrderSide.SELL, stop_price=round(stop_price, 2),
                               time_in_force=TimeInForce.DAY, client_order_id=client_order_id)
        return to_order_info(self._client.submit_order(req))

    def cancel_order(self, order_id: str) -> None:
        self._client.cancel_order_by_id(order_id)


def _side(side: str):
    from alpaca.trading.enums import OrderSide

    return OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
