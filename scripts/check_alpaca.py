"""Verificação da conta paper e dos dados. Só lê; não envia nenhuma ordem.

Uso (na raiz do projeto, com o ambiente virtual ativo):
    python scripts/check_alpaca.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config.settings import ConfigError, load_settings  # noqa: E402
from agent.data import market_data  # noqa: E402
from agent.data.validation import validate_daily_bars  # noqa: E402

SYMBOLS = ["SPY", "AAPL"]
TARGET_PAPER_EQUITY = 18.50


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"[config] {exc}")
        return 1
    print(f"[config] modo paper, chave {settings.masked_key()}, feed {settings.data_feed}")

    from agent.execution.alpaca_paper import PaperBroker

    broker = PaperBroker(settings)
    acct = broker.raw_account()
    print("\n[conta]")
    for attr in ("status", "equity", "cash", "buying_power", "multiplier",
                 "pattern_day_trader", "daytrade_count", "trading_blocked"):
        print(f"  {attr}: {getattr(acct, attr, 'n/d')}")
    equity = float(acct.equity)
    if abs(equity - TARGET_PAPER_EQUITY) > 1:
        print(f"  aviso: patrimônio de {equity:.2f}; o documento prevê cerca de US$ {TARGET_PAPER_EQUITY:.2f}."
              " Crie uma conta paper nova com esse saldo no painel da Alpaca.")
    if str(getattr(acct, "multiplier", "1")) not in ("1", "1.0"):
        print("  aviso: a conta tem margem (multiplier > 1). O motor de risco bloqueia alavancagem,"
              " mas o poder de compra exibido não reflete o caixa real.")

    clock = market_data.market_clock(settings)
    print(f"\n[relógio] mercado aberto: {clock.is_open}; próxima abertura {clock.next_open};"
          f" próximo fechamento {clock.next_close}")

    end = date.today()
    start = end - timedelta(days=60)
    sessions = market_data.trading_sessions(settings, start, end)
    session_days = [s["date"] for s in sessions]
    last_complete = market_data.last_complete_session(settings)
    print(f"[calendário] {len(sessions)} pregões entre {start} e {end};"
          f" último pregão completo: {last_complete}")

    print("\n[dados]")
    feeds = [settings.data_feed] + (["iex"] if settings.data_feed == "sip" else [])
    bars = {}
    for feed in feeds:
        try:
            bars = market_data.daily_bars(settings, SYMBOLS, start, feed=feed)
            print(f"  feed {feed}: ok")
            break
        except Exception as exc:  # o plano gratuito pode recusar o feed SIP
            print(f"  feed {feed}: falhou ({exc}); tentando o próximo")
    if not bars:
        print("  nenhum dado recebido")
        return 1

    all_ok = True
    for sym, df in bars.items():
        rep = validate_daily_bars(df, sym, expected_sessions=session_days,
                                  last_expected_session=last_complete)
        print("  " + rep.summary().replace("\n", "\n  "))
        print(f"    último candle: {df.index[-1]} fechamento {df['close'].iloc[-1]:.2f}")
        all_ok &= rep.ok

    print("\nResultado:", "tudo certo" if all_ok else "há problemas acima para verificar")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
