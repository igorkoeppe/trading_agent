"""Motor de risco independente dos modelos.

Toda ordem passa por `RiskEngine.check`. A função é pura: recebe o pedido e o estado da
conta (vindo da corretora, que é a fonte da verdade) e devolve aprovado ou bloqueado,
com os motivos. Nenhum modelo de IA chama esta camada com permissão de contorná-la.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agent.config.settings import PROJECT_ROOT

DEFAULT_LIMITS_PATH = PROJECT_ROOT / "config" / "risk_limits.yaml"


@dataclass(frozen=True)
class RiskLimits:
    max_daily_loss_pct: float
    risk_per_trade_pct: float
    max_exposure_per_asset_pct: float
    max_open_positions: int
    max_orders_per_day: int
    min_order_notional_usd: float = 1.0
    require_stop_on_entry: bool = True
    allow_short: bool = False

    @classmethod
    def from_yaml(cls, path: Path = DEFAULT_LIMITS_PATH) -> "RiskLimits":
        with open(path, encoding="utf-8") as fh:
            return cls(**yaml.safe_load(fh))


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str                       # "buy" abre ou aumenta; "sell" reduz ou fecha
    notional: float                 # valor em dólares
    entry_price: float              # preço de referência usado no cálculo de risco
    stop_price: float | None = None


@dataclass
class AccountState:
    equity: float
    cash: float
    positions: dict[str, float] = field(default_factory=dict)  # símbolo -> valor de mercado (US$)
    day_pnl: float = 0.0            # resultado do dia (realizado + não realizado), em US$
    orders_today: int = 0
    kill_switch: bool = False
    data_ok: bool = True            # falso se a validação de dados falhou
    reconciled: bool = True         # falso se estado local e corretora divergem


@dataclass
class RiskVerdict:
    approved: bool
    reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.approved


class RiskEngine:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def check(self, order: OrderIntent, acct: AccountState) -> RiskVerdict:
        lim = self.limits
        reasons: list[str] = []
        side = order.side.lower()
        is_entry = side == "buy"
        held = acct.positions.get(order.symbol, 0.0)

        # Bloqueios gerais: valem para entradas. Saídas que reduzem risco continuam permitidas.
        if is_entry:
            if acct.kill_switch:
                reasons.append("kill switch acionado: novas entradas bloqueadas")
            if not acct.data_ok:
                reasons.append("dados inválidos ou desatualizados")
            if not acct.reconciled:
                reasons.append("estado local diverge da corretora")
            if acct.equity > 0 and acct.day_pnl <= -lim.max_daily_loss_pct * acct.equity:
                reasons.append(
                    f"perda do dia ({acct.day_pnl:.2f}) atingiu o limite de "
                    f"{lim.max_daily_loss_pct:.0%} do patrimônio"
                )

        if side not in ("buy", "sell"):
            reasons.append(f"lado inválido: {order.side!r}")
        if order.notional < lim.min_order_notional_usd:
            reasons.append(f"valor {order.notional:.2f} abaixo do mínimo de {lim.min_order_notional_usd:.2f}")
        if acct.orders_today >= lim.max_orders_per_day:
            reasons.append(f"limite de {lim.max_orders_per_day} ordens por dia atingido")

        if side == "sell" and not lim.allow_short and order.notional > held + 1e-6:
            reasons.append(
                f"venda de {order.notional:.2f} maior que a posição de {held:.2f} (venda a descoberto bloqueada)"
            )

        if is_entry:
            if order.notional > acct.cash + 1e-6:
                reasons.append(f"caixa insuficiente: {acct.cash:.2f} para ordem de {order.notional:.2f}")

            exposure = held + order.notional
            cap = lim.max_exposure_per_asset_pct * acct.equity
            if exposure > cap + 1e-6:
                reasons.append(f"exposição em {order.symbol} ({exposure:.2f}) acima do limite de {cap:.2f}")

            open_positions = sum(1 for v in acct.positions.values() if v > 0)
            if held <= 0 and open_positions >= lim.max_open_positions:
                reasons.append(f"já existem {open_positions} posições abertas (máximo {lim.max_open_positions})")

            if order.stop_price is None:
                if lim.require_stop_on_entry:
                    reasons.append("entrada sem stop definido")
            elif order.stop_price >= order.entry_price:
                reasons.append("stop acima ou igual ao preço de entrada em uma compra")
            else:
                loss_at_stop = order.notional * (order.entry_price - order.stop_price) / order.entry_price
                max_loss = lim.risk_per_trade_pct * acct.equity
                if loss_at_stop > max_loss + 1e-9:
                    reasons.append(
                        f"perda até o stop ({loss_at_stop:.2f}) acima do risco por operação ({max_loss:.2f})"
                    )

        return RiskVerdict(approved=not reasons, reasons=reasons)


def max_notional_for_risk(equity: float, entry: float, stop: float, limits: RiskLimits) -> float:
    """Maior valor de compra que respeita o risco por operação e a exposição por ativo."""
    if stop >= entry:
        return 0.0
    by_risk = limits.risk_per_trade_pct * equity * entry / (entry - stop)
    by_exposure = limits.max_exposure_per_asset_pct * equity
    return max(0.0, min(by_risk, by_exposure))
