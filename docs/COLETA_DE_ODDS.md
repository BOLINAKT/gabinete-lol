# Coleta de odds — o que vale, o que custa, e por onde começar

Registrado em 15/09/2026, a partir do que ele pediu e corrigiu na conversa.
A parte da Pinnacle **está construída e rodando** — o que ela coleta hoje está
no fim deste documento. O resto continua sendo plano.

## A correção que mudou a prioridade

Meu primeiro enquadramento estava estreito: eu tratei odds como "talvez vire
uma camada do modelo, se melhorar a nota". Ele corrigiu:

> "não é preto no branco assim, até porque por exemplo, se a pinnacle der uma
> nota mt diferente das outras seria legal saber."

Ele está certo, e por dois motivos que valem independente do modelo.

### 1. A régua externa que hoje não existe

Toda medição deste projeto compara o modelo **com ele mesmo** — versão nova
contra versão velha, na régua honesta. Nenhuma responde a única pergunta que
decide se existe lucro: **o modelo bate o mercado?**

A Pinnacle é a referência usada para isso porque trabalha com margem baixa e
limite alto e aceita dinheiro afiado em vez de barrar a conta — o preço dela é
o mais próximo de probabilidade verdadeira que o mercado oferece. Comparar a
previsão pré-jogo com o **fechamento** dela (CLV, closing line value) é o
padrão da área para dizer se uma aposta tinha valor, independente de ter
ganho ou perdido.

Isso é uma régua NOVA, não uma camada. Vale mesmo que nunca entre no modelo.

### 2. A discordância entre casas é o próprio sinal

Pinnacle marcando 1,76 e outra casa 1,95 no mesmo confronto não é ruído: é
onde o valor mora. E nas casas de muitas linhas a discordância aparece em
mercado que a Pinnacle nem abre.

## Os alvos, como ele descreveu

| casa | para quê | observação |
|---|---|---|
| **Pinnacle** | ML, principalmente | a referência; é dela que sai a régua externa |
| **bet365** | muitas linhas | kills, tempo, handicap, barão, inibidor |
| **Estrela** (e clones) | muitas linhas | ele citou clones como caminho alternativo |
| **BB** | secundárias | "lá tem algumas secundárias" |
| **Betano**, **Betesporte** | muitas linhas | mercado brasileiro |

Mercados que interessam além do ML: **kills, tempo, handicap, barão,
inibidores** — que é exatamente o conjunto que o app já analisa.

## O que torna isto a parte DIFÍCIL

O obstáculo não é técnico, é de acesso:

- casas grandes bloqueiam robô de propósito (proteção anti-bot);
- raspar contra os termos de uso é risco que cai na conta DELE, não na minha —
  e conta limitada ou encerrada custa mais que qualquer ganho de modelo;
- o markup muda sem aviso, então raspagem de tela quebra sozinha.

Caminhos honestos, em ordem de preferência:

1. **Casa que publica API de verdade.** A Pinnacle tem API documentada — é o
   caminho limpo para justamente a casa mais importante.
2. **Agregador pago** que já licenciou o dado das outras casas.
3. **Raspagem**, só como último recurso, e com ele sabendo do risco.

## Desenho, quando for a hora

Vale a mesma arquitetura da agenda, que já está de pé e funcionando:

- **quem coleta é o robô**, nunca o site — cada visita dele viraria uma ida ao
  alvo, e a hospedagem já provou que não é confiável para isso (13/09/2026);
- **grava arquivo versionado no repositório**, e o app só lê;
- **falha alto em mudança de formato**, quieto em problema passageiro;
- **guarda o histórico**, que é o que permite medir CLV depois — odd sem
  carimbo de quando foi vista não serve para medir nada.

Para a régua externa, o que precisa ser guardado por confronto é: **casa,
mercado, linha, odd e o instante da leitura**. Sem o instante não dá para
saber o que era abertura e o que era fechamento.

## A primeira pergunta, quando começarmos

**Em qual casa ele aposta de fato?** Não adianta coletar odd de casa onde ele
não tem conta: o preço seria bonito e inútil.

---

# O que já existe (15/09/2026)

