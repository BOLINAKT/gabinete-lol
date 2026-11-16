# Tasks: Ligar a margem de vitória no rating

**Feature**: 001-ligar-margem-vitoria | **Data**: 2026-09-11
**Entrada**: [spec.md](./spec.md) · [plan.md](./plan.md) · [research.md](./research.md)

## Format: `[ID] [P?] [Story] Description`

- `[P]` = pode rodar em paralelo com outras marcadas `[P]`
- `[US1]`, `[US2]`, `[US3]` = a qual história de usuário pertence

## Path Conventions

Repositório único, sem estrutura nova. Os caminhos abaixo são reais e existem hoje.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] **T001** Criar branch `001-ligar-margem-vitoria` a partir de `master`, com a
      árvore limpa. **A árvore NÃO está limpa hoje** — há 19 arquivos alterados
      desta sessão (ferramentas de medição, testes novos, `whr_core.py`,
      `train_offline.py`). Decidir com o dono: commitar primeiro ou levar junto.
      *Bloqueia tudo: sem isso não há rollback confiável.*

- [ ] **T002** Registrar o estado de partida: rodar `tools/nota_honesta.py` na
      configuração atual e guardar em `evidence/`. É o número contra o qual o
      resultado será comparado. *(Já medido: 7,12 — mas refazer com a árvore da
      branch garante que nada mudou no caminho.)*

---

## Phase 2: Foundational (Blocking Prerequisites)

- [ ] **T003** Confirmar que a suíte está verde **antes** de qualquer mudança:
      `python -m unittest discover -s mlcore/tests -p "test_*.py"`.
      Esperado: 4.795 testes, zero falhas. *Sem isso, qualquer quebra depois fica
      ambígua entre "eu quebrei" e "já estava quebrado".*

- [ ] **T004** Fazer backup do artefato atual (`ml_artifact.json` e
      `players_artifact.json`) com carimbo de data, fora do git.
      *É o rollback de emergência que não depende de git funcionar.*

---

## Phase 3: User Story 1 — A odd reflete um modelo melhor (P1) 🎯 MVP

**Objetivo:** o rating passa a aprender por quanto se ganhou, não só se ganhou.

**Teste independente:** a nota honesta sobe de 7,12 para ≥ 7,30, e o mesmo
confronto produz número diferente no app.

### Implementation for User Story 1

- [ ] **T005** [US1] Em `tools/atualizar_modelo.py`, acrescentar ao comando de
      rebuild as flags `--whr-mov gd15 --whr-mov-lambda 0.35 --whr-mov-folga 0.15`.
      *Uma linha. É aqui que a margem entra em produção — o mecanismo já existe.*

- [ ] **T006** [US1] Retreinar o modelo completo com
      `python tools/atualizar_modelo.py --holdout-days 30`.

- [ ] **T007** [US1] Verificar **FR-004**: o artefato novo contém o bloco
      `meta.whr_mov` com sinal, peso, folga, coeficientes da expectativa e as
      contagens de jogos com e sem margem.

- [ ] **T008** [US1] Verificar **FR-003**: `jogos_sem_margem` está preenchido e é
      da ordem de 8% do total. Se vier zero, é sintoma de que o sinal não está
      chegando — investigar antes de seguir.

- [ ] **T009** [US1] Verificar **SC-006**: o app carrega o artefato novo e serve
      número. Usar a máquina já construída:
      `python tools/caracterizacao_cadeia.py --capturar`.

- [ ] **T010** [US1] Verificar **SC-001 e SC-002**: rodar
      `tools/nota_honesta.py --marca margem --dobras 7 --cadencia diaria --com-hybrid --com-form --extra "--whr-mov gd15 --whr-mov-lambda 0.35 --whr-mov-folga 0.15"`
      e comparar com T002 usando `tools/comparar_variantes.py`.
      **Critério:** ganho > 0,002 e limite inferior do IC diádico > 0.

- [ ] **T011** [US1] Verificar **SC-003**: nenhuma dobra individual piora mais que
      0,20 de nota. *Média boa com uma dobra péssima é alerta, não sucesso.*

---

## Phase 4: User Story 2 — Parar de encolher a confiança sem motivo (P2)

**Objetivo:** desligar o `patch_meta_guard`, que piora a previsão em todos os
níveis porque o calibrador já corrige o que ele tentava corrigir.

**Teste independente:** o traço do pipeline mostra `patch_meta_guard` com
`applied=False`, e o número servido não é mais encolhido.

### Implementation for User Story 2

- [ ] **T012** [US2] Em `app_core/ml_settings_runtime_core.py`, mudar
      `ml_patch_guard_enabled` para `False`, **com comentário** citando a medição
      (−0,00129 no nível "warn", −0,00334 no "refit") e a data.
      *FR-007: só a bandeira. O código do guard fica, para o rollback ser uma linha.*

