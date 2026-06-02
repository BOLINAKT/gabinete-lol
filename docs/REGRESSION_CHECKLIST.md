# Fase 0 - Checklist de Regressao Manual (10 cenarios)

Objetivo: validar que mudancas nao quebraram comportamento essencial antes de novas refatoracoes.

## Ambiente
- CSV ativo carregado no app
- artifact carregado (`ml_artifact.json`)
- abrir app em sessao limpa quando possivel

## Cenarios fixos
1. Fluxo base de confronto
- Selecionar Time 1/Time 2/BO.
- Confirmar exibicao de odd Mapa e Serie para ambos os lados.

2. Estabilidade de odd sem mudanca real
- Abrir `Editar linhas`, salvar sem alterar nada, reanalisar.
- Odd de ML nao deve oscilar sem motivo.

3. Aba Resumo (colunas essenciais)
- Confirmar presenca de: `Odd (Modelo)`, `StatsCamps%`, `Odd (Hist)`, `Odd (Mix)`, `Laplace (Liga)`, `Laplace (H2H)`.

4. Consistencia de Mercado - alternancia de abas
- Trocar entre Kills/Torres/Dragoes/Baroes/Inibidores/Tempo.
- Confirmar que bloco de modelo + historico atualiza sem tela em branco.

5. ML + Totais (somente Kills e Tempo)
- Confirmar calculo com linhas proprias do bloco ML+Totais.
- Verificar que nao depende das linhas gerais de outros mercados.

6. Players - autofill + analisar
- Clicar `Auto-preencher players dos times`.
- Confirmar nomes em lanes e geracao de tabelas apos `Analisar players`.

7. Players - linhas individuais (passou/nao passou)
- Inserir linhas em kills/deaths/assists para 2 lanes.
- Confirmar saida por jogador individual (`Lado` Acima/Abaixo + odds).

8. Filtros do painel Players
- Aplicar filtro de Time/Lane/Mercado/Player.
- Confirmar dataframe filtra corretamente sem erro.

9. Parametros e manutencao
- Abrir aba Parametros e verificar botoes de manutencao.
- Rodar walk-forward e confirmar feedback de conclusao sem exception.

10. Integridade de texto/encoding
- Navegar no app e validar ausencia de mojibake (ex.: `Configuracoes`, `Calibracoes`, `Ultimos`).

## Criterio de aprovacao
- 10/10 cenarios sem erro em runtime.
- Sem telas em branco nas abas principais.
- Sem regressao visual critica no fluxo principal (Visao Geral, Consistencia, Resumo, Players).
