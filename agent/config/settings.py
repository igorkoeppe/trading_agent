"""Configuração do ambiente. O projeto roda somente em paper trading.

Regras de segurança:
- só existe o modo "paper"; qualquer outro valor de TRADING_MODE interrompe a execução;
- o endereço da API precisa ser o de paper;
- as chaves são lidas de variáveis de ambiente (arquivo .env local), nunca do código.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALLOWED_FEEDS = {"sip", "iex"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """Configuração inválida ou insegura."""


@dataclass(frozen=True)
class Settings:
    key_id: str
    secret_key: str
    base_url: str
    data_feed: str
    mode: str = "paper"

    @property
    def paper(self) -> bool:
        return True  # não existe outro modo nesta fase do projeto

    def masked_key(self) -> str:
        return self.key_id[:4] + "..." if self.key_id else "(vazia)"


def _load_dotenv(path: Path | None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv é opcional; variáveis podem vir do sistema
        return
    load_dotenv(path or PROJECT_ROOT / ".env", override=False)


def load_settings(env: dict | None = None, dotenv_path: Path | None = None) -> Settings:
    """Lê e valida a configuração. `env` permite testes sem tocar no ambiente real."""
    if env is None:
        _load_dotenv(dotenv_path)
        env = dict(os.environ)

    mode = env.get("TRADING_MODE", "paper").strip().lower()
    if mode != "paper":
        raise ConfigError(
            f"TRADING_MODE={mode!r} não é permitido. Este projeto só roda em paper trading."
        )

    base_url = env.get("ALPACA_PAPER_BASE_URL", PAPER_BASE_URL).strip().rstrip("/")
    if base_url != PAPER_BASE_URL:
        raise ConfigError(
            f"ALPACA_PAPER_BASE_URL={base_url!r} não é o endereço de paper ({PAPER_BASE_URL})."
        )

    key_id = env.get("ALPACA_PAPER_KEY_ID", "").strip()
    secret = env.get("ALPACA_PAPER_SECRET_KEY", "").strip()
    if not key_id or not secret:
        raise ConfigError(
            "Chaves de paper ausentes. Copie .env.example para .env e preencha "
            "ALPACA_PAPER_KEY_ID e ALPACA_PAPER_SECRET_KEY."
        )
    # Chaves de conta real da Alpaca começam com "AK"; as de paper, com "PK".
    if key_id.upper().startswith("AK"):
        raise ConfigError("A chave informada parece ser de conta REAL (prefixo AK). Use a chave de paper.")

    feed = env.get("ALPACA_DATA_FEED", "sip").strip().lower()
    if feed not in ALLOWED_FEEDS:
        raise ConfigError(f"ALPACA_DATA_FEED={feed!r} inválido; use 'sip' ou 'iex'.")

    return Settings(key_id=key_id, secret_key=secret, base_url=base_url, data_feed=feed)