- [x] **T013** [US2] Rodar a suíte inteira. Algum teste pode depender do guard
      ligado — se falhar, é informação, não obstáculo.

- [x] **T014** [US2] Recapturar o traço com `tools/caracterizacao_cadeia.py
      --capturar` e confirmar `patch_meta_guard: applied=False` nos quatro
      confrontos.

---

## Phase 5: User Story 3 — Rollback em um passo (P3)

**Objetivo:** garantir que dá para voltar sem depender de ninguém.

**Teste independente:** treinar com `--whr-mov off` devolve o artefato de hoje.

### Implementation for User Story 3

- [x] **T015** [US3] Verificar **SC-005 / FR-005**: treinar com `--whr-mov off`
      num caminho de rascunho e comparar os ratings com um **controle**. Devem
      bater bit a bit.
      *Se não baterem, a margem está vazando para o caminho desligado — para tudo.*

      > **CORREÇÃO DE MÉTODO, 11/09/2026.** Esta tarefa dizia "comparar com o
      > artefato de backup (T004)". **Isso está errado e teria dado falso
      > alarme.** O backup `ml_artifact.json.pre_update_*` é uma atualização
      > **incremental** (27 jogos) empilhada sobre um treino completo de 16/08.
      > Um treino completo novo nunca vai bater com ele: a diferença é de
      > cadência, não de margem. Conferido — 0 de 880 ratings iguais, maior
      > diferença 750 pontos, e até os conjuntos de times diferem.
      >
      > **O controle certo é o CÓDIGO de antes da margem rodando nos MESMOS
      > CSVs.** Feito com uma árvore de trabalho no commit `4b86a7d`, com os
      > três CSVs conferidos idênticos por hash de blob, e o mesmo
      > interpretador. Comparação por `tools/comparar_ratings.py`.
      >
      > **RESULTADO: PASSA.** 884 de 884 ratings idênticos bit a bit, mais
      > params, calibrador, forças de liga/tier e os 5.193 jogadores. As
      > métricas do holdout batem dígito a dígito. Única diferença: o
      > carimbo de hora `updated_at`. Evidência em
      > `specs/001-ligar-margem-vitoria/verificacao-rollback.txt`
      > (cópia versionada; `evidence/` é ignorado pelo git por convenção do
      > repositório, e esta prova não pode sumir num formato).

- [x] **T016** [US3] Escrever `specs/001-ligar-margem-vitoria/quickstart.md` com o
      procedimento de reversão em passos numerados, **em português claro**, para o
      dono executar sozinho sem pedir ajuda.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] **T017** [P] Atualizar `MODELO_LOL.md`: a peça "margem de vitória" sai de
      "desligada" para "ligada e medida", com o número e a data.

- [x] **T018** [P] Atualizar `PROTOCOLO_FASE2.md` com o resultado da aplicação —
      o protocolo dizia que a Fase 2 mede e a decisão vem depois; registrar que a
      decisão foi tomada e qual foi.

- [x] **T019** [P] Registrar em `RETOMAR.md` a pendência declarada na pesquisa:
      **o ganho depende de treino completo ~mensal, e não existe treino completo
      programado.** Último foi 16/08.

- [ ] **T020** Commitar com mensagem que diga o ganho medido e o que fica em aberto.

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)  →  Phase 2 (Foundational)  →  Phase 3 (US1)  →  Phase 6 (Polish)
                                             ↘  Phase 4 (US2)  ↗
                                             ↘  Phase 5 (US3)  ↗
```

### User Story Dependencies

- **US1 e US2 são independentes.** Medido: o guard atrapalha com e sem a margem
  (−0,00129 vs −0,00121). Podem ser aplicadas separadamente, em qualquer ordem.
- **US3 depende de US1**, porque só há o que reverter depois de aplicar.

### Within Each User Story

Sequencial. Cada verificação depende do artefato produzido pela anterior.

### Parallel Opportunities

- **T017, T018, T019** — documentação, independentes entre si.
- **US2 (T012–T014)** pode rodar em paralelo com US1 se houver duas máquinas;
  numa só, não compensa: o treino ocupa a CPU inteira.

---

## Implementation Strategy

**MVP = US1 sozinha.** Ela entrega +0,20 de nota e é o que muda a odd na tela. Se
o tempo acabar depois da Fase 3, a entrega já vale.

**US2 é um bônus barato** — uma linha de configuração, sem retreino.

**US3 não é opcional**, mesmo sendo P3. Sem rollback verificado, a entrega é uma
aposta, e o dono fica dependente de mim para desfazer.

## Fora de escopo, registrado

- **Camada de jogadores por desempenho** (+0,0046 medido) — frente própria, por
  decisão do dono.
- **Levar a margem ao `update_incremental`** — é modelagem de verdade, merece
  especificação própria (decisão D2 da pesquisa).
- **Treino completo programado** — frente nova, nasceu da pesquisa (decisão D4).
