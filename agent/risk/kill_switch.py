"""Kill switch: interrompe novas entradas e cancela ordens de COMPRA pendentes.

Decisão de desenho: o kill switch NÃO cancela stops de proteção nem fecha posições.
Cancelar um stop deixaria a posição sem proteção justamente no momento de emergência.
Encerrar posições é uma decisão separada do operador (ou de uma regra da estratégia).
O estado fica em arquivo, então sobrevive a reinícios do programa.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agent.execution.broker_api import Broker


class KillSwitch:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"active": False}
        return json.loads(self.path.read_text(encoding="utf-8"))

    @property
    def active(self) -> bool:
        return bool(self._read().get("active", False))

    @property
    def reason(self) -> str:
        return self._read().get("reason", "")

    def activate(self, reason: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "active": True,
            "reason": reason,
            "since_utc": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
        os.replace(tmp, self.path)

    def deactivate(self) -> None:
        if self.path.exists():
            self.path.unlink()


def trigger_kill_switch(ks: KillSwitch, broker: Broker, reason: str) -> list[str]:
    """Aciona o kill switch e cancela ordens de compra abertas. Devolve os IDs cancelados."""
    ks.activate(reason)
    canceled = []
    for order in broker.open_orders():
        if order.side == "buy":
            broker.cancel_order(order.id)
            canceled.append(order.id)
    return canceled
