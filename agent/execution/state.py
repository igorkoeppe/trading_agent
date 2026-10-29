"""Estado local das posições do agente.

A corretora é a fonte da verdade para o que existe. Este arquivo guarda o que só o agente
sabe: de qual estratégia é a posição, o preço do stop e quais IDs de stop já foram usados.
Escrita atômica (arquivo temporário + rename) para não corromper o estado numa queda.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class LocalState:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.positions: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.positions = data.get("positions", {})
        else:
            self.positions = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"positions": self.positions}, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def add_fill(self, symbol: str, qty: float, stop_price: float | None, strategy: str,
                 session: str, entry_cid: str) -> None:
        pos = self.positions.get(symbol)
        if pos is None:
            pos = {"qty": 0.0, "stop_price": stop_price, "strategy": strategy,
                   "opened_session": session, "entry_cids": [], "stop_cids": []}
            self.positions[symbol] = pos
        pos["qty"] = round(pos["qty"] + qty, 9)
        if stop_price is not None:
            pos["stop_price"] = stop_price
        if entry_cid not in pos["entry_cids"]:
            pos["entry_cids"].append(entry_cid)
        self.save()

    def add_stop_cid(self, symbol: str, cid: str) -> None:
        pos = self.positions[symbol]
        if cid not in pos["stop_cids"]:
            pos["stop_cids"].append(cid)
            self.save()

    def remove(self, symbol: str) -> None:
        if self.positions.pop(symbol, None) is not None:
            self.save()
