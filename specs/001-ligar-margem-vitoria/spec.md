# Feature Specification: Ligar a margem de vitória no rating

**Feature Branch**: `001-ligar-margem-vitoria`

**Created**: 2026-09-11

**Status**: Draft

**Input**: Aplicar em produção o pacote já medido na régua honesta: ligar a margem
de vitória (ouro aos 15 minutos) no fit do WHR, e desligar o `patch_meta_guard`.
A camada de jogadores fica de fora desta entrega, para uma frente própria.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A odd na tela reflete um modelo melhor (Priority: P1)

O dono abre o app, escolhe um confronto e vê a probabilidade pré-jogo. Hoje esse
número vem de um rating que só sabe "ganhou ou perdeu". Depois desta entrega, ele
vem de um rating que também sabe **por quanto** — usando a diferença de ouro aos
15 minutos de cada jogo passado.

**Por que P1:** é a única mudança medida que altera o número que ele aposta.

**Teste de aceitação:** o mesmo confronto, calculado antes e depois, produz
números diferentes; e a nota honesta do modelo novo é maior que a do atual,
medida pela Régua da constituição.

### User Story 2 - O modelo para de encolher a confiança sem motivo (Priority: P2)

Hoje, quando o patch muda, o `patch_meta_guard` empurra a probabilidade em
direção a 50% — até 22%. Medido, ele **piora** a previsão em todos os níveis,
porque o calibrador Platt já corrige a confiança excessiva que ele tentava tratar.

**Por que P2:** melhora independente da margem, mas de efeito menor.

**Teste de aceitação:** com a bandeira desligada, o traço do pipeline mostra
`patch_meta_guard` com `applied=False`, e o número servido não é mais encolhido.

### User Story 3 - Rollback em um passo (Priority: P3)

Se algo der errado, o dono precisa voltar ao comportamento anterior sem depender
de ninguém.

**Teste de aceitação:** retreinar com `--whr-mov off` devolve, bit a bit, o
artefato que produção tem hoje.

### Edge Cases

- **Jogo sem ouro aos 15** (dado ausente em ~8% das partidas, mais comum em ligas
  menores): o jogo DEVE entrar no rating pelo ganhou/perdeu puro, e a ausência
  DEVE ser contada. Nunca virar zero silencioso — Princípio IV.
- **Artefato antigo, código novo:** o app DEVE continuar funcionando com um
  artefato treinado sem margem. A margem vive no treino, não na leitura.
- **Retreino do robô:** o robô roda `update_incremental`, que aplica updates de
  Elo sobre o artefato. Essa etapa NÃO conhece margem. O efeito é que os jogos
  incrementais entram sem margem até o próximo treino completo — **limitação
  conhecida e aceita nesta entrega**, registrada em Assumptions.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O treino DEVE aceitar a margem de vitória no fit do WHR, com o sinal
  ouro-aos-15, peso 0,35 e folga 0,15.
- **FR-002**: A margem DEVE entrar como resultado fracionário na verossimilhança
  (ỹ ∈ [0,1]), preservando gradiente e Hessiana — nunca como empurrão no rating.
- **FR-003**: Jogo sem o sinal DEVE cair no resultado binário e ser **contado**
  separadamente; a contagem DEVE ir para o artefato.
- **FR-004**: A receita usada (sinal, peso, folga, coeficientes da expectativa)
  DEVE ficar gravada no artefato, de modo que ele diga sozinho como foi treinado.
- **FR-005**: Com a margem desligada, o fit DEVE ser **bit a bit** o de hoje.
- **FR-006**: A bandeira do `patch_meta_guard` DEVE ser desligada por padrão.
- **FR-007**: Desligar o guard NÃO DEVE remover o código dele — só a bandeira,
  para o rollback ser uma linha.
- **FR-008**: A suíte de testes DEVE continuar inteira verde.

### Key Entities

- **Artefato do modelo** (`ml_artifact.json`): ganha o bloco `whr_mov` com a
  receita e a contagem de jogos com/sem margem.
- **Configuração de runtime**: a bandeira `ml_patch_guard_enabled` passa a
  `False` por padrão.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A nota honesta sobe de **7,12** para **≥ 7,30**, medida pela Régua
  da constituição (7 dobras, cadência diária, calibrador aplicado, corte temporal
  estrito).
- **SC-002**: O ganho de logloss contra produção é **> 0,002** com limite inferior
  do IC 95% diádico **> 0**. *(Medido: +0,00573, IC [+0,00396, +0,00751].)*
- **SC-003**: Nenhuma dobra individual piora mais que 0,20 de nota.
- **SC-004**: A suíte de testes passa inteira (4.795 testes na última execução).
- **SC-005**: Treinar com a margem desligada produz artefato idêntico ao atual.
- **SC-006**: O artefato novo carrega e prevê no app sem erro, e o número servido
  muda em relação ao anterior.

## Assumptions

- **A margem já está implementada e testada** (`mlcore/whr_core.py`,
  `mlcore/train_offline.py`, 18 testes). Esta entrega **liga** o que existe; não
  constrói mecanismo novo.
- **Os parâmetros (0,35 / 0,15) não serão reajustados aqui.** Foram escolhidos em
  2025 e revalidados em 2026 em dados independentes. Reajustar agora, vendo o
  resultado, seria a maldição do vencedor — Princípio III.
- **O `update_incremental` continua sem margem.** Entre treinos completos, os
  jogos novos entram pelo caminho Elo antigo. Isso limita o ganho real a algo
  menor que o medido, e o tamanho dessa perda **não foi medido**.
- **Desligar o `patch_meta_guard` passa a barra completa apenas no nível "refit"**
  (+0,00334). No nível "warn" o ganho é +0,00129 — abaixo dos 0,002, ainda que o
  intervalo exclua zero. Entra como melhora de efeito pequeno, não como aprovada
  pela barra cheia.
- **A camada de jogadores fica fora**, por decisão do dono, para frente própria.
