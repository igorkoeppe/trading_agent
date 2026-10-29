"""Teste da execução na conta PAPER da Alpaca (Fase 2).

Sem argumentos: só lê e mostra o estado (conta, posições, ordens, reconciliação). Não envia nada.

    python scripts\\phase2_smoke.py              # status, somente leitura
    python scripts\\phase2_smoke.py --send       # compra US$ 1,00 de SPY e coloca o stop 5% abaixo
    python scripts\\phase2_smoke.py --stops      # reenvia stops que expiraram (rotina diária)
    python scripts\\phase2_smoke.py --exit       # vende a posição de SPY e remove o stop
    python scripts\\phase2_smoke.py --kill       # aciona o kill switch (cancela compras pendentes)
    python scripts\\phase2_smoke.py --unkill     # desativa o kill switch

--send exige o mercado aberto (09h30 a 16h00 de Nova York).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config.settings import ConfigError, load_settings  # noqa: E402
from agent.data import market_data  # noqa: E402
from agent.data.validation import validate_daily_bars  # noqa: E402
from agent.execution.alpaca_paper import PaperBroker  # noqa: E402
from agent.execution.order_manager import OrderManager, OrderManagerError  # noqa: E402
from agent.risk.kill_switch import trigger_kill_switch  # noqa: E402
from agent.risk.risk_engine import OrderIntent, RiskEngine, RiskLimits  # noqa: E402

NY = ZoneInfo("America/New_York")
SYMBOL, STRATEGY, NOTIONAL, STOP_PCT = "SPY", "SMOKE", 1.00, 0.05


def show_status(broker: PaperBroker, mgr: OrderManager) -> None:
    acct = broker.account()
    print(f"[conta] patrimônio {acct.equity:.2f}  caixa {acct.cash:.2f}")
    pos = broker.positions()
    print(f"[posições] {', '.join(f'{s} {p.qty}' for s, p in pos.items()) or 'nenhuma'}")
    orders = broker.open_orders()
    print(f"[ordens abertas] {len(orders)}")
    for o in orders:
        print(f"  {o.symbol} {o.side} {o.type} {o.status} qty={o.qty} stop={o.stop_price}")
    print(f"[estado local] {mgr.state.positions or 'vazio'}")
    ks = mgr.kill_switch
    print(f"[kill switch] {'ATIVO: ' + ks.reason if ks.active else 'desativado'}")
    print("[reconciliação]", mgr.reconcile().summary())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag in ("send", "stops", "exit", "kill", "unkill"):
        ap.add_argument(f"--{flag}", action="store_true")
    args = ap.parse_args()

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"[config] {exc}")
        return 1

    broker = PaperBroker(settings)
    mgr = OrderManager(broker, RiskEngine(RiskLimits.from_yaml()))
    session = datetime.now(NY).date()

    if args.unkill:
        mgr.kill_switch.deactivate()
        print("kill switch desativado")
    if args.kill:
        ids = trigger_kill_switch(mgr.kill_switch, broker, "acionado manualmente pelo smoke test")
        print(f"kill switch ativo; {len(ids)} ordens de compra canceladas; stops e posições mantidos")

    if args.stops:
        placed = mgr.ensure_stops(session)
        print(f"stops reenviados: {[(o.symbol, o.stop_price) for o in placed] or 'nenhum'}")

    if args.exit:
        try:
            out = mgr.submit_exit(SYMBOL, session, "smoke")
            print(f"saída: {out.status}, executado {out.filled_qty} a {out.filled_avg_price}")
        except OrderManagerError as exc:
            print(f"nada para vender: {exc}")

    if args.send:
        if not market_data.market_clock(settings).is_open:
            print("O mercado está fechado. Rode --send entre 09h30 e 16h00 de Nova York.")
            return 1
        start = session - timedelta(days=60)
        bars = market_data.daily_bars(settings, [SYMBOL], start)[SYMBOL]
        last_complete = market_data.last_complete_session(settings)
        sessions = [s["date"] for s in market_data.trading_sessions(settings, start, session)]
        rep = validate_daily_bars(bars, SYMBOL, expected_sessions=sessions, last_expected_session=last_complete)
        print(rep.summary())
        ref = float(bars["close"].iloc[-1])
        intent = OrderIntent(SYMBOL, "buy", NOTIONAL, ref, round(ref * (1 - STOP_PCT), 2))
        print(f"enviando compra de US$ {NOTIONAL:.2f} de {SYMBOL} (referência {ref:.2f}, stop {intent.stop_price})")
        res = mgr.submit_entry(intent, STRATEGY, session, data_ok=rep.ok)
        if res.blocked:
            print("BLOQUEADA pelo motor de risco:", *res.blocked_reasons, sep="\n  ")
        elif res.already_existed:
            print("já existia uma ordem com este ID hoje; nada foi reenviado:", res.order.status)
        else:
            print(f"compra: {res.order.status}, {res.order.filled_qty} a {res.order.filled_avg_price}")
            print(f"stop: {res.stop_order.status if res.stop_order else 'NÃO COLOCADO'}"
                  f" (preço {res.stop_order.stop_price if res.stop_order else '-'})")
            for n in res.notes:
                print("  nota:", n)

    print()
    show_status(broker, mgr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
