"""Registro em JSON Lines: um evento por linha, com horário UTC.

Usado para sinais, decisões, ordens e chamadas ao LLM (replay). Os arquivos ficam em
logs/, que não é versionado.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.config.settings import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"


def read_events(stream: str, log_dir: Path = LOG_DIR) -> list[dict]:
    """Eventos já gravados em `stream`, do mais antigo ao mais novo."""
    path = log_dir / f"{stream}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def log_event(stream: str, event: dict, log_dir: Path = LOG_DIR) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{stream}.jsonl"
    record = {"ts_utc": datetime.now(timezone.utc).isoformat(), **event}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path
