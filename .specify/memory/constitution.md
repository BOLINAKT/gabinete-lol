<!--
Sync Impact Report — amendment of 2026-09-11
  Version change: (none) → 1.0.0   [ratificação inicial]
  Modified principles: nenhuma (documento era só template)
  Added sections:
    - Core Principles I–V
    - A Régua (critério único de aceitação)
    - Fluxo de Trabalho
    - Governance
  Removed sections: nenhuma
  Follow-up TODOs: nenhum — todos os placeholders foram preenchidos.
  NOTA: este bloco é material de revisão humana, não é governança.
  Remover antes de commitar a versão final.
-->

# Gabinete LoL — Constituição

Modelo de probabilidade pré-jogo para apostas em League of Legends profissional.

Cada princípio abaixo nasceu de uma violação real, cometida e corrigida. Nenhum é
teórico. Onde houver número, ele foi medido.

## Core Principles

### I. Pesquisar antes de decidir (NÃO NEGOCIÁVEL)

Toda decisão de modelagem, estatística ou arquitetura DEVE ser precedida de
pesquisa, e a fonte DEVE ter sido **aberta e lida** — não um resumo de busca.

Quando só houver resumo, isso DEVE estar escrito ao lado da afirmação, com a
palavra "não conferido". Citar fonte que não se abriu é pior que não citar: cria
autoridade falsa.

*Por quê:* várias vezes nesta sessão uma fonte aberta contradisse o que o resumo
sugeria. E ao menos duas decisões minhas — colher a fiação viva do app, e
descartar o `hybrid_blend` por preconceito — teriam sido erradas sem a pesquisa.

### II. Medir fora da amostra, com corte temporal estrito (NÃO NEGOCIÁVEL)

Nenhum número de qualidade vale se o modelo já viu os jogos que está pontuando.
Toda medição DEVE usar origem rolante, cadência de produção, e histórico
**estritamente anterior** à data de cada partida.

Ablação de peça que vive **dentro** do treino exige retreino; peça de pós-treino
pode ser desligada no teste.

*Por quê:* a nota oficial do projeto pontuava 8.452 jogos dos quais 7.175 (84,9%)
estavam no treino. Ela dizia 8,91; medida direito, o mesmo modelo dá 7,12. Dois
pontos inteiros de ilusão.

### III. A barra decide, não a impressão (NÃO NEGOCIÁVEL)

Nada entra ou sai do modelo sem passar a barra completa, definida na seção
**A Régua**. Estimativa pontual favorável NÃO é aprovação.

Todo ganho declarado por seleção ("melhor de N configurações") DEVE ser tratado
como inflado até revalidação em dados independentes.

*Por quê:* o `best_form` declarava +0,005125 e não replicou. A margem declarava
+0,0117 e replicou em +0,0057. A diferença entre os dois só apareceu revalidando.

### IV. Ausência de dado nunca vira número

Nenhum dublê, fallback ou valor padrão DEVE devolver um número plausível quando o
dado não existe. O código DEVE falhar alto, ou contar e registrar a ausência.

*Por quê:* três dívidas do projeto vêm daí — estágio inerte com bandeira ligada,
cache que não vencia, e delta ausente virando zero. E uma armadilha deliberada
(`_proibido`) encontrou, na primeira execução, um colaborador que eu jurava não
ser chamado.

### V. Não reimplementar o caminho de produção para medi-lo

Medição DEVE chamar o código que produção chama. Quando isso for impossível, a
divergência DEVE ser declarada por escrito, com o que fica de fora.

*Por quê:* existem cinco implementações da probabilidade pré-jogo neste
repositório, cada uma parando num ponto diferente, e **nenhuma** igual à do app.
A régua desta sessão esqueceu o calibrador Platt e mediu, por horas, um modelo
que ninguém serve.

## A Régua

Critério **único** de aceitação. Trocar qualquer linha invalida as comparações já
feitas e exige emenda datada.

| item | valor |
|---|---|
| ferramenta | `tools/nota_honesta.py` |
| dobras | 7 janelas de 30 dias, origem rolante, janela expansiva |
| cadência | `--cadencia diaria` |
| calibrador | Platt da própria dobra, sempre aplicado |
| corte temporal | histórico estritamente anterior à partida |
| métrica de decisão | logloss agregado, todos os jogos com peso igual |
| erro-padrão | diádico (Cameron/Gelbach/Miller): `V = V_a + V_b − V_par` |
| semente | 20260908 |

**Aceitação exige as três:**

1. ganho de logloss **> 0,002**
2. limite inferior do IC 95% **> 0**
3. sobreviver a Benjamini-Hochberg (primária) e Holm-Bonferroni (estrita)

Peça que passa só na primeira entra como **indício**, não como aprovada.

## Fluxo de Trabalho

**Peneirar antes de construir.** Sinal candidato DEVE ser testado contra o
resíduo do melhor modelo atual (residualização, Frisch-Waugh-Lovell) antes de
qualquer implementação. Sinal que não explica o erro não rende, por melhor que
seja a construção.

**Fatorial, não um-de-cada-vez.** Peças interagem. Medido: `hybrid_blend` e
`season_form_blend` se canibalizam (interação −0,0043), e o `patch_meta_guard`
encolhe o ganho da margem. Um-de-cada-vez esconde isso.

**Pré-registrar antes de rodar.** Regra fixada depois de ver o resultado é a
maldição do vencedor com assinatura de quem a diagnosticou.

**Verificar o que já existe antes de construir.** Duas vezes nesta sessão eu
quase construí algo que o projeto já tinha.

**Corrigir em voz alta.** Erro encontrado DEVE ser dito ao dono e registrado no
próprio arquivo onde ocorreu, com data e sintoma — não apenas consertado.

**Explicar em português claro.** O dono é apostador profissional, não
engenheiro. Sem jargão, sem nome de função, sem erro de git.

## Governance

Esta constituição prevalece sobre preferência, pressa e intuição — inclusive as
minhas.

**Emendas:** qualquer mudança em princípio ou na Régua exige emenda escrita,
datada, com o motivo e o que fica invalidado. Emenda pode revogar emenda: a
EMENDA 1 do `PROTOCOLO_FASE2.md` foi revogada pela EMENDA 2 por ter torcido a
régua com base que o dono não endossava.

**Versionamento:** MAJOR para remoção ou redefinição incompatível de princípio;
MINOR para princípio ou seção nova; PATCH para clareza e redação.

**Conformidade:** antes de declarar qualquer resultado, verificar contra os cinco
princípios e contra a Régua. Resultado que viole um deles DEVE ser reportado como
não-conforme, mesmo que favorável — **principalmente** se for favorável.

**Version**: 1.0.0 | **Ratified**: 2026-09-11 | **Last Amended**: 2026-09-11
