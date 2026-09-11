# A camada de jogadores NÃO está entrando na conta hoje

**Conferido em**: 11/09/2026

Este arquivo existe porque o `MODELO_LOL.md` descreve a camada de jogadores
como **"LIGADA. A peça que mais paga"**, com nota 10. Isso **não é verdade no
caminho que o app serve**.

---

## A prova, em três frentes que concordam

### 1. O traço do app de verdade

`evidence/golden_cadeia_servida.json`, capturado dirigindo o app:

```
use_lineup   = False
pl_enabled   = True
pl_w         = 0.00424
lineup_mode  = "ML players layer"
```

E os estágios que a probabilidade servida realmente percorre:

```
interregional_strength_prior      -
season_form_blend            APLICOU
hybrid_blend                 APLICOU
confidence_guard                  -
patch_meta_guard                  -     <- o desligamento da spec 001, valendo
consistency_guard                 -
series_gamma                      -
```

**Não existe estágio de jogadores na lista.** Nenhum.

### 2. A leitura exaustiva do código

`delta_eff_used` é o número que carrega o sinal de jogadores. Em
`app_core/ml_pre_engine_core.py` ele é **consumido para mudar a probabilidade
em exatamente dois lugares**:

| linha | o que faz | dentro de qual guarda |
|---|---|---|
| 569 | `logit_base + pl_w * delta_eff_used` | `if ... and bool(use_lineup)` (linha 565) |
| 755 | `base_diff + lam * delta_eff_used` | `if bool(use_lineup) and ...` (linha 746) |

As outras ocorrências (550, 651, 736, 837) são legenda de tela ou reatribuição
para exibir. Fora desse arquivo, `delta_players_eff` só viaja em modelos de
saída, para mostrar e registrar.

**Com `use_lineup` falso, não há caminho pelo qual o sinal chegue ao número.**

### 3. Os dois interruptores, nos dois lugares onde moram

| onde | valor |
|---|---|
| `app_core/app_state.py` (default do código) | `use_lineup_adjust: False` |
| `.gabinete_settings.json` → `settings` (o salvo, que vence) | `False` |

---

## Por que a tabela do MODELO_LOL diz outra coisa

A nota 10 e o "paga 0,00644" vêm da ablação de **27/08/2026**. O próprio
`MODELO_LOL.md` já registra, na seção de 08/09, que aquela ablação **mediu uma
cadeia que o app não roda** (dívidas D8 e D9). A linha da tabela não foi
corrigida junto — só o texto acima dela.

É o mesmo padrão do calibrador com grupo: um estágio medido com ganho real,
que nunca era alcançado na tela.

---

## O que isto muda na spec 002

A pergunta deixa de ser *"como melhorar a métrica dos jogadores"* e passa a ser
**"a camada não está rodando; ligá-la é o ganho"**.

E já está medido o quanto, na régua honesta, por teste pareado (n = 8.494):

| caminho | ganho | IC 95% diádico |
|---|---|---|
| **deslocamento no logito** | **+0,00491** | [+0,00364, +0,00619] |
| deslocamento + fusão por precisão | +0,00565 | [+0,00424, +0,00705] |

Mas **a fusão por precisão, sozinha, custa −0,00183** — ver `medicao-us1.md`.
Por isso o caminho a ligar é o do **deslocamento**, e não o de abrir o portão
`use_lineup`, que traria a fusão junto.

## O que ainda NÃO se sabe, e não deve ser presumido

1. **Isto não quer dizer que o portão foi fechado por engano.** Abrir
   `use_lineup` liga deslocamento **e** fusão de uma vez. Medido assim, o
   pacote rende +0,00565 − mas não foi medido se o app, com todos os outros
   estágios, entrega isso. Falta a medição pelo app dirigido.
2. **A nota de jogador que rende +0,00491 é a APRENDIDA por rota**, que hoje
   vive em `tools/nota_honesta.py` — lado da régua. Para subir, ela precisa
   existir em `mlcore/` e a régua passar a importá-la, ou o Princípio V é
   violado ao contrário.
3. O artefato de jogadores guarda um escalar por jogador+rota
   (`{r, gp, last_date, last_league, last_tier}`). Se a nota nova couber nesse
   mesmo campo `r`, a mudança é **só do lado do treino** — o app não precisa
   mudar. **Isso é hipótese, ainda não verificada.**
