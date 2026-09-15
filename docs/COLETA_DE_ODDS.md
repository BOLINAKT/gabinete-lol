# Coleta de odds — o que vale, o que custa, e por onde começar

Registrado em 15/09/2026, a partir do que ele pediu e corrigiu na conversa.
Nada aqui está construído ainda. Este documento existe para a decisão não se
perder e para ninguém recomeçar do zero.

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
