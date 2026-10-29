"""Gerenciador de ordens: entrada idempotente, stop diário, saída e reconciliação.

Fluxo de uma entrada:
  1. se o client_order_id já existe na corretora, não envia de novo (idempotência);
  2. reconcilia estado local com a corretora; divergência bloqueia a entrada;
  3. passa pelo motor de risco (inclui kill switch, dados válidos e stop obrigatório);
  4. envia; se a rede falhar, consulta a corretora antes de qualquer reenvio;
  5. acompanha até o estado final; o que sobrar de ordem parcial é cancelado;
  6. com posição aberta, coloca um stop com a quantidade que realmente encheu.

Ordens fracionadas só aceitam validade "day" e não aceitam ordem composta, então o stop é uma
ordem separada que expira no fim do pregão e precisa ser reenviada por `ensure_stops`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from agent.config.settings import PROJECT_ROOT
from agent.execution.broker_api import Broker, OrderInfo
from agent.execution.order_ids import client_order_id
from agent.execution.state import LocalState
from agent.monitoring.logger import log_event, read_events
from agent.risk.kill_switch import KillSwitch
from agent.risk.reconciliation import ReconcileReport, reconcile
from agent.risk.risk_engine import AccountState, OrderIntent, RiskEngine

DEFAULT_STATE_DIR = PROJECT_ROOT / "logs" / "state"
TRANSIENT = (TimeoutError, ConnectionError, OSError)


class OrderManagerError(RuntimeError):
    pass


@dataclass
class EntryResult:
    submitted: bool = False
    already_existed: bool = False
    blocked_reasons: list[str] = field(default_factory=list)
    order: OrderInfo | None = None
    stop_order: OrderInfo | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_reasons)


class OrderManager:
    def __init__(
        self,
        broker: Broker,
        risk: RiskEngine,
        state_dir: Path = DEFAULT_STATE_DIR,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wait_timeout_s: float = 60.0,
        poll_s: float = 2.0,
        submit_retries: int = 2,
    ):
        self.broker = broker
        self.risk = risk
        self.state_dir = Path(state_dir)
        self.state = LocalState(self.state_dir / "positions.json")
        self.kill_switch = KillSwitch(self.state_dir / "kill_switch.json")
        self._sleep, self._clock = sleep, clock
        self.wait_timeout_s, self.poll_s, self.submit_retries = wait_timeout_s, poll_s, submit_retries

    # ---------- registro ----------
    def _log(self, event: str, **data) -> None:
        log_event("orders", {"event": event, **data}, log_dir=self.state_dir)

    def orders_today(self, session: date) -> int:
        return sum(1 for e in read_events("orders", self.state_dir)
                   if e.get("event") == "order_submitted" and e.get("session") == session.isoformat())

    # ---------- estado e reconciliação ----------
    def account_state(self, session: date, *, data_ok: bool, reconciled: bool) -> AccountState:
        snap = self.broker.account()
        return AccountState(
            equity=snap.equity,
            cash=snap.cash,
            positions={s: p.market_value for s, p in self.broker.positions().items()},
            day_pnl=snap.equity - snap.last_equity,
            orders_today=self.orders_today(session),
            kill_switch=self.kill_switch.active,
            data_ok=data_ok,
            reconciled=reconciled,
        )

    def settle_closed_positions(self) -> list[str]:
        """Remove do estado local posições que fecharam porque um stop executou."""
        closed = []
        broker_pos = self.broker.positions()
        for sym, meta in list(self.state.positions.items()):
            if sym in broker_pos:
                continue
            for cid in meta.get("stop_cids", []):
                o = self.broker.find_order(cid)
                if o is not None and o.status == "filled":
                    self._log("position_closed_by_stop", symbol=sym, client_order_id=cid,
                              fill_price=o.filled_avg_price, qty=o.filled_qty)
                    self.state.remove(sym)
                    closed.append(sym)
                    break
        return closed

    def reconcile(self) -> ReconcileReport:
        self.settle_closed_positions()
        report = reconcile(self.broker, self.state)
        if not report.ok:
            self._log("reconcile_failed", issues=[i.__dict__ for i in report.issues])
        return report

    # ---------- envio com recuperação de falha de rede ----------
    def _submit_with_recovery(self, send: Callable[[], OrderInfo], cid: str) -> OrderInfo:
        last_exc: Exception | None = None
        for attempt in range(self.submit_retries + 1):
            try:
                return send()
            except TRANSIENT as exc:
                last_exc = exc
                self._log("submit_error", client_order_id=cid, attempt=attempt, error=repr(exc))
                found = self.broker.find_order(cid)   # a ordem pode ter chegado antes da queda
                if found is not None:
                    self._log("submit_recovered", client_order_id=cid)
                    return found
                self._sleep(self.poll_s)
        raise OrderManagerError(f"não foi possível enviar {cid}: {last_exc!r}")

    def wait_for_final(self, cid: str) -> OrderInfo | None:
        deadline = self._clock() + self.wait_timeout_s
        order = self.broker.find_order(cid)
        while order is not None and not order.is_terminal and self._clock() < deadline:
            self._sleep(self.poll_s)
            order = self.broker.find_order(cid)
        return order

    def _finalize(self, order: OrderInfo, notes: list[str]) -> OrderInfo:
        cid = order.client_order_id
        final = self.wait_for_final(cid) or order
        if not final.is_terminal:
            self.broker.cancel_order(final.id)
            notes.append("ordem não terminou no prazo; restante cancelado")
            self._log("order_timeout_cancel", client_order_id=cid, filled_qty=final.filled_qty)
            final = self.wait_for_final(cid) or final
        return final

    # ---------- entrada ----------
    def submit_entry(self, intent: OrderIntent, strategy: str, session: date, *, data_ok: bool,
                     signal_version: str = "1") -> EntryResult:
        if intent.side.lower() != "buy":
            raise OrderManagerError("submit_entry só aceita compras; use submit_exit para vender")
        cid = client_order_id(strategy, session, intent.symbol, "buy", signal_version)
        result = EntryResult()

        existing = self.broker.find_order(cid)
        if existing is not None:
            self._log("entry_duplicate_ignored", client_order_id=cid, status=existing.status)
            result.already_existed, result.order = True, existing
            result.notes.append("ordem com este client_order_id já existe; nada foi reenviado")
            return result

        report = self.reconcile()
        acct = self.account_state(session, data_ok=data_ok, reconciled=report.ok)
        verdict = self.risk.check(intent, acct)
        if not verdict.approved:
            self._log("entry_blocked", client_order_id=cid, symbol=intent.symbol, reasons=verdict.reasons)
            result.blocked_reasons = verdict.reasons
            return result

        order = self._submit_with_recovery(
            lambda: self.broker.submit_market_notional(intent.symbol, "buy", round(intent.notional, 2), cid), cid)
        result.submitted = True
        self._log("order_submitted", client_order_id=cid, symbol=intent.symbol, side="buy",
                  notional=intent.notional, session=session.isoformat(), strategy=strategy)

        order = self._finalize(order, result.notes)
        result.order = order
        self._log("order_final", client_order_id=cid, status=order.status, filled_qty=order.filled_qty,
                  avg_price=order.filled_avg_price)

        if order.filled_qty > 0:
            self.state.add_fill(intent.symbol, order.filled_qty, intent.stop_price, strategy,
                                session.isoformat(), cid)
            result.stop_order = self._place_stop(intent.symbol, session, strategy)
        else:
            result.notes.append(f"ordem terminou como {order.status} sem execução")
        return result

    # ---------- stops ----------
    def _place_stop(self, symbol: str, session: date, strategy: str) -> OrderInfo | None:
        meta = self.state.positions.get(symbol)
        pos = self.broker.positions().get(symbol)
        if meta is None or pos is None or meta.get("stop_price") is None:
            return None
        n = 0
        while True:   # um stop cancelado ou expirado no mesmo dia não pode ser reutilizado: novo ID
            cid = client_order_id(meta["strategy"], session, symbol, "sell",
                                  signal_version="stop" if n == 0 else f"stop{n}")
            found = self.broker.find_order(cid)
            if found is None:
                break
            if found.is_open:
                return found
            n += 1
        stop = self._submit_with_recovery(
            lambda: self.broker.submit_stop_qty(symbol, pos.qty, round(meta["stop_price"], 2), cid), cid)
        self.state.add_stop_cid(symbol, cid)
        self._log("stop_placed", symbol=symbol, client_order_id=cid, qty=pos.qty,
                  stop_price=meta["stop_price"], session=session.isoformat())
        return stop

    def ensure_stops(self, session: date) -> list[OrderInfo]:
        """Rotina de início de pregão: reenvia o stop de toda posição que ficou sem ele.

        Stops de ordens fracionadas valem só no dia, então esta rotina precisa rodar todo pregão.
        """
        self.settle_closed_positions()
        placed = []
        open_stops = {o.symbol for o in self.broker.open_orders() if o.side == "sell" and o.is_stop}
        for symbol in list(self.state.positions):
            if symbol in open_stops or symbol not in self.broker.positions():
                continue
            stop = self._place_stop(symbol, session, self.state.positions[symbol]["strategy"])
            if stop is not None:
                placed.append(stop)
        return placed

    # ---------- saída ----------
    def submit_exit(self, symbol: str, session: date, reason: str) -> OrderInfo | None:
        """Vende a posição inteira a mercado. Cancela o stop antes, para não travar a quantidade."""
        pos = self.broker.positions().get(symbol)
        meta = self.state.positions.get(symbol)
        if pos is None or meta is None:
            raise OrderManagerError(f"sem posição conhecida em {symbol}")
        for o in self.broker.open_orders():
            if o.symbol == symbol and o.side == "sell":
                self.broker.cancel_order(o.id)
                self.wait_for_final(o.client_order_id)
        cid = client_order_id(meta["strategy"], session, symbol, "sell", signal_version=f"exit-{reason}")
        existing = self.broker.find_order(cid)
        if existing is not None:
            return existing
        order = self._submit_with_recovery(lambda: self.broker.submit_market_qty(symbol, "sell", pos.qty, cid), cid)
        self._log("order_submitted", client_order_id=cid, symbol=symbol, side="sell", qty=pos.qty,
                  session=session.isoformat(), reason=reason)
        order = self._finalize(order, [])
        self._log("order_final", client_order_id=cid, status=order.status, filled_qty=order.filled_qty,
                  avg_price=order.filled_avg_price)
        if order.status == "filled":
            self.state.remove(symbol)
        else:
            self._place_stop(symbol, session, meta["strategy"])   # saída falhou: volta a proteger
        return order
