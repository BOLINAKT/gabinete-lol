# O ganho da camada de jogadores, contra a base REAL da produção

**Medido em**: 11/09/2026 | 8 dobras de 30 dias, cadência diária, Platt
aplicado, hybrid + forma ligados, **n = 8.494** jogos de 2026 fora da amostra.
Todos os ganhos são de teste pareado jogo a jogo, com IC 95% diádico.

---

## Por que esta medição precisou ser refeita do zero

As medições anteriores comparavam contra uma base que **já aplicava um
empurrão da camada de jogadores**. A produção **não aplica** — o sinal está
bloqueado antes de chegar na probabilidade.

Ou seja, elas respondiam *"quanto a camada nova acrescenta a uma base que
ninguém serve"*. A pergunta certa é *"quanto ela acrescenta ao que está na
tela hoje"*.

Corrigido com a opção `--sem-camada-jogadores`, que zera esse empurrão.

## A tabela que decide

| o que é | nota | ganho sobre a produção de hoje | IC 95% diádico |
|---|---|---|---|
| **produção hoje** (jogadores bloqueados) | **7,09** | — | — |
| + camada **antiga** (Elo pelo resultado) | 7,13 | +0,00233 | [+0,00158, +0,00308] |
| + camada **nova** (desempenho, escalação anterior) | **7,20** | **+0,00402** | [+0,00282, +0,00521] |
| + camada nova, **com escalação corrigida** | 7,27 | +0,00577 | — |

E as duas comparações diretas:

| comparação | efeito | IC 95% diádico |
|---|---|---|
| trocar a camada antiga pela nova | +0,00169 | [+0,00049, +0,00289] |
| **acertar a escalação** (corrigir à mão) | **+0,00175** | [+0,00119, +0,00231] |

## O que isso decide

**Sobe a camada NOVA, não a antiga.** +0,00402 é o dobro da barra da casa
(0,002), com o limite inferior do intervalo em +0,00282. A antiga entrega
+0,00233, que passa raspando, e é batida pela nova por +0,00169.

A diferença entre as duas não é de ajuste fino, é de ideia: a antiga dá e tira
nota de jogador **pelo resultado da partida** — ganhou o time, subiu todo
mundo. A nova avalia **como o jogador jogou**, por rota, e só depois monta a
nota.

**Devolver os seletores de escalação vale +0,00175 quando usados.** Sozinho
fica logo abaixo da barra, mas não é para ficar sozinho: soma ao +0,00402 e
leva a nota de 7,09 para 7,27.

## O que ainda NÃO está feito

1. A nota por rota vive na régua (`tools/`), não em produção. Para subir, tem
   de existir no núcleo, e a régua passar a importá-la — senão mede uma coisa
   e serve outra.
2. O peso que multiplica o sinal tem de ser ajustado no treino, só com dados
   anteriores a cada janela.
3. Caminho de volta conferido, como o da margem.
4. Os seletores de escalação na tela: bloco fechado, salvando por confronto.
