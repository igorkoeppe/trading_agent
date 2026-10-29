# Pré-registro v1 (CONGELADO em 2026-10-28)

Este documento fixa, antes de qualquer backtest, o que será testado e o que conta como sucesso.
Os números ficam em `prereg_v1.yaml`. Depois do congelamento, nada aqui muda. Se algo precisar mudar,
cria-se um `prereg_v2` antes de olhar resultados novos, e o teste final continua sem ser tocado.

## Pergunta

A estratégia de referência (A) tem vantagem líquida de custos fora da amostra? Kronos (B) acrescenta
algo sobre A? O filtro LLM (C) reduz perdas sem cortar os ganhos? Responder "não" é um resultado válido.

## Dados e períodos

| Uso | Período |
| --- | --- |
| Desenvolvimento e walk-forward | 2016-01-01 a 2024-12-31 |
| Teste final (intocado, uma única vez) | 2025-01-01 a 2026-09-30 |
| Paper trading prospectivo | 6 meses, a partir da Fase 7 |

- Barras diárias SIP da Alpaca, ajustadas por splits e dividendos.
- O código só carrega o período do teste final por um script próprio, rodado após o congelamento.
- Limitação conhecida: o universo (20 ativos de hoje) tem viés de sobrevivência. Os ETFs
  reduzem o problema; as ações individuais não. Resultados de ações valem menos que os de ETFs.

## Walk-forward

Treino expansivo a partir de 3 anos (2016–2018). Teste em janelas de 6 meses, andando de 6 em 6 meses
(2019-01 em diante). Só resultados das janelas de teste entram nas métricas.

## Simulação de execução

- Sinal calculado no fechamento do pregão t; compra na abertura de t+1. O candle do dia em andamento
  nunca entra na decisão.
- Slippage de 5 bps por lado (estresse: 10 bps). Comissão zero. O paper da Alpaca não simula
  slippage, então esse número é premissa e será comparado ao observado no paper (gate C5).
- Stop em 2×ATR(14). Se o preço abrir abaixo do stop, executa na abertura (gap), não no preço do stop.
- Saída por tempo em 10 pregões. Risco de 1% do patrimônio por operação, máximo de 3 posições, sem short.
- Resultados medidos em múltiplos de R (risco por operação), o que independe do capital. Com US$ 18,50
  o arredondamento de ordens distorce os números reais; por isso o backtest não usa o capital real.

## Estratégia A (referência)

Setups de `find_setups` (breakout e retomada da média de 20) com os parâmetros originais, sem otimização
prévia. Qualquer variação de parâmetro conta como configuração testada e é registrada em
`log_configuracoes.jsonl`. Limite: 12 configurações. Passar disso invalida o gate G6, porque quanto mais
combinações testadas, maior a chance de um acerto por sorte.

## Gates

**A passa se todos valerem, nas janelas fora da amostra agregadas:**

| Gate | Critério |
| --- | --- |
| G1 | pelo menos 100 operações |
| G2 | expectativa líquida ≥ +0,10 R por operação |
| G3 | limite inferior do IC 90% (bootstrap) da expectativa > 0 |
| G4 | fator de lucro ≥ 1,3 |
| G5 | drawdown máximo ≤ 20% |
| G6 | pelo menos 60% das janelas de 6 meses positivas |
| G7 | expectativa ainda ≥ 0 com slippage de 10 bps |
| G8 | Sharpe maior que o do SPY comprado e mantido no mesmo período |

**B (A + Kronos), nas mesmas janelas:** ganho de expectativa ≥ +0,05 R sobre A, com IC 90% pareado
acima de zero, drawdown não pior que o de A, pelo menos 100 operações, e 20 amostras individuais por
previsão (a média interna do `predict` esconde a incerteza).

**C (B + LLM):** só em paper prospectivo, porque um LLM treinado com dados até 2026 já conhece o que aconteceu
no backtest. Mínimo de 6 meses e 100 operações; as operações vetadas devem ter R médio menor que as
mantidas; drawdown não pior que B; slippage observado até 2× o assumido.

## O que acontece se não passar

- A falha em algum gate: o projeto não avança para Kronos. Revisamos a hipótese num novo pré-registro,
  sem tocar no teste final.
- A passa no desenvolvimento e falha no teste final: resultado negativo, registrado como tal.
- Nenhum gate muda para "fazer passar".

## Decisões aprovadas (2026-10-28)

1. Gates numéricos aprovados como estão.
2. Universo: os 20 ativos de `config/universe.yaml`. Os gates valem para os 20. Os resultados dos 8 ETFs
   (SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV) são reportados ao lado, como leitura sem viés de sobrevivência.
3. Teste final em 2025-01 a 2026-09, rodado uma única vez, e limite de 12 configurações.

## Congelamento

`prereg_v1.sha256` guarda o SHA-256 deste arquivo, do `prereg_v1.yaml` e do `config/universe.yaml`.
Qualquer diferença depois disso significa que o pré-registro foi alterado e os resultados não valem.
