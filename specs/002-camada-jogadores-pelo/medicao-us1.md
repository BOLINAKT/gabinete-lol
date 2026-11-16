# US1 — quanto sobra depois da fusão

**Medido em**: 11/09/2026 | **Régua**: 8 dobras de 30 dias, cadência diária,
Platt aplicado, hybrid + forma ligados, **n = 8.494** jogos de 2026 fora da
amostra. Base de produção: margem de vitória ligada.

Todas as quatro variantes rodaram na **mesma** base de dados e nas **mesmas**
dobras. Todos os ganhos abaixo são de teste **pareado** jogo a jogo, com IC 95%
diádico, conforme RF-005.

---

## O 2×2

|  | sem fusão | com fusão |
|---|---|---|
| **base** | 7,13 | 7,10 |
| **+ camada de jogadores** | 7,28 | 7,28 |

## Os quatro efeitos

| comparação | efeito | IC 95% diádico |
|---|---|---|
| base → jogadores, **sem** fusão | **+0,00491** | [+0,00364, +0,00619] |
| base → jogadores, **com** fusão | **+0,00565** | [+0,00424, +0,00705] |
| efeito só da fusão, na base | **−0,00183** | [−0,00246, −0,00120] |
| efeito só da fusão, com jogadores | **−0,00110** | [−0,00168, −0,00051] |

---

## Achado 1 — minha hipótese estava errada

Eu escrevi, no `research.md` desta spec e no fechamento da Fase 2, que
**"+0,00346 é um teto, não a entrega"**, porque a fusão por precisão encolheria
o deslocamento.

**Não encolhe.** O ganho da camada é **maior** com a fusão (+0,00565) do que
sem ela (+0,00491).

O motivo é indireto e vale entender: a fusão **piora as duas pontas**, mas
piora a base (−0,00183) mais do que piora a variante com jogadores (−0,00110).
A diferença entre as duas pontas por isso aumenta. O ganho não cresceu porque a
camada ficou melhor — cresceu porque o ponto de comparação piorou mais.

Conclusão que importa: **a decisão de ligar a camada não depende da fusão.**
Ela passa na barra da casa nos dois caminhos, com folga, e o IC não chega perto
de zero em nenhum dos dois.

## Achado 2 — a fusão por precisão, medida honestamente, FAZ MAL

Este não era o alvo da medição e é o resultado mais forte dela.

Acrescentar o estágio de fusão do app custa **−0,00183** de logloss na base,
com intervalo inteiramente abaixo de zero. Não é ruído.

E isso **casa** com o estado atual do app: `use_lineup_adjust = False` fecha
justamente esse caminho. **O portão estar fechado está certo.**

Consequência de projeto, e é o oposto do que eu tinha escrito no `research.md`:
o precedente do calibrador com grupo — que foi salvo com uma "aplicação de
reserva" fora do ramo `use_lineup` — **não se aplica aqui**. Abrir o ramo para
alcançar a fusão traria junto um estágio que custa mais do que entrega.

**A camada nova deve entrar como deslocamento no logito, fora do ramo
`use_lineup`, sem passar pela fusão por precisão.**

## Achado 3 — infidelidade na BASE da régua, que já existia

`w_lineup` do `meta.players_layer` do artefato é lido só por ferramentas de
ajuste offline (`fit_ml_params.py`, `calibration_diagnostics.py`,
`layer_validation.py`). **O app servido não lê esse campo** — ele usa `pl_w`,
que vem de `params_fitted["w_lineup_used"] = 0,85`, e está atrás do portão
`use_lineup_adjust`, hoje fechado.

A régua, porém, aplica o deslocamento do `w_lineup` do artefato
incondicionalmente (valores por dobra entre 0,0047 e 0,089 — pequenos, mas não
zero).

Ou seja: **a base da régua aplica um deslocamento que o app não aplica.**

- **Não foi introduzido por mim** nesta spec; é anterior.
- **Não invalida as comparações acima**, porque as quatro variantes têm
  exatamente a mesma base e o teste é pareado.
- **Afeta as notas absolutas** (os 7,10 / 7,13 / 7,28), em grau não medido.

Fica como dívida desta spec, com dono: medir a base com o deslocamento
desligado e ver quanto as notas absolutas se movem.

---

## Decisão

**US1 passa.** A camada de jogadores por desempenho, com pesos aprendidos por
rota, entrega **+0,00491** como deslocamento no logito — mais que o dobro do
mínimo da casa (0,002), com o limite inferior do IC em +0,00364.

Segue para o desenho de como ligar, **pelo caminho do deslocamento**, não pelo
da fusão.

**US2 e US3 continuam justificadas**, porque existe sinal real para melhorar.

## O que NÃO foi feito, e é preciso, antes de ligar

1. Como o deslocamento entra em produção fora do ramo `use_lineup` sem mexer no
   que já está servido — e o teste de caracterização que prova que o resto da
   cadeia não mudou.
2. O caminho de volta, verificado como na spec 001.
3. `w_lineup_used = 0,85` foi ajustado na régua velha, dentro da amostra. Se a
   camada nova usar peso próprio, ele precisa ser ajustado na régua honesta, e
   só em dobras anteriores a cada janela.

## Defeito consertado no caminho

O resumo por dobra imprimia `pior nan | melhor nan`. A causa é legítima: a
janela de janeiro **não tem jogo entre regiões**, e a nota é uma mistura 45/55
de inter-região e mesma-região — sem um dos lados ela não existe. O `min()` e o
`max()` deixavam o `nan` escorrer e escondiam o resumo inteiro.

Agora as dobras sem nota própria são **contadas e ditas**, e o resumo sai das
que têm nota (Princípio IV: ausência não vira número). Os jogos dessas dobras
sempre contaram na nota geral, que soma tudo — isso não mudou.
