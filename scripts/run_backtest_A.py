"""Backtest walk-forward da Configuração A no período de DESENVOLVIMENTO (pré-registro v1).

    python scripts\\run_backtest_A.py            # usa o cache em data_cache/ quando existir
    python scripts\\run_backtest_A.py --refresh  # baixa os candles de novo

Não toca no período do teste final. Resultado em experiments/results/A_dev.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.backtesting.data import load_daily  # noqa: E402
from agent.backtesting.engine import SimParams, simulate  # noqa: E402
from agent.backtesting.guard import EXPERIMENTS, assert_dev_only, load_prereg  # noqa: E402
from agent.backtesting.metrics import evaluate_gates_A, oos_windows, report, sharpe  # noqa: E402
from agent.backtesting.signals import SETUPS_A  # noqa: E402
from agent.config.settings import PROJECT_ROOT, load_settings  # noqa: E402

CONFIG_NAME = "A1_find_setups_breakout_reclaim"


def config_id(params: SimParams) -> str:
    blob = json.dumps({"nome": CONFIG_NAME, "setups": SETUPS_A, "params": asdict(params)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def log_config(path: Path, cid: str, params: SimParams) -> int:
    """Registra a configuração e devolve quantas configurações distintas já foram testadas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if path.exists():
        seen = {json.loads(l)["config_id"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}
    if cid not in seen:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"config_id": cid, "nome": CONFIG_NAME, "setups": list(SETUPS_A),
                                "params": asdict(params),
                                "utc": datetime.now(timezone.utc).isoformat()}) + "\n")
        seen.add(cid)
    return len(seen)


def run(bars, universe, pr, first_test, end, spy_sharpe, n_configs, max_configs):
    base_p = SimParams.from_prereg(pr.raw)
    stress_p = SimParams.from_prereg(pr.raw, pr.raw["execucao_simulada"]["slippage_bps_estresse"])
    wins = oos_windows(first_test, end, pr.raw["walk_forward"]["janela_teste_meses"])
    base = simulate(bars, base_p, first_test, end, universe)
    stress = simulate(bars, stress_p, first_test, end, universe)
    rb, rs = report(base.trades, base.equity, wins), report(stress.trades, stress.equity, wins)
    gates = evaluate_gates_A(pr.raw["gates_config_A"], rb, rs, spy_sharpe, n_configs, max_configs)
    return rb, rs, gates, base


def fmt(v):
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, dict):
        return ", ".join(f"{k}={fmt(x)}" for k, x in v.items())
    return str(v)


def print_block(title, rb, rs, gates):
    print(f"\n=== {title} ===")
    print(f"operações {rb.n} | expectativa {rb.mean_r:.3f} R | IC90 [{rb.ci90[0]:.3f}, {rb.ci90[1]:.3f}]"
          f" | acerto {rb.win_rate:.1%} | fator de lucro {rb.profit_factor:.2f}")
    print(f"drawdown máx {rb.max_dd:.1%} | Sharpe {rb.sharpe:.2f} | janelas positivas {rb.frac_windows_positive:.0%}"
          f" | estresse: {rs.mean_r:.3f} R | saídas {rb.exits}")
    for k, g in gates.items():
        print(f"  {k} {'PASSOU' if g['passou'] else 'FALHOU'}  valor {fmt(g['valor'])}  ({g['criterio']})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    pr = load_prereg()   # confere os hashes do congelamento
    settings = load_settings()
    universe = yaml.safe_load((PROJECT_ROOT / pr.raw["dados"]["universo"]).read_text(encoding="utf-8"))["symbols"]
    etfs = pr.raw["dados"]["relatorio_separado"]
    start, end = pr.dev_start, pr.dev_end
    first_test = (pd.Timestamp(start) + pd.DateOffset(years=pr.raw["walk_forward"]["treino_inicial_anos"])).date()

    bars = load_daily(settings, universe, start, end, refresh=args.refresh)
    assert_dev_only(bars, end)
    for s, df in bars.items():
        print(f"{s}: {len(df)} candles, {df.index.min().date()} a {df.index.max().date()}")

    spy = bars["SPY"]["close"]
    spy_sharpe = sharpe(spy[(spy.index >= pd.Timestamp(first_test)) & (spy.index <= pd.Timestamp(end))])
    max_configs = pr.raw["busca_de_parametros"]["max_configuracoes_testadas"]
    cid = config_id(SimParams.from_prereg(pr.raw))
    n_configs = log_config(PROJECT_ROOT / pr.raw["busca_de_parametros"]["registrar_em"], cid, SimParams.from_prereg(pr.raw))

    rb, rs, gates, base = run(bars, universe, pr, first_test, end, spy_sharpe, n_configs, max_configs)
    eb, es, egates, _ = run({s: bars[s] for s in etfs}, etfs, pr, first_test, end, spy_sharpe, n_configs, max_configs)

    print(f"\nperíodo fora da amostra: {first_test} a {end} | configuração {cid} | configs testadas: {n_configs}/{max_configs}")
    print(f"SPY comprado e mantido: Sharpe {spy_sharpe:.2f}")
    print_block("Configuração A, 20 ativos (vale para os gates)", rb, rs, gates)
    print_block("Somente ETFs (informativo, sem viés de sobrevivência)", eb, es, egates)
    verdict = all(g["passou"] for g in gates.values())
    print(f"\nVEREDITO (20 ativos): {'A PASSOU em todos os gates' if verdict else 'A NÃO passou'}")

    out = EXPERIMENTS / "results" / "A_dev.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "config_id": cid, "periodo_oos": [str(first_test), str(end)], "spy_sharpe": spy_sharpe,
        "configs_testadas": n_configs, "veredito": verdict,
        "universo_20": {"base": rb.as_dict(), "estresse": rs.as_dict(), "gates": gates},
        "etfs": {"base": eb.as_dict(), "estresse": es.as_dict(), "gates": egates},
        "operacoes": [{**{k: (str(v) if hasattr(v, "isoformat") else v) for k, v in t.__dict__.items()},
                       "R": t.r_multiple} for t in base.trades],
        "utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"resultado salvo em {out.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
