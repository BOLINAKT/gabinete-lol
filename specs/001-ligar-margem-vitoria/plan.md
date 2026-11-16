# Implementation Plan: Ligar a margem de vitória no rating

**Branch**: `001-ligar-margem-vitoria` | **Date**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-ligar-margem-vitoria/spec.md`

## Summary

Ligar, em produção, a margem de vitória no fit do WHR (ouro aos 15 min, peso 0,35,
folga 0,15) e desligar a bandeira do `patch_meta_guard`.

**O mecanismo já existe e está testado.** Esta entrega não constrói modelagem nova:
ela troca dois valores de configuração, retreina, verifica e publica. O trabalho
real é de **verificação**, não de implementação.

## Technical Context

**Language/Version**: Python 3.13 (venv do projeto em `.venv`)

**Primary Dependencies**: numpy, pandas, streamlit (app). Sem dependência nova.

**Storage**: `ml_artifact.json` e `players_artifact.json` (JSON versionados em git)

**Testing**: `python -m unittest discover -s mlcore/tests -p "test_*.py"` — 4.795 testes

**Target Platform**: app Streamlit local (Windows) + robô no GitHub Actions

**Project Type**: biblioteca de modelagem + app de leitura

**Performance Goals**: o treino completo leva ~6 min por execução; sem requisito novo

**Constraints**:
- O artefato é lido pelo app **e** pelo robô. Formato não pode quebrar.
- O robô roda `update_incremental` 3x/dia, que **não conhece margem**.
- Rollback tem que ser de uma linha.

**Scale/Scope**: ~28.700 jogos na base; 2 arquivos de configuração mudam; 0 arquivos
de modelagem mudam.

**NEEDS CLARIFICATION**: quanto do ganho medido (+0,00573) se perde porque o robô
aplica os jogos novos sem margem entre um treino completo e outro? Resolvido na
Fase 0.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| princípio | status | evidência |
|---|---|---|
| **I** — pesquisar antes de decidir | **PASSA** | MOVDA, G-Elo, Weighted Elo e Bradley-Terry fracionário abertos e citados em `mlcore/whr_core.py` e `tools/eval_whr_mov.py` |
| **II** — medir fora da amostra | **PASSA** | 7 dobras, cadência diária, calibrador aplicado, corte temporal estrito; 7.359 jogos, nenhum visto no treino |
| **III** — a barra decide | **PASSA com ressalva** | margem: +0,00573, IC [+0,00396, +0,00751], p<1e-8. Guard: ver Complexity Tracking |
| **IV** — ausência não vira número | **PASSA** | FR-003; `n_mov_faltando` conta e vai ao artefato; 4 testes cobrem |
| **V** — não reimplementar para medir | **PASSA** | a medição chamou `train_offline` de produção por subprocesso; nenhuma matemática reescrita |

**Portão: LIBERADO**, com uma violação declarada abaixo.

## Project Structure

### Documentation (this feature)

```text
specs/001-ligar-margem-vitoria/
├── spec.md          # o que e por quê
├── plan.md          # este arquivo
├── research.md      # Fase 0 — resolve o NEEDS CLARIFICATION
├── quickstart.md    # Fase 1 — como aplicar e como reverter
└── tasks.md         # gerado pelo /speckit-tasks
```

### Source Code (repository root)

```text
mlcore/
├── whr_core.py              # JÁ PRONTO — margem implementada e testada
├── train_offline.py         # JÁ PRONTO — flags --whr-mov*
└── tests/
    └── test_whr_mov.py      # JÁ PRONTO — 18 testes

app_core/
└── ml_settings_runtime_core.py   # MUDA — 1 linha: ml_patch_guard_enabled

tools/
├── atualizar_modelo.py      # MUDA — passar as flags da margem no rebuild
└── nota_honesta.py          # verificação (não muda)

ml_artifact.json             # REGERADO pelo retreino
```

**Structure Decision**: nenhuma estrutura nova. A mudança é de **configuração e
artefato**, não de arquitetura. Dois arquivos de código mudam, e cada um por uma
linha ou duas.

## Complexity Tracking

| Violação | Por que é necessária | Alternativa simples rejeitada porque |
|---|---|---|
| **Desligar o `patch_meta_guard` no nível "warn" não passa a barra cheia** (ganho +0,00129 < 0,002, embora o IC exclua zero) | O guard é uma bandeira só: ou liga nos três níveis, ou desliga nos três. Nos níveis "refit" (+0,00334) e "refit+liga" ele passa folgado. Manter ligado só para o nível "warn" não é opção técnica existente. | Criar um guard com níveis seletivos seria código novo, não medido, para capturar um efeito de −0,00129. Desproporcional ao ganho. |

## Phase 0 — pesquisa (resolve os desconhecidos)

Um item, e é **medição**, não leitura:

**Quanto custa o robô não conhecer a margem?** Entre treinos completos, o
`update_incremental` aplica os jogos novos pelo caminho Elo, sem margem. Se o
treino completo é raro, a maior parte dos jogos recentes entra sem margem — e o
ganho real encolhe.

*Como medir:* simular na régua uma dobra em que o artefato é treinado com margem
mas os jogos da janela entram sem ela, e comparar com a versão em que entram com.
A diferença é o custo do buraco.

*Por que isso importa antes de aplicar:* se o custo for grande, a entrega correta
muda — passa a incluir levar a margem ao `update_incremental`, que é trabalho de
modelagem de verdade e mereceria sua própria especificação.

## Phase 1 — desenho

Sem modelo de dados novo e sem contrato de API novo. O único artefato de desenho
que faz sentido aqui é o **quickstart**: a sequência exata de aplicar, verificar e
reverter, escrita para o dono executar sozinho.
