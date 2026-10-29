"""Interface mínima de corretora usada pelo gerenciador de ordens.

O gerenciador só conhece estes tipos. Isso permite testar todos os cenários de falha com
uma corretora simulada (tests/fakes.py) e trocar a implementação sem tocar na lógica.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Estados em que a ordem não muda mais.
TERMINAL_STATUSES = frozenset({"filled", "canceled", "expired", "rejected", "done_for_day", "replaced"})


@dataclass(frozen=True)
class OrderInfo:
    id: str
    client_order_id: str
    symbol: str
    side: str                      # "buy" | "sell"
    status: str                    # minúsculas: new, accepted, partially_filled, filled, canceled...
    type: str = "market"           # "market" | "stop" ...
    qty: float | None = None
    notional: float | None = None
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    stop_price: float | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_open(self) -> bool:
        return not self.is_terminal

    @property
    def is_stop(self) -> bool:
        return self.type.startswith("stop")


@dataclass(frozen=True)
class PositionInfo:
    symbol: str
    qty: float
    market_value: float


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float
    last_equity: float
    cash: float


class Broker(Protocol):
    def account(self) -> AccountSnapshot: ...
    def positions(self) -> dict[str, PositionInfo]: ...
    def open_orders(self) -> list[OrderInfo]: ...
    def find_order(self, client_order_id: str) -> OrderInfo | None: ...
    def submit_market_notional(self, symbol: str, side: str, notional: float, client_order_id: str) -> OrderInfo: ...
    def submit_market_qty(self, symbol: str, side: str, qty: float, client_order_id: str) -> OrderInfo: ...
    def submit_stop_qty(self, symbol: str, qty: float, stop_price: float, client_order_id: str) -> OrderInfo: ...
    def cancel_order(self, order_id: str) -> None: ...
