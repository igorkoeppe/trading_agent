# Market Research: agente de trading em paper

Plataforma de pesquisa em trading com horizonte diário, só em paper trading na Alpaca.
O desenho completo está no documento "Agente de Trading — Proposta revisada v2.0".

**Estado:** Fase 3 (estratégia de referência e backtest). Pré-registro v1 congelado em 2026-10-28.

## Instalação no Windows (PowerShell)

Requer Python 3.10 ou mais novo (o Kronos exige 3.10+). Na pasta do projeto:

```powershell
py -3 --version                      # confira a versão
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1         # se bloquear: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env               # depois abra o .env e cole as chaves de PAPER
```

## Verificações da Fase 1

```powershell
pytest                               # testes offline do núcleo
python scripts\check_alpaca.py       # conta paper, relógio, calendário e candles validados
```

Para a GPU (opcional agora, necessário na Fase 4): instale o PyTorch com CUDA conforme
`requirements-gpu.txt` e rode `python scripts\check_gpu.py`.

## Fase 2: execução na conta paper

```powershell
python scripts\phase2_smoke.py            # somente leitura: conta, posições, ordens, reconciliação
python scripts\phase2_smoke.py --send     # compra US$ 1,00 de SPY e coloca o stop 5% abaixo (mercado aberto)
python scripts\phase2_smoke.py --stops    # reenvia stops que expiraram (rotina de cada pregão)
python scripts\phase2_smoke.py --kill     # kill switch: cancela compras pendentes, mantém stops
python scripts\phase2_smoke.py --exit     # vende a posição e remove o stop
```

Regras da execução (detalhes em `docs/fase2_execucao.md`):

- ordem repetida com o mesmo sinal não é reenviada (mesmo `client_order_id`);
- se a rede cair no envio, o sistema consulta a corretora antes de tentar de novo;
- divergência entre estado local e corretora bloqueia novas entradas;
- o kill switch cancela compras pendentes, mas **mantém os stops** e não fecha posições;
- stops de ordens fracionadas valem só no dia: `--stops` precisa rodar todo pregão.

## Fase 3: backtest da Configuração A

```powershell
python scripts\run_backtest_A.py            # walk-forward 2019-2024, gates do pré-registro
python scripts\run_backtest_A.py --refresh  # baixa os candles de novo (cache em data_cache\)
```

- Antes de rodar, o script confere o hash do pré-registro; se algo mudou, ele para.
- Só usa dados de 2016 a 2024. O teste final (2025-01 a 2026-09) tem trava própria e só abre uma vez.
- Cada configuração testada fica em `experiments/log_configuracoes.jsonl` (limite: 12).
- Resultado completo, com todas as operações, em `experiments/results/A_dev.json`.

## Estrutura

```text
agent/
  config/settings.py        modo paper obrigatório, chaves do .env
  data/market_data.py       candles diários e calendário da Alpaca; descarta candle incompleto
  data/validation.py        checagens de OHLCV, buracos e dados velhos
  quant/indicators.py       SMA, RSI de Wilder, volatilidade EWMA, ATR
  quant/setups.py           setups diários portados do day-trader-skill
  risk/risk_engine.py       limites de risco independentes dos modelos
  execution/order_ids.py    client_order_id determinístico (idempotência)
  execution/broker_api.py   interface de corretora (permite testar com corretora simulada)
  execution/alpaca_paper.py adaptador da Alpaca paper
  execution/order_manager.py entrada idempotente, stops diários, saída, reconciliação
  execution/state.py        estado local das posições (escrita atômica)
  backtesting/engine.py     simulador diário (abertura t+1, stop ATR com gap, saída por tempo)
  backtesting/metrics.py    métricas em R, bootstrap, janelas, gates
  backtesting/guard.py      trava do pré-registro e do teste final
  risk/kill_switch.py       kill switch persistente
  risk/reconciliation.py    compara estado local com a corretora
  monitoring/logger.py      eventos em JSON Lines
config/                     limites de risco e universo provisório
strategies/                 definições versionadas de estratégia (Fase 3)
experiments/                hipóteses pré-registradas e resultados
scripts/                    verificações manuais
docs/                       inventário do day-trader-skill e notas técnicas
tests/                      testes offline (pytest)
```

## Regras de segurança

- `TRADING_MODE` só aceita `paper`; o endereço da API precisa ser o de paper.
- Chaves ficam no `.env`, que o `.gitignore` exclui. Não cole chaves em conversas.
- Toda ordem passa pelo motor de risco; entradas exigem stop.
- O candle do pregão em andamento nunca entra numa decisão diária.

## Créditos

`agent/quant/setups.py` e `rsi_wilder` portam regras do
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT, Jake Schincariol).