`tools/coletar_odds.py`, rodando de 3 em 3 horas pelo robô do GitHub. Lê a API
interna de convidado da Pinnacle, sem login, e grava dois arquivos: o retrato
de agora (`odds_pinnacle.json`) e só o que **mudou de preço**
(`odds_pinnacle_historico.jsonl`), que é o que permite medir CLV depois.

## O erro que custou a tarde, e como ele aparecia

Ele me corrigiu: *"tanto kills, quanto torre, e tempo também na pinnacle"*. Eu
tinha dito que ela só tinha mercado de mapas. Fui atrás dos "derivados por
confronto", escrevi a busca, rodei — e voltaram **274 linhas, nenhuma de
kills**. Parecia que os mercados não existiam.

Existiam. Vinham **na mesma resposta que eu já pedia**, de graça. Dois filtros
meus os matavam, os dois em silêncio:

1. **"Filho não interessa."** Kills não é um campo do jogo: é um confronto
   filho separado, com `units: "Kills"` e os times renomeados
   `Fuego (Kills)` × `9z (Kills)`. O filtro que descartava qualquer coisa com
   `parentId` matava kills junto com o placar exato.
2. **"Sem casa e fora, não serve."** Num mercado assim os lados não são
   casa/fora — são `Over 33.5` e `Under 33.5`. A checagem derrubava a linha
   num desvio **mudo**, sem sequer somar um contador. Por isso rodar não
   acusava nada: o número aparecia bonito e completo.

Um terceiro defeito estava junto: a busca por confronto devolve **o próprio
jogo** na lista de derivados, e eu o adicionava de novo. Nove séries viraram
"11 séries" no relatório, com as linhas contadas em dobro. Número inflado é
pior que número faltando — parece certo.

## O que ele passa a receber sem digitar nada

Medido na corrida real de 15/09/2026, 9 séries de LoL, **298 linhas**:

| mercado | linhas |
|---|---|
| Handicap de mapas (série) | 58 |
| Placar exato | 54 |
| Total de mapas (série) | 36 |
| Vencedor (série e cada mapa) | 72 |
| **Total de kills, mapa a mapa** | 30 |
| **Handicap de kills, mapa a mapa** | 30 |
| **Total de kills por time** | 12 |
| **Quem faz mais kills no mapa** | 6 |

Exemplo do que chega pronto, sem ele procurar: `Fuego x 9z`, total de kills do
mapa 1 oferecido em **31,5 · 32,5 · 33,5 · 34,5 · 35,5**, cada um com as duas
odds e o limite da casa.

Custo disso tudo: **zero requisição a mais**. Era descarte, não ausência.

## Torre e tempo

Ainda não apareceram. Kills abriu enquanto eu trabalhava (não existia vinte
minutos antes), o que mostra que ela abre esses mercados aos poucos, perto do
jogo. Torre e tempo devem chegar no mesmo formato, cada um com a sua unidade —
e aí o coletor pega sozinho, sem precisar mexer em nada: o rótulo repete a
unidade que ela mandar, em vez de tentar adivinhar. Há teste guardando isso.

## Aviso para quem for medir CLV

O histórico tem três leituras do dia 15/09/2026 escritas **antes** da
correção, e elas não devem ser usadas:

- `15:55` (170 registros) — sem o campo `mercado`;
- `19:09` (102 registros) — com `mercado: "Regular"`, rótulo que não existe
  mais, e com as linhas dos dois jogos varridos contadas em dobro.

As duas são fáceis de separar: qualquer registro **sem `mercado`, ou com
`mercado` igual a `Regular`**, é anterior à correção. Não apaguei porque são
preços realmente observados; mas a identidade da aposta mudou de formato
(passou a incluir o nome do mercado, senão `Yes` de um mercado colidia com
`Yes` de outro), então cruzar os antigos com os novos daria par errado.

A partir de `20:21` o formato é o definitivo.

## O que ainda não existe

- **Tela** mostrando essas linhas ao lado da odd justa do modelo. Hoje o dado
  está no arquivo, não na frente dele.
- **A régua de CLV.** Precisa de histórico acumulado; começou agora.
- **Segunda casa** para comparar. Ele pediu Thunderpick ou alguma com linhas
  próximas de Betesporte/BB. Não foi tentado ainda.
