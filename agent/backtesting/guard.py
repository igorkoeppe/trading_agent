"""Trava do pré-registro.

- Confere o hash dos arquivos congelados antes de qualquer backtest.
- Impede que dados do período de teste final entrem no desenvolvimento.
- O teste final só abre uma vez: depois de rodar, fica registrado em `final_test_done.json`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from agent.config.settings import PROJECT_ROOT

EXPERIMENTS = PROJECT_ROOT / "experiments"
PREREG_YAML = EXPERIMENTS / "prereg_v1.yaml"
PREREG_HASHES = EXPERIMENTS / "prereg_v1.sha256"
FINAL_DONE = EXPERIMENTS / "final_test_done.json"


class PreregError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_hashes(hash_file: Path = PREREG_HASHES, root: Path = PROJECT_ROOT) -> None:
    """Falha se qualquer arquivo congelado mudou desde o congelamento."""
    if not hash_file.exists():
        raise PreregError(f"arquivo de hashes não encontrado: {hash_file}")
    bad = []
    for line in hash_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(maxsplit=1)
        p = root / rel.strip().lstrip("*")
        if not p.exists() or _sha256(p) != digest:
            bad.append(rel.strip())
    if bad:
        raise PreregError("pré-registro alterado depois do congelamento: " + ", ".join(bad))


@dataclass(frozen=True)
class Prereg:
    raw: dict

    @property
    def dev_start(self) -> date:
        return date.fromisoformat(self.raw["dados"]["desenvolvimento"]["inicio"])

    @property
    def dev_end(self) -> date:
        return date.fromisoformat(self.raw["dados"]["desenvolvimento"]["fim"])

    @property
    def final_start(self) -> date:
        return date.fromisoformat(self.raw["dados"]["teste_final"]["inicio"])

    @property
    def final_end(self) -> date:
        return date.fromisoformat(self.raw["dados"]["teste_final"]["fim"])


def load_prereg(path: Path = PREREG_YAML, check_hashes: bool = True) -> Prereg:
    if check_hashes:
        verify_hashes()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("status") != "congelado":
        raise PreregError("o pré-registro não está congelado")
    return Prereg(raw)


def assert_dev_only(bars: dict[str, pd.DataFrame], dev_end: date) -> None:
    """Falha se algum candle passar do fim do período de desenvolvimento."""
    for sym, df in bars.items():
        if len(df) and pd.Timestamp(df.index.max()).date() > dev_end:
            raise PreregError(f"{sym}: dados depois de {dev_end} no desenvolvimento")


def open_final_test(prereg: Prereg, done_file: Path = FINAL_DONE) -> None:
    """Libera o teste final uma única vez. Grava a marca ANTES de carregar os dados."""
    if done_file.exists():
        info = json.loads(done_file.read_text(encoding="utf-8"))
        raise PreregError(f"o teste final já foi rodado em {info.get('utc')}; não pode ser repetido")
    done_file.write_text(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
                                     "periodo": [str(prereg.final_start), str(prereg.final_end)]}),
                         encoding="utf-8")
