"""Reconciliação: compara o estado local com a corretora, que é a fonte da verdade.

Erros bloqueiam novas entradas. Avisos são relatados, mas não bloqueiam.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.execution.broker_api import Broker
from agent.execution.state import LocalState

QTY_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Issue:
    kind: str
    symbol: str
    detail: str
    severity: str  # "error" | "warning"


@dataclass
class ReconcileReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if not self.issues:
            return "reconciliação: tudo consistente"
        return "\n".join(f"{i.severity}: {i.kind} {i.symbol}: {i.detail}" for i in self.issues)


def reconcile(broker: Broker, state: LocalState) -> ReconcileReport:
    report = ReconcileReport()
    broker_pos = broker.positions()
    open_orders = broker.open_orders()

    for sym, pos in broker_pos.items():
        if sym not in state.positions:
            report.issues.append(Issue("posicao_desconhecida", sym,
                                       f"a corretora tem {pos.qty} e o estado local não conhece essa posição", "error"))

    for sym, meta in state.positions.items():
        pos = broker_pos.get(sym)
        if pos is None:
            report.issues.append(Issue("posicao_ausente", sym,
                                       f"o estado local tem {meta['qty']} e a corretora não tem posição", "error"))
            continue
        if abs(pos.qty - meta["qty"]) > QTY_TOLERANCE:
            report.issues.append(Issue("quantidade_diverge", sym,
                                       f"local {meta['qty']} contra corretora {pos.qty}", "error"))
        has_stop = any(o.symbol == sym and o.side == "sell" and o.is_stop for o in open_orders)
        if not has_stop:
            report.issues.append(Issue("sem_stop", sym, "posição sem ordem de stop aberta", "warning"))

    for o in open_orders:
        if o.side == "sell" and o.symbol not in broker_pos:
            report.issues.append(Issue("ordem_orfa", o.symbol,
                                       f"ordem de venda {o.client_order_id} aberta sem posição", "warning"))
    return report
