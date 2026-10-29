"""Corretora simulada para testar cenários de falha sem rede."""
from __future__ import annotations

from dataclasses import replace

from agent.execution.broker_api import AccountSnapshot, OrderInfo, PositionInfo


class FakeBroker:
    def __init__(self, equity: float = 18.50, price: float = 100.0):
        self.cash = equity
        self.initial_equity = equity
        self.price = price
        self.qty: dict[str, float] = {}
        self.orders: dict[str, OrderInfo] = {}      # por client_order_id
        self.by_id: dict[str, str] = {}             # id -> client_order_id
        self.fill_mode = "immediate"                # immediate | reject | partial | never
        self.partial_fraction = 0.4
        self.fail_next_submit: tuple[str, Exception] | None = None   # ("before"|"after", erro)
        self.submit_calls: list[tuple] = []
        self.cancel_calls: list[str] = []
        self._n = 0
        self.polls_until_fill = 0                   # >0: ordem só enche depois de N consultas
        self._pending_polls: dict[str, int] = {}

    # ---------- leitura ----------
    def account(self) -> AccountSnapshot:
        mv = sum(q * self.price for q in self.qty.values())
        return AccountSnapshot(equity=self.cash + mv, last_equity=self.initial_equity, cash=self.cash)

    def positions(self) -> dict[str, PositionInfo]:
        return {s: PositionInfo(s, q, q * self.price) for s, q in self.qty.items() if q > 1e-12}

    def open_orders(self) -> list[OrderInfo]:
        return [o for o in self.orders.values() if o.is_open]

    def find_order(self, client_order_id: str) -> OrderInfo | None:
        o = self.orders.get(client_order_id)
        if o is not None and client_order_id in self._pending_polls:
            self._pending_polls[client_order_id] -= 1
            if self._pending_polls[client_order_id] <= 0:
                del self._pending_polls[client_order_id]
                self._fill(client_order_id, 1.0)
                o = self.orders[client_order_id]
        return o

    # ---------- escrita ----------
    def _new(self, **kw) -> OrderInfo:
        self._n += 1
        o = OrderInfo(id=f"id-{self._n}", **kw)
        self.orders[o.client_order_id] = o
        self.by_id[o.id] = o.client_order_id
        return o

    def _maybe_fail(self, when: str) -> None:
        if self.fail_next_submit and self.fail_next_submit[0] == when:
            _, exc = self.fail_next_submit
            self.fail_next_submit = None
            raise exc

    def _fill(self, cid: str, fraction: float) -> None:
        o = self.orders[cid]
        total = o.qty if o.qty is not None else round((o.notional or 0) / self.price, 9)
        qty = round(total * fraction, 9)
        delta = qty - o.filled_qty
        if o.side == "buy":
            self.qty[o.symbol] = round(self.qty.get(o.symbol, 0.0) + delta, 9)
            self.cash -= delta * self.price
        else:
            self.qty[o.symbol] = round(self.qty.get(o.symbol, 0.0) - delta, 9)
            self.cash += delta * self.price
        status = "filled" if fraction >= 1.0 else "partially_filled"
        self.orders[cid] = replace(o, status=status, filled_qty=qty, filled_avg_price=self.price,
                                   qty=o.qty if o.qty is not None else total)

    def _market(self, symbol, side, cid, qty=None, notional=None) -> OrderInfo:
        self.submit_calls.append(("market", symbol, side, qty, notional, cid))
        self._maybe_fail("before")
        if cid in self.orders:
            raise ValueError("client_order_id duplicado")
        o = self._new(client_order_id=cid, symbol=symbol, side=side, status="accepted", type="market",
                      qty=qty, notional=notional)
        if self.fill_mode == "reject":
            self.orders[cid] = replace(o, status="rejected")
        elif self.fill_mode == "partial":
            self._fill(cid, self.partial_fraction)
        elif self.fill_mode == "immediate":
            if self.polls_until_fill > 0:
                self._pending_polls[cid] = self.polls_until_fill
            else:
                self._fill(cid, 1.0)
        self._maybe_fail("after")
        return self.orders[cid]

    def submit_market_notional(self, symbol, side, notional, client_order_id) -> OrderInfo:
        return self._market(symbol, side, client_order_id, notional=notional)

    def submit_market_qty(self, symbol, side, qty, client_order_id) -> OrderInfo:
        return self._market(symbol, side, client_order_id, qty=qty)

    def submit_stop_qty(self, symbol, qty, stop_price, client_order_id) -> OrderInfo:
        self.submit_calls.append(("stop", symbol, "sell", qty, stop_price, client_order_id))
        if client_order_id in self.orders:
            raise ValueError("client_order_id duplicado")
        return self._new(client_order_id=client_order_id, symbol=symbol, side="sell", status="new",
                         type="stop", qty=qty, stop_price=stop_price)

    def cancel_order(self, order_id: str) -> None:
        self.cancel_calls.append(order_id)
        cid = self.by_id[order_id]
        o = self.orders[cid]
        if o.is_open:
            self.orders[cid] = replace(o, status="canceled")

    # ---------- ajudantes de teste ----------
    def expire_day_orders(self) -> None:
        """Fim do dia: ordens abertas com validade 'day' expiram (stops incluídos)."""
        for cid, o in list(self.orders.items()):
            if o.is_open:
                self.orders[cid] = replace(o, status="expired")

    def trigger_stop(self, symbol: str) -> None:
        """O preço bate no stop: a ordem executa e a posição fecha."""
        for cid, o in list(self.orders.items()):
            if o.symbol == symbol and o.is_stop and o.is_open:
                self.price = o.stop_price
                self._fill(cid, 1.0)

    def set_position(self, symbol: str, qty: float) -> None:
        """Cria uma posição fora do controle do agente (para testar divergência)."""
        self.qty[symbol] = qty
