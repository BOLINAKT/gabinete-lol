# Smoke Manual (5 Cenarios)

Objetivo: validar estabilidade funcional do app sem alterar codigo.

## Preparacao
1. Inicie o app normalmente.
2. Limpe filtros muito restritivos (odd maxima, exigir H2H, exigir modelo) para evitar falso negativo.
3. Em cada cenario, ao final clique nos expanders de trace (Resumo e Players) e confirme que existem linhas.
4. Depois rode: `python tools/check_smoke_trace.py`

## Cenario 1 - Favorito forte (ex.: LNG vs TT)
1. Selecione confronto de favorito claro.
2. Confira `Visao Geral`: ML Mapa, MD3, MD5 preenchidos.
3. Abra `Resumo`: deve haver picks e colunas `Odd (Modelo)`, `Odd (Hist)`, `Odd (Mix)`, `Laplace (Liga)`, `Laplace (H2H)`.
4. Aceite se:
- Nao houver erro na tela.
- `ml_trace_last.json` tiver `ml_trace` e `resumo_markets_trace`.

## Cenario 2 - Jogo equilibrado (ex.: WE vs TES)
1. Selecione confronto proximo de 50/50.
2. Altere apenas uma vez um filtro leve (ex.: odd maxima 2.00 -> 2.20) e volte.
3. Aceite se:
- Odds mudarem de forma coerente com filtro.
- Sem "sumico" de abas ou tabelas.

## Cenario 3 - Top vs Top (ex.: Gen.G vs T1)
1. Abra `Consistencia de Mercado (Laplace)` e troque entre sub-abas (Kills, Torres, Dragões, Tempo, ML+Totais).
2. Aceite se:
- Cards/tabelas carregarem sem erro.
- Ao trocar sub-aba, os blocos mudarem conforme o mercado selecionado.

## Cenario 4 - Players (linhas individuais)
1. Aba `Players`: use auto-preencher por times.
2. Informe algumas linhas (ex.: kills top A=2.5, top B=2.5, mid A=3.5).
3. Clique `Analisar players`.
4. Aceite se:
- `Medias por jogador`, `Fair (Modelo)` e `Mercados de Players` aparecerem.
- Sem erro de chave duplicada Streamlit.
- `players_trace` existir no `ml_trace_last.json`.

## Cenario 5 - Reprodutibilidade de sessao
1. No mesmo confronto, clique "Editar linhas", salve sem alterar valores.
2. Reanalise.
3. Aceite se:
- Sem mudanca abrupta injustificada de odd (drift pequeno aceitavel).
- Guardioes/trace continuam ativos.

## Checklist de aprovacao
- [ ] Nenhum erro Streamlit na tela.
- [ ] `ml_trace_last.json` gerado e atualizado.
- [ ] Chaves obrigatorias no trace: `ml_trace`, `resumo_markets_trace`, `players_trace`.
- [ ] Abas principais funcionando: Visao Geral, Resumo, Consistencia, Players.
- [ ] Sem texto quebrado (mojibake) relevante em labels principais.

