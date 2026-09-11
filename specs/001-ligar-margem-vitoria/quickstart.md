# O que mudou, como conferir e como voltar atrás

**Feature**: 001-ligar-margem-vitoria | **Aplicado em**: 11/09/2026

Escrito para você executar sozinho, sem depender de ninguém.

---

## O que mudou, em uma frase

O modelo passou a aprender **por quanto** um time ganhou, não só **se** ganhou.
E parou de encolher a confiança quando o patch muda, porque isso piorava.

## O número

```
7,12  antes
7,24  agora
```

Medido em 7.285 jogos de 2026 que o modelo nunca tinha visto, com a régua
honesta, comparando jogo a jogo. Ganho de logloss **+0,00463**, com margem de
erro de [+0,00273, +0,00654] e chance de ser sorte de cerca de 2 em 1 milhão.

> **Correção de 11/09/2026, feita no mesmo dia.** Este arquivo dizia **7,32** e
> **+0,00573**. Estava errado: o 7,32 é a nota da margem **mais a camada de
> jogadores**, e a camada de jogadores **não subiu** — ela ainda está sendo
> medida pelo caminho certo. O que está em produção rende 7,24.

**Atenção:** a nota antiga (`ml_fusion_scorecard.py`) vai mostrar **queda**, de
8,83 para 8,78. Isso é esperado e não é problema — aquela nota mede o modelo em
cima do próprio treino, e a margem faz ele decorar menos. Ignore aquele número.

---

## Como conferir que está valendo

**1. O artefato diz que foi treinado com margem:**

```
python -c "import json;m=json.load(open('ml_artifact.json',encoding='utf-8'))['meta'];print(m.get('whr_mov'))"
```

Tem que aparecer `sinal: gd15`, e as contagens de jogos com e sem margem
(esperado: ~8% sem, porque nem todo jogo tem o dado de ouro aos 15).

**2. O guard do patch parou de agir:**

```
python tools/caracterizacao_cadeia.py --capturar
```

No arquivo `evidence/golden_cadeia_servida.json`, o estágio `patch_meta_guard`
tem que aparecer com `applied: false`.

---

## Como voltar atrás

São duas mudanças independentes. Você pode reverter uma, outra, ou as duas.

### Para tirar a margem

1. Abra `tools/atualizar_modelo.py`
2. Ache a linha com `"--whr-mov", "gd15"`
3. Troque `"gd15"` por `"off"`
4. Rode `python tools/atualizar_modelo.py --holdout-days 30`

O modelo volta a ser **exatamente** o de antes. Isso não é promessa: há teste
travando que, com a margem desligada, o resultado é idêntico bit a bit.

### Para religar o guard do patch

1. Abra `app_core/app_state.py`
2. Ache `"ml_patch_guard_enabled": False`
3. Troque para `True`
4. Abra `.gabinete_settings.json` e faça o mesmo lá

**Por que em dois lugares:** o app tem o default do código e a sua configuração
salva. A salva vence. Foi justamente isso que fez a primeira tentativa de
desligar não funcionar.

### Rollback de emergência (desfaz tudo de uma vez)

O retreino guardou uma cópia do modelo anterior:

```
ml_artifact.json.pre_update_AAAAMMDD_HHMMSS
players_artifact.json.pre_update_AAAAMMDD_HHMMSS
```

Renomeie as duas tirando o sufixo `.pre_update_...` e o modelo de ontem volta,
sem retreinar nada.

---

## O que ficou pendente, e você precisa saber

**O ganho depende de retreinar por completo mais ou menos todo mês.**

Seu robô roda três vezes ao dia, mas ele só faz atualização **incremental**, que
usa o caminho antigo e **não conhece a margem**. Entre um treino completo e
outro, os jogos novos entram sem ela.

Treinos completos até aqui: 16/08, 15/07, 02/06 — nenhum programado, todos
disparados por algum evento.

Se passar dois ou três meses sem treino completo, o ganho decai. **Quanto decai
não foi medido.**

Para retreinar por completo:

```
python tools/atualizar_modelo.py --holdout-days 30
```

Leva uns 15 minutos e faz backup sozinho.
