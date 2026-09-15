# -*- coding: utf-8 -*-
"""Coleta as odds de LoL da Pinnacle e guarda o MOVIMENTO delas.

POR QUE A PINNACLE, E NAO QUALQUER CASA
Ela trabalha com margem baixa e limite alto, e aceita dinheiro afiado em vez
de barrar a conta — por isso o preco dela e o mais proximo de probabilidade
verdadeira que o mercado oferece. Com esses precos guardados COM HORA, da para
medir se o modelo bate o fechamento (CLV), que e a unica medicao que responde
se existe lucro. Nenhuma regua deste projeto responde isso hoje: todas
comparam o modelo com ele mesmo.

DE ONDE VEM, SEM DISFARCE
`guest.api.arcadia.pinnacle.com` — a API interna que o site DELES usa, aberta
e sem credencial. NAO e a API oficial: essa fechou para o publico e, para
esports, o FAQ deles diz que precisa de autorizacao especial (b2b@pinnacle.com).
E a porta dos fundos, e ele decidiu usa-la sabendo disso (15/09/2026).

O risco concreto NAO e a conta de aposta dele — nada aqui usa login. E bloqueio
de IP, que tiraria o acesso ao site onde ele aposta. Por isso:
  - DUAS requisicoes por corrida, de 3 em 3 horas. Trafego irrisorio.
  - User-Agent honesto, que diz o que e e para que serve.
  - 403/429 = para na hora e sai com rc=75. Nao insiste, nao tenta contornar,
    nao troca de identidade. Se eles nao quiserem, a resposta e parar.

POR QUE SO O QUE MUDA
Guardar o retrato inteiro a cada corrida daria ~9 MB por mes no repositorio.
E o que a medicao de CLV precisa nao e o retrato: e o MOVIMENTO. Entao cada
linha so entra no historico quando o preco dela mudou desde a ultima leitura.
Encolhe enormemente e nao perde nada do que importa.

MEDIDO EM 15/09/2026, chamando de verdade:
  - 9 series de LoL por vir (LPL, LEC, LCS, CBLOL, Rift Legends, WSCI)
  - mercados: moneyline, handicap de mapas, total de mapas, total por time
  - a margem denuncia onde ela esta confiante: LPL 4,8% · LCS 5,3% · WSCI 9,4%
  - o LIMITE tambem: R$ 2.000 no LPL contra R$ 100 no WSCI. E a propria casa
    dizendo em qual preco acredita — informacao que ninguem mais da de graca.
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

RAIZ = Path(__file__).resolve().parents[1]
AGORA_JSON = RAIZ / "odds_pinnacle.json"          # o retrato de agora
HISTORICO = RAIZ / "odds_pinnacle_historico.jsonl"  # so o que mudou

BASE = "https://guest.api.arcadia.pinnacle.com/0.1/"
ESPORTE_ESPORTS = 12
AGENTE = ("gabinete-lol/1.0 (leitura de odds para analise pessoal, "
          "8 requisicoes por dia; sem login)")
FUSO = "America/Sao_Paulo"

RC_OK = 0
RC_ERRO = 1
RC_TEMPORARIO = 75


def _agora_local() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(FUSO))
    except Exception:
        return datetime.now(timezone.utc)


def para_decimal(preco: Any) -> Optional[float]:
    """Odd americana -> decimal. None quando nao da para converter.

    PRINCIPIO IV: preco ilegivel nao vira 1,0 nem 2,0 — vira ausencia.
    """
    try:
        p = float(preco)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return None
    return 1.0 + (p / 100.0 if p > 0 else 100.0 / abs(p))


def margem(odds: List[float]) -> Optional[float]:
    """Quanto a casa cobra, em %. Precisa de TODAS as pernas do mercado.

    EXIGE PELO MENOS DUAS PERNAS, e isso nao e detalhe: com uma so, a conta
    devolve um numero negativo perfeitamente plausivel (uma odd de 2,90
    sozinha da -65,5%) que nao quer dizer nada. Defeito meu, pego pelo teste
    em 15/09/2026 — o coletor so chamava com duas pernas, entao ele nunca
    apareceu na pratica, mas a funcao estava errada para quem a usasse depois.
    """
    if not odds or len(odds) < 2:
        return None
    if any(o is None or o <= 1.0 for o in odds):
        return None
    return (sum(1.0 / o for o in odds) - 1.0) * 100.0


def _exigir_lista(payload: Any, nome: str) -> List[Any]:
    """A resposta tem de ser lista. Se a API mudou, ESTOURA.

    Devolver [] calado seria o pior desfecho: a tela diria "sem odds hoje"
    com toda a confianca do mundo, num dia cheio de jogo.
    """
    if not isinstance(payload, list):
        raise ValueError("{} nao veio como lista (a API mudou?)".format(nome))
    return payload


def normalizar(matchups: Any, mercados: Any, *, so_lol: bool = True) -> Dict[str, Any]:
    """As duas respostas -> uma lista plana de linhas de aposta."""
    matchups = _exigir_lista(matchups, "matchups")
    mercados = _exigir_lista(mercados, "markets")

    por_jogo: Dict[int, List[dict]] = {}
    for mk in mercados:
        if isinstance(mk, dict):
            por_jogo.setdefault(int(mk.get("matchupId", -1)), []).append(mk)

    linhas: List[Dict[str, Any]] = []
    jogos: List[Dict[str, Any]] = []
    descartes = {"ao_vivo": 0, "filho": 0, "sem_mercado": 0, "outro_jogo": 0}

    for m in matchups:
        if not isinstance(m, dict):
            continue
        liga = str((m.get("league") or {}).get("name") or "")
        if so_lol and "LEAGUE OF LEGENDS" not in liga.upper():
            descartes["outro_jogo"] += 1
            continue
        if m.get("parentId") is not None:
            # Confronto FILHO: placar exato, mapa avulso etc. O pai ja traz
            # tudo o que interessa, com nome de time legivel.
            descartes["filho"] += 1
            continue
        if m.get("isLive"):
            descartes["ao_vivo"] += 1   # escopo do projeto e PRE-JOGO
            continue

        lados = {str(p.get("alignment")): str(p.get("name") or "")
                 for p in (m.get("participants") or []) if isinstance(p, dict)}
        if not (lados.get("home") and lados.get("away")):
            continue

        mks = por_jogo.get(int(m.get("id", -1)), [])
        if not mks:
            descartes["sem_mercado"] += 1
            continue

        jogos.append({
            "id": int(m.get("id", -1)),
            "liga": liga.replace("League of Legends - ", ""),
            "casa": lados["home"], "fora": lados["away"],
            "bo": m.get("bestOfX"),
            "inicio_utc": str(m.get("startTime") or ""),
        })

        for mk in mks:
            precos = mk.get("prices") if isinstance(mk.get("prices"), list) else []
            decs = [para_decimal(x.get("price")) for x in precos if isinstance(x, dict)]
            marg = margem([d for d in decs if d is not None]) if len(decs) == 2 else None
            lim = (mk.get("limits") or [{}])
            limite = lim[0].get("amount") if isinstance(lim[0], dict) else None
            for x in precos:
                if not isinstance(x, dict):
                    continue
                d = para_decimal(x.get("price"))
                if d is None:
                    continue
                linhas.append({
                    "jogo": int(m.get("id", -1)),
                    "tipo": str(mk.get("type") or ""),
                    "periodo": int(mk.get("periodo", mk.get("period", -1)) or 0),
                    "alternativa": bool(mk.get("isAlternate", False)),
                    "lado": str(x.get("designation") or ""),
                    "pontos": x.get("points"),
                    "odd": round(float(d), 4),
                    "americana": x.get("price"),
                    "limite": limite,
                    "margem_pct": (round(marg, 2) if marg is not None else None),
                    "fecha_em": str(mk.get("cutoffAt") or ""),
                })

    return {"jogos": jogos, "linhas": linhas, "descartes": descartes}


def chave_da_linha(l: Dict[str, Any]) -> str:
    """Identidade de uma aposta, para saber se o preco dela mudou."""
    return "{}|{}|{}|{}|{}".format(
        l.get("jogo"), l.get("tipo"), l.get("periodo"), l.get("lado"),
        "" if l.get("pontos") is None else l.get("pontos"))


def _ultimas_odds(caminho: Path) -> Dict[str, float]:
    """Ultimo preco visto de cada aposta, lido do historico."""
    vistos: Dict[str, float] = {}
    try:
        with open(str(caminho), "r", encoding="utf-8") as fh:
            for linha in fh:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    r = json.loads(linha)
                except ValueError:
                    continue   # linha truncada nao derruba o resto
                if isinstance(r, dict) and r.get("chave"):
                    vistos[str(r["chave"])] = r.get("odd")
    except OSError:
        pass
    return vistos


def _gravar_atomico(caminho: Path, conteudo: Dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(caminho.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(conteudo, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, str(caminho))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description="Coleta odds de LoL da Pinnacle.")
    ap.add_argument("--agora", default=str(AGORA_JSON))
    ap.add_argument("--historico", default=str(HISTORICO))
    args = ap.parse_args()

    import requests

    cab = {"User-Agent": AGENTE}
    try:
        r1 = requests.get("{}sports/{}/matchups".format(BASE, ESPORTE_ESPORTS),
                          headers=cab, timeout=30)
        if r1.status_code in (403, 429):
            print("[odds] a casa respondeu {} — parando na hora.".format(r1.status_code))
            print("[odds] nao insisto e nao tento contornar. Tenta na proxima janela.")
            return RC_TEMPORARIO
        r2 = requests.get("{}sports/{}/markets/straight".format(BASE, ESPORTE_ESPORTS),
                          headers=cab, timeout=30)
        if r2.status_code in (403, 429):
            print("[odds] a casa respondeu {} nos mercados — parando.".format(r2.status_code))
            return RC_TEMPORARIO
    except requests.RequestException as e:
        print("[odds] rede fora do ar: {}".format(e))
        return RC_TEMPORARIO

    if r1.status_code != 200 or r2.status_code != 200:
        print("[odds] ERRO: HTTP {} e {}.".format(r1.status_code, r2.status_code))
        return RC_ERRO

    try:
        dados = normalizar(r1.json(), r2.json())
    except ValueError as e:
        print("[odds] ERRO DE FORMATO: {}".format(e))
        print("[odds] Nada foi escrito. O retrato anterior continua valendo.")
        return RC_ERRO

    lido_em = _agora_local().isoformat(timespec="seconds")
    alvo_agora = Path(str(args.agora)).expanduser()
    alvo_hist = Path(str(args.historico)).expanduser()

    _gravar_atomico(alvo_agora, {
        "lido_em": lido_em, "fonte": BASE, "fuso": FUSO,
        "jogos": dados["jogos"], "linhas": dados["linhas"],
        "descartes": dados["descartes"],
    })

    # HISTORICO: so o que MUDOU desde a ultima leitura.
    anteriores = _ultimas_odds(alhist := alvo_hist)
    novas = 0
    with open(str(alhist), "a", encoding="utf-8") as fh:
        for l in dados["linhas"]:
            k = chave_da_linha(l)
            if anteriores.get(k) == l["odd"]:
                continue
            fh.write(json.dumps({"lido_em": lido_em, "chave": k, **l},
                                ensure_ascii=False) + "\n")
            novas += 1

    print("[odds] {} serie(s) de LoL, {} linha(s) de aposta lidas.".format(
        len(dados["jogos"]), len(dados["linhas"])))
    print("[odds] {} preco(s) mudaram e entraram no historico.".format(novas))
    for j in dados["jogos"][:8]:
        print("    {:<14} {:<20} x {:<20} BO{}".format(
            j["liga"][:14], j["casa"][:20], j["fora"][:20], j["bo"]))
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
