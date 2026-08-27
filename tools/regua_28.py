# -*- coding: utf-8 -*-
"""RÉGUA DAS 28 — "estamos no melhor possível?" com número, não com sensação.

Adaptação do ML Test Score (Breck, Cai, Nielsen, Salib & Sculley — Google,
IEEE Big Data 2017): 28 testes fixos em quatro áreas, aplicados aos dois
Gabinetes.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║                                                                             ║
║ 1. A LISTA DOS 28 e as quatro áreas vêm do artigo, lido direto (as tabelas  ║
║    I a IV). Não adaptei de memória — faltavam-me as áreas de Dados e        ║
║    Modelo, e inventá-las seria o oposto do ponto da régua.                  ║
║                                                                             ║
║ 2. PONTUAÇÃO, do próprio artigo:                                            ║
║      meio ponto  — o teste é executado À MÃO e o resultado documentado      ║
║      um ponto    — existe sistema que o executa AUTOMÁTICO e repetido       ║
║    "Régua que só roda quando eu rodo vale metade de uma régua."             ║
║                                                                             ║
║ 3. A NOTA FINAL É O MÍNIMO das quatro áreas, não a média — também do        ║
║    artigo: "escolhemos o mínimo porque acreditamos que as quatro áreas são  ║
║    importantes, e um sistema precisa considerar todas para subir a nota".   ║
║    É o que impede a nossa força em desenvolvimento de modelo de esconder    ║
║    que monitoramento está perto de zero.                                    ║
║                                                                             ║
║ 4. A ESCALA DE LEITURA (Tabela V do artigo):                                ║
║      0        mais projeto de pesquisa que sistema em produção              ║
║      (0,1]    vale considerar buracos sérios de confiabilidade              ║
║      (1,2]    primeira passada de produtização; falta investimento          ║
║      (2,3]    razoavelmente testado, mas muito ainda podia ser automatizado ║
║      (3,5]    forte, adequado a sistema crítico                             ║
║      >5       excepcional                                                   ║
║                                                                             ║
║ 5. POR QUE PARTE É VERIFICADA E PARTE É DECLARADA:                          ║
║    o artigo é uma rubrica preenchida pela equipe. Onde dá para checar        ║
║    mecanicamente (existe passo na esteira? existe arquivo de evidência?),   ║
║    a régua checa — porque declaração envelhece e verificação não. Onde não  ║
║    dá, a declaração é obrigada a NOMEAR a evidência.                        ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso: python tools/regua_28.py [--root OUTRO_REPO]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

RAIZ_PADRAO = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# Verificadores mecanicos. Devolvem (nota, evidencia). Nota: 0, 0.5 ou 1.0.
# --------------------------------------------------------------------------


def _existe(raiz: Path, *padroes: str):
    achados = [p for pad in padroes for p in raiz.glob(pad) if p.exists()]
    return achados


def _na_esteira(raiz: Path, *trechos: str):
    """O passo roda numa esteira (automatico = 1 ponto) ou so a mao (0,5)?"""
    for yml in (raiz / ".github" / "workflows").glob("*.y*ml"):
        try:
            texto = yml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for t in trechos:
            if t in texto:
                return yml.name
    return None


def v_na_esteira(*trechos: str, descricao: str):
    """O passo roda numa esteira? Nomeia o ARQUIVO ONDE ACHOU.

    Existe porque a primeira versao reportava o primeiro resultado do glob em
    vez do arquivo onde o trecho estava, produzindo evidencia sem sentido
    ("nota_semanal.yml roda em retreino.yml"). Nota certa, texto mentiroso —
    e num arquivo cujo proposito e ser verificavel, texto mentiroso e pior."""
    def verificar(raiz: Path):
        yml = _na_esteira(raiz, *trechos)
        if yml:
            return 1.0, f"{descricao} ({yml})"
        return 0.0, f"{descricao}: nao encontrado em nenhuma esteira"
    return verificar


def v_ferramenta(*, arquivos: tuple[str, ...], esteira: tuple[str, ...] = ()):
    """Existe a ferramenta? Roda sozinha? -> 1,0. So a mao? -> 0,5. Nao existe? 0."""
    def verificar(raiz: Path):
        achados = _existe(raiz, *arquivos)
        if not achados:
            return 0.0, "ferramenta nao existe"
        yml = _na_esteira(raiz, *esteira) if esteira else None
        nome = achados[0].name
        if yml:
            return 1.0, f"{nome} roda em {yml}"
        return 0.5, f"{nome} existe, mas so roda a mao"
    return verificar


def v_evidencia(nome: str, cadencia_dias: float):
    """Existe evidencia recente? Usa o mesmo criterio do tools/frescor.py."""
    def verificar(raiz: Path):
        p = raiz / "evidence" / nome
        if not p.exists():
            return 0.0, f"evidence/{nome} nao existe"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            carimbo = d.get("gerado_em") or d.get("generated_at")
            quando = datetime.fromisoformat(str(carimbo).replace("Z", "+00:00").split("+")[0])
            idade = (datetime.now() - quando).days
        except (OSError, ValueError, TypeError):
            return 0.5, f"evidence/{nome} existe mas SEM carimbo de data"
        if idade > 3 * cadencia_dias:
            return 0.5, f"evidence/{nome} tem {idade}d (velha)"
        return 1.0, f"evidence/{nome} tem {idade}d"
    return verificar


# --------------------------------------------------------------------------
# Os 28. (area, numero, titulo, verificador OU (nota, justificativa))
# Declaracao e obrigada a NOMEAR a evidencia (fonte 5).
# --------------------------------------------------------------------------
ITENS = [
    # ---- DADOS ----
    ("dados", 1, "expectativas das features num esquema",
     (0.5, "VERIFICADO 27/08: tools/run_phase1_data_contract.py existe e o app le o relatorio (params_sections_core), mas nao roda em esteira")),
    ("dados", 2, "todas as features sao beneficas",
     (1.0, "toda camada passa por gate OOS antes de entrar; ha REJECTs registrados (draft, players no Dota, circuitos)")),
    ("dados", 3, "nenhuma feature custa demais", (0.0, "custo por feature nunca foi medido")),
    ("dados", 4, "features atendem requisitos de nivel superior",
     (0.5, "regras existem (so tier pro no Dota, ano/liga no LoL) mas nao sao verificadas por programa")),
    ("dados", 5, "controles de privacidade no pipeline",
     (1.0, "dado publico de partida; sem dado pessoal — requisito nao se aplica e isso esta declarado")),
    ("dados", 6, "feature nova entra rapido", (0.5, "entra, mas o caminho e manual e nao cronometrado")),
    ("dados", 7, "codigo de feature testado",
     v_ferramenta(arquivos=("mlcore/tests/test_*features*.py", "mlcore/tests/test_*data*.py"))),
    # ---- MODELO ----
    ("modelo", 1, "especificacao revisada e versionada",
     (1.0, "tudo em git com o porque no texto do commit; nenhuma mudanca de modelo sem gate")),
    ("modelo", 2, "metricas offline e online se correlacionam",
     (0.0, "NAO medido: exigiria CLV, que esta fora do plano por decisao dele")),
    ("modelo", 3, "hiperparametros ajustados",
     (1.0, "gates com validacao cruzada; L2 e agrupamento do calibrador escolhidos por VC repetida DENTRO da calibracao")),
    ("modelo", 4, "impacto do envelhecimento conhecido",
     (1.0, "medido em 27/08: calibrador ajustado em temporada velha custa +0.023 de logloss")),
    ("modelo", 5, "modelo simples nao e melhor",
     (1.0, "toda camada e medida contra a base; ha casos em que o simples ganhou e foi mantido")),
    ("modelo", 6, "qualidade suficiente em cada FATIA",
     v_ferramenta(arquivos=("tools/nota_por_liga.py", "dota_scorecard.py"),
                  esteira=("nota_por_liga.py", "dota_scorecard.py"))),
    ("modelo", 7, "testado quanto a inclusao",
     (1.0, "nao se aplica: nao ha pessoa como sujeito da previsao, e isso esta declarado")),
    # ---- INFRA ----
    ("infra", 1, "treino reproduzivel", (0.0, "VERIFICADO 27/08: NAO ha semente aleatoria no treino — os 'seed' em fit_ml_params sao checkpoints de estagio — nem teste que rode duas vezes e compare")),
    ("infra", 2, "especificacao com teste unitario", v_ferramenta(arquivos=("mlcore/tests/test_artifact.py",))),
    ("infra", 3, "pipeline com teste de integracao",
     v_na_esteira("python -m unittest", descricao="a suite roda na esteira de retreino")),
    ("infra", 4, "qualidade validada ANTES de servir",
     v_na_esteira("Guardas pos-retreino", "Guardas pós-retreino",
                  descricao="guarda que barra modelo quebrado antes de publicar")),
    ("infra", 5, "modelo depuravel",
     (1.0, "VERIFICADO 27/08: session_state[_ml_trace_last] guarda o caminho da previsao (first_x_gap_core, flow_runtime_core) e a aba de explicabilidade o exibe")),
    ("infra", 6, "canario antes de servir",
     (0.5, "o calibrador com grupo entrou desligado ate os coeficientes existirem, mas nao ha canario sistematico")),
    ("infra", 7, "da para reverter", v_ferramenta(arquivos=("tools/rollback_baseline.py",))),
    # ---- MONITORAMENTO ----
    ("monitor", 1, "mudanca de dependencia notifica", (0.0, "nao existe")),
    ("monitor", 2, "invariantes valem na entrada",
     (0.5, "VERIFICADO 27/08: retreino.yml tem 'Guardas pos-retreino' e retreino_ao_vivo tem GUARDA FALHOU; mas schema/volume/distribuicao nao sao vigiados")),
    ("monitor", 3, "treino e servico NAO divergem",
     (0.0, "divergencia ENCONTRADA duas vezes em 26/08 (scope_meta) e a nota oficial mede caminho diferente do servido; nao ha vigia")),
    ("monitor", 4, "modelo nao esta velho demais",
     v_ferramenta(arquivos=("tools/frescor.py",), esteira=("frescor.py",))),
    ("monitor", 5, "numericamente estavel", (0.0, "VERIFICADO 27/08: train_offline tem UM isfinite, numa conta especifica — nao ha vigia de NaN/infinito")),
    ("monitor", 6, "desempenho computacional nao regrediu", (0.0, "tempo de treino e de resposta nao sao medidos")),
    ("monitor", 7, "qualidade de previsao nao regrediu",
     v_ferramenta(arquivos=("tools/ml_fusion_scorecard.py",), esteira=("ml_fusion_scorecard.py",))),
]

AREAS = {"dados": "DADOS", "modelo": "MODELO", "infra": "INFRAESTRUTURA", "monitor": "MONITORAMENTO"}


def leitura(nota: float) -> str:
    if nota <= 0:
        return "mais projeto de pesquisa que sistema em producao"
    if nota <= 1:
        return "vale considerar buracos serios de confiabilidade"
    if nota <= 2:
        return "primeira passada de produtizacao; falta investimento"
    if nota <= 3:
        return "razoavelmente testado, mas muito ainda podia ser automatizado"
    if nota <= 5:
        return "forte, adequado a sistema critico"
    return "excepcional"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--out", default="evidence/regua_28.json")
    args = ap.parse_args()
    raiz = Path(args.root).resolve() if args.root else RAIZ_PADRAO

    print(f"[raiz] {raiz}")
    if raiz != RAIZ_PADRAO:
        # Os itens DECLARADOS foram escritos olhando o LoL. Os verificados
        # mecanicamente se adaptam ao repo; os declarados NAO. Herdar
        # declaracao e exatamente o tipo de afirmacao velha que faz regua
        # mentir — entao a regua avisa em vez de fingir que vale.
        print("AVISO: os itens DECLARADOS foram escritos olhando o repositorio")
        print("       do LoL. Aqui eles precisam ser revistos um a um antes de")
        print("       a nota valer. Os verificados mecanicamente ja se adaptam.")
    print()
    por_area: dict[str, float] = {k: 0.0 for k in AREAS}
    linhas = []
    for area, num, titulo, regra in ITENS:
        if callable(regra):
            nota, evid = regra(raiz)
        else:
            nota, evid = regra
        por_area[area] += nota
        linhas.append({"area": area, "n": num, "item": titulo,
                       "nota": nota, "evidencia": evid})

    for area, rotulo in AREAS.items():
        itens = [x for x in linhas if x["area"] == area]
        print(f"=== {rotulo}: {por_area[area]:.1f} / 7 ===")
        for x in itens:
            marca = {0.0: "  ", 0.5: "½ ", 1.0: "✓ "}[x["nota"]]
            print(f"  {marca}{x['n']}. {x['item'][:52]:<54}{x['evidencia'][:56]}")
        print()

    nota = min(por_area.values())
    pior = [a for a, v in por_area.items() if v == nota]
    print("=" * 78)
    print(f"NOTA (o MINIMO das quatro areas, fonte 3): {nota:.1f}")
    print(f"  area que segura: {', '.join(AREAS[a] for a in pior)}")
    print(f"  leitura: {leitura(nota)}")
    print(f"  media (que NAO e a nota, e serve so de contraste): "
          f"{sum(por_area.values()) / 4:.1f}")
    print("=" * 78)

    destino = raiz / str(args.out)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "nota": nota, "por_area": por_area, "itens": linhas,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[salvo] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
