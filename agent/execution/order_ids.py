"""IDs de ordem determinísticos (idempotência).

O mesmo sinal sempre gera o mesmo client_order_id. Antes de reenviar uma ordem após
falha de rede, o executor consulta esse ID na corretora; se já existe, não reenvia.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

_SAFE = re.compile(r"[^A-Za-z0-9]")


def client_order_id(strategy: str, session: date, symbol: str, side: str, signal_version: str = "1") -> str:
    """Ex.: 'A1-20261028-SPY-B-3f9c2a1b'. Até 48 caracteres, só letras, números e hífen."""
    strat = _SAFE.sub("", strategy)[:12] or "S"
    sym = _SAFE.sub("", symbol.upper())[:8]
    s = side.lower()
    if s not in ("buy", "sell"):
        raise ValueError(f"lado inválido: {side!r}")
    raw = f"{strategy}|{session.isoformat()}|{symbol.upper()}|{s}|{signal_version}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"{strat}-{session:%Y%m%d}-{sym}-{s[0].upper()}-{digest}"
