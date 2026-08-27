# Gabinete LoL — leia isto antes de qualquer coisa

Este arquivo é carregado sozinho em toda sessão nova nesta pasta. Ele existe
para que o assistente não precise ser reapresentado ao projeto.

## O que é

Modelo de apostas em LoL profissional (previsão de vencedor de mapa, totais e ao
vivo), servido por um app Streamlit. O dono é apostador profissional, não
engenheiro: **explique em português claro, sem jargão, e nunca peça que ele
confira código para validar um número.**

Repositório irmão, do Dota: `BOLINCRVG/gabinete-dota`. Regra que faz isso sair
barato: **arquivo compartilhado fica idêntico nos dois repositórios.**

## Os dois arquivos que dizem o que fazer

1. **`MODELO_LOL.md`** — as 43 peças do modelo, cada uma com nota de evidência
   e o efeito medido. **É a fila de trabalho**, e a ordem das frentes está no
   fim dele. Comece por aqui.
2. **`RETOMAR.md`** — como reconstruir o ambiente, o estado de cada frente e as
   dívidas abertas. Leia se a máquina for nova ou se algo não subir.

## AS REGRAS DE TRABALHO — não negociáveis

Ele já teve que repetir estas várias vezes. Não são preferências.

1. **Uma frente por vez**, terminada por completo antes de abrir a próxima.
   Só avançar quando ele mandar.
2. **Pesquisar ANTES de propor.** Não sugerir a ideia primeiro: ir à internet,
   ver se aquilo já existe, como se faz, e se já se sabe que é bom (copiar) ou
   ruim (nem começar). Só então formar a ideia, misturando com o que a pesquisa
   trouxe. Pesquisar de novo depois de implementado.
3. **Dúvida → pesquisar. "Eu acho que assim é melhor" → pesquisar.** Vale
   inclusive para consertar bug: aquele jeito é mesmo o mais eficiente?
4. **A fonte fica ESCRITA no arquivo**, em bloco FONTES. Pesquisa que não ficou
   escrita conta como pesquisa que não aconteceu, porque ninguém pode conferir.
5. **Tudo testado. Só passa o que for medidamente melhor, sem exceção.** Teste
   cego separado do de calibração, intervalo de confiança, e a barra da casa:
   **ganho > 0,002 de logloss, p < 0,05, e limite inferior do intervalo acima de
   zero — as três juntas.** Nunca medir no conjunto usado para calibrar.
6. **Nota nunca sai da cabeça.** Toda nota é um programa reproduzível, com
   carimbo de quando foi medida. Em mercado binário, mostrar o ganho **sobre a
   taxa-base** (`p*(1-p)`), porque o Brier premia linha torta.
7. Não tem problema o modelo ficar quebrado por um tempo. Tem problema ele ficar
   bom por sorte.

## Fora do plano: CLV

Ele decidiu que não tem tempo. Consequência que ele aceitou: dá para provar que
o modelo **acerta**, nunca que **ganha dinheiro**. Neste projeto, "melhorou" só
pode significar **"prevê melhor"** — nunca "é lucrativo". Não reabrir sozinho.

## Armadilhas que já morderam (não repetir)

- **Raiz do repositório**: nunca `Path(__file__).parents[N]` em ferramenta que
  vive em pastas diferentes nos dois repos — usa `git rev-parse --show-toplevel`.
  Esse bug fez a régua do Dota medir a Área de Trabalho por semanas.
- **Afirmação sobre um repo dentro de código compartilhado** vira crédito
  emprestado para o outro repo. Declaração é dado local, e nomeia o seu dono.
- **Casar string em YAML não prova que o passo roda.** A esteira roda 3 módulos,
  não a suíte inteira — e a régua dava ponto por automação inexistente.
- **Base fraca dá ACCEPT falso.** Medir contra o modelo de produção, não contra
  um baseline conveniente.
- **`git add` seletivo no workflow** faz a medição morrer no runner.
- Antes de rodar medição pesada, conferir se a saída não sobrescreve produção.

## Comandos

```
.venv\Scripts\python -m unittest discover -s mlcore\tests -p "test_*.py"
.venv\Scripts\python tools\regua_28.py        # confiabilidade do sistema
.venv\Scripts\python tools\frescor.py         # as notas são de quando?
.venv\Scripts\python tools\ml_fusion_scorecard.py   # a nota oficial
```

A suíte leva ~11 min e roda 4.697 testes. Há **1 falha conhecida** em
`test_e2e_smoke` que só aparece na suíte inteira — está descrita em `RETOMAR.md`,
dívida D1. Qualquer outra falha é nova.
