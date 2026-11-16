# Especificação: camada de jogadores pelo caminho servido

**Branch**: `002-camada-jogadores-pelo` | **Criada**: 11/09/2026 | **Status**: Rascunho

**Pedido do dono**: *"vai melhorar a metrica dos jogadores, pesquisando onde
você pode achar dados melhores, enfim, esse tipo de coisa, ou mesmo só
melhorando os dados que já tem"*

---

## O problema, em uma frase

A camada de jogadores rende **+0,00346** na régua e **não está ligada**, porque
a régua mediu por um caminho que o app não percorre inteiro.

## Por que isso não é birra de método

O app faz três coisas, nesta ordem
(`app_core/ml_pre_engine_core.py` ~565–595):

1. desloca o logito **cru**: `logit(p_raw) + w_lineup × delta`
2. **calibra** o resultado
3. **funde por precisão** com a probabilidade só-de-time

A régua fazia só uma versão do passo 1, sobre o logito **já calibrado**, e
pulava o passo 3 inteiro. O passo 3 **encolhe** o deslocamento na direção do
time. Então **+0,00346 é um teto, não a entrega** — e ninguém sabe ainda quanto
sobra depois do encolhimento.

Ligar a camada com base nesse número seria prometer um ganho medido num
caminho que o app não roda. É o que o Princípio V proíbe, e é o mesmo erro que
já custou uma rodada inteira quando o calibrador com grupo media +0,02 num
estágio que nunca era alcançado.

---

## Histórias

### US1 — Saber quanto sobra depois da fusão (P1)

Como dono, quero saber **o ganho real** da camada de jogadores pelo caminho que
o app percorre, para decidir se vale ligar.

**Por que é P1**: se sobrar pouco, as histórias 2 e 3 não têm motivo para
existir. Esta pode matar a frente inteira, e é barata.

**Teste independente**: rodar a régua com e sem `--fusao-servida`, comparar
pareado, e ler o intervalo de confiança.

**Cenários**:

1. **Dado** a régua com a fusão por precisão ligada, **quando** comparo a base
   com e sem a camada de jogadores, **então** obtenho o ganho pareado com IC
   diádico e p corrigido.
2. **Dado** que o ganho **não** passa na barra da casa (> 0,002, p < 0,05,
   limite inferior acima de zero), **então** a frente é encerrada e registrada
   como morta — sem tentar salvá-la ajustando parâmetro até passar.

### US2 — Nota de habilidade em vez de média acumulada (P2)

Como dono, quero que a nota de um jogador saiba **contra quem** ele jogou e
quanta **incerteza** ela tem, em vez de ser uma média simples do passado.

Hoje a nota é `soma acumulada ÷ (jogos + β)`. O PandaSkill trata cada partida
como um confronto dos **10 jogadores entre si**, ordenados pela nota de
desempenho, e atualiza a habilidade por esse ranking.

**Por que é P2**: é a maior diferença estrutural contra o desenho de
referência, mas só faz sentido depois que US1 disser que existe sinal.

**Teste independente**: trocar só o estágio 2, medir na régua com fusão.

### US3 — Correção de contexto por região (P3)

Como dono, quero que nota alta em liga fraca não valha o mesmo que nota alta em
liga forte.

Temos correção de liga **no nível de time**; **não temos no nível de jogador**.
O PandaSkill separa nota contextual (dentro da região) de nota da própria
região — e é justamente entre regiões que o método deles ganha mais
(70,07% contra 64,86%).

**Por que é P3**: maior esforço, e o time já corrige parte disso. Só depois de
US1 e US2.

---

## Requisitos

- **RF-001** A régua DEVE aplicar a fusão por precisão **importando**
  `fuse_with_coherence_guard` de `mlcore/fusion_core.py`. Nenhuma cópia da
  matemática da fusão pode existir em `tools/`.
- **RF-002** A régua DEVE aplicar o deslocamento ao logito **cru** e calibrar
  depois, na mesma ordem do app.
- **RF-003** As escalas de evidência DEVEM ser lidas de
  `params_fitted["best"]`, onde o app as lê — não cravadas no código.
- **RF-004** Cada variante DEVE gravar em arquivo próprio. Colisão de nome já
  invalidou uma comparação antes.
- **RF-005** Todo ganho publicado DEVE vir de uma corrida do
  `comparar_variantes.py`, com IC diádico, colada junto. Esta regra nasceu do
  erro de 11/09, quando o ganho da margem foi publicado como +0,00573 por
  leitura à mão e o valor pareado era +0,00463.
- **RF-006** Nada sobe sem passar na barra da casa: ganho > 0,002, p < 0,05
  **corrigido para comparações múltiplas**, e limite inferior do IC acima de
  zero — as três coisas.
- **RF-007** Se a camada for ligada, DEVE haver caminho de volta verificado,
  como no rollback da spec 001.
- **RF-008** A citação não-conferida no bloco FONTES de
  `NotaDeJogadorAprendida` (SAGE, HTTP 403 em 11/09) DEVE ser reaberta ou
  rebaixada a inferência minha.

## Critérios de sucesso

- **CS-001** O ganho da camada de jogadores **pelo caminho servido** está
  medido, com IC diádico, e escrito.
- **CS-002** A decisão de ligar ou não está tomada **por esse número**, não
  pelo +0,00346.
- **CS-003** Se ligada, a nota honesta de produção sobe, medida pareada.
- **CS-004** Se não ligada, o motivo está escrito de forma que ninguém precise
  refazer a medição para entender.

## Fora de escopo

- Draft (vive no lado ao vivo).
- Qualquer coisa que dependa de registro de ações dentro da partida — nossa
  fonte é estatística de fim de jogo.
- Trocar o motor de rating (medido, empate, p = 0,49).

## Premissas

- A régua honesta continua sendo a única régua que decide. A nota do
  `ml_fusion_scorecard` mede dentro da amostra e não entra em nenhuma decisão.
- Os artefatos de dobra já treinados com a marca `margem` são reaproveitáveis,
  então medir variantes novas custa minutos, não horas.
- `w_lineup_used = 0,85` fica como está enquanto US1 roda. Mexer nele no meio
  da medição criaria um segundo fator e estragaria a comparação.

## Riscos

| risco | o que fazer |
|---|---|
| a fusão engole o ganho quase todo | é o resultado mais provável; US1 existe para descobrir isso barato |
| ligar `use_lineup_adjust` mexe em mais coisa que a fusão | o portão abre **dois** pontos; o segundo (~linha 747) ainda não foi lido |
| `w_lineup_used = 0,85` foi ajustado na régua velha | pode estar errado; reajustar na régua honesta é candidato a tarefa |
| tentar muitas variantes até uma passar | maldição do vencedor; por isso RF-006 exige correção para comparações múltiplas |
