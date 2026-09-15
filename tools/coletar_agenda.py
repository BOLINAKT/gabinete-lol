# -*- coding: utf-8 -*-
"""Coleta a agenda de jogos de LoL e grava em agenda_coletada.json.

PARA QUE SERVE
Hoje o dono copia a lista de jogos de um site e cola no app. O parser dele
(app_core/schedule_import_core.parse_schedule_text) ja trata os cabecalhos, os
nomes repetidos e os apelidos de time. Este coletor produz EXATAMENTE a mesma
lista, so que sozinho — o passo manual some, o resto do caminho fica igual.

DE ONDE VEM
`https://esports-api.lolesports.com/persisted/gw/getSchedule` — a API que o
site oficial da Riot usa por tras, com a chave publica que ele mesmo publica
no javascript da propria pagina.

  MEDIDO EM 15/09/2026, chamando de verdade:
    - 80 eventos numa chamada (44 ainda por jogar)
    - nome de liga limpo (LCK, VCS, NACL) — o Leaguepedia devolve caminho de
      wiki ("LFL/2027 Season/Promotion"), que daria trabalho a toa
    - formato da serie por jogo: {"type": "bestOf", "count": 5}
    - dos 77 nomes de time distintos, o resolvedor do app acerta 74% sozinho,
      inclusive traduzindo ("BILIBILI GAMING" -> "Bilibili Gaming")

ELA NAO E DOCUMENTADA NEM PROMETIDA. Pode mudar sem aviso, e por isso este
programa foi escrito para FALHAR ALTO em vez de gravar lixo. As garantias sao
as mesmas que o tools/oe_download.py aprendeu a ferro neste projeto:

  - NUNCA substitui uma agenda boa por uma vazia. Se a coleta vier sem jogos e
    ja houver arquivo com jogos, sai com erro e nao escreve. Agenda vazia num
    dia de jogo e pior que agenda velha: a velha ao menos se denuncia.
  - Se o FORMATO da resposta mudar (a API foi mexida), sai com erro dizendo
    isso. Ler um campo que sumiu daria zero jogos, que pareceria "dia sem
    jogo" — o erro mais caro possivel aqui, porque e silencioso.
  - Escrita atomica (tmp + os.replace). Ja quebrou o app duas vezes ler
    arquivo pela metade.
  - Rede fora do ar e rc=75 (EX_TEMPFAIL), para o robo tratar como "tenta na
    proxima janela" e nao como defeito.

O FUSO E CONVERTIDO. A API responde em UTC; o dono ve horario de Brasilia. Um
jogo as 14:00Z e 11:00 para ele. Deixar em UTC criaria erro de horario de 3
horas numa tela usada para apostar.
"""
from __future__ import annotations

import sys

# Console cp1252 no Windows derruba qualquer print com acento — e o estouro vem
# no fim, depois do trabalho todo feito. Mesma protecao do oe_download.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

import argparse
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "agenda_coletada.json"

URL = "https://esports-api.lolesports.com/persisted/gw/getSchedule"
# Chave publica, a mesma que o site oficial usa no javascript da propria pagina.
CHAVE = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
AGENTE = "gabinete-lol/1.0 (agenda para uso pessoal; contato via repositorio)"

FUSO = "America/Sao_Paulo"

RC_OK = 0
RC_ERRO = 1
RC_TEMPORARIO = 75   # EX_TEMPFAIL: o robo tenta na proxima janela


def _agora_local():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(FUSO))
    except Exception:
        return datetime.now(timezone.utc)


def _para_local(iso_utc: str):
    """ISO em UTC -> datetime no fuso do dono, ou None se ilegivel."""
    txt = str(iso_utc or "").strip()
    if not txt:
        return None
    try:
        quando = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return quando.astimezone(ZoneInfo(FUSO))
    except Exception:
        return quando.astimezone(timezone.utc)


# Horas de folga para tras: uma partida em andamento ainda interessa, e o
# relogio do robo pode estar alguns minutos adiantado em relacao ao da fonte.
FOLGA_HORAS = 4.0

# A fonte usa este texto quando a chave de playoff ainda nao foi definida.
NAO_DEFINIDO = {"tbd", "to be determined", "?"}


def _e_indefinido(nome: str) -> bool:
    return str(nome or "").strip().lower() in NAO_DEFINIDO


def normalizar(eventos: Any, *, incluir_jogados: bool = False,
               incluir_indefinidos: bool = False,
               agora=None) -> Dict[str, Any]:
    """Resposta da API -> a lista que o app ja sabe consumir, mais o descarte.

    O formato de saida e o mesmo de `parse_schedule_text`, mais o `bo` real de
    cada partida (que hoje o app preenche com um unico valor padrao para todos)
    e o `estado`.

    DOIS FILTROS QUE NASCERAM DE OLHAR A SAIDA, nao de teoria (15/09/2026):

    1. HORA, e nao so o `state`. A primeira versao confiava em
       `state != "completed"` e trouxe jogos de 12/09 e 13/09 como "por vir" —
       a fonte nem sempre fecha o estado. Agenda que oferece jogo de anteontem
       faz perder tempo no melhor caso e apostar errado no pior.

    2. TBD FORA. Chave de playoff ainda nao definida vira "TBD x TBD", que nao
       da para analisar. Sao contados e ditos, nunca sumidos em silencio.
    """
    if agora is None:
        agora = _agora_local()
    corte = agora - timedelta(hours=FOLGA_HORAS)

    fora: List[Dict[str, Any]] = []
    descartes = {"ja_jogados": 0, "passados": 0, "indefinidos": 0, "sem_dois_times": 0}

    for ev in (eventos or []):
        if not isinstance(ev, dict):
            continue
        estado = str(ev.get("state") or "").strip()
        if not incluir_jogados and estado == "completed":
            descartes["ja_jogados"] += 1
            continue

        quando = _para_local(ev.get("startTime"))
        if quando is None:
            continue
        if not incluir_jogados and quando < corte:
            descartes["passados"] += 1
            continue

        partida = ev.get("match") if isinstance(ev.get("match"), dict) else {}
        times = partida.get("teams") if isinstance(partida.get("teams"), list) else []
        nomes = [str((t or {}).get("name") or "").strip() for t in times]
        nomes = [n for n in nomes if n]
        if len(nomes) < 2:
            descartes["sem_dois_times"] += 1
            continue
        if not incluir_indefinidos and (_e_indefinido(nomes[0]) or _e_indefinido(nomes[1])):
            descartes["indefinidos"] += 1
            continue

        estrategia = partida.get("strategy") if isinstance(partida.get("strategy"), dict) else {}
        try:
            bo = int(estrategia.get("count") or 0)
        except (TypeError, ValueError):
            bo = 0
        if bo not in (1, 3, 5):
            bo = 0   # PRINCIPIO IV: formato desconhecido nao vira 3 chutado

        fora.append({
            "date": quando.strftime("%d/%m"),
            "time": quando.strftime("%H:%M"),
            "league": str((ev.get("league") or {}).get("name") or "").strip(),
            "teamA_raw": nomes[0],
            "teamB_raw": nomes[1],
            "bo": bo,
            "estado": estado,
            "inicio_utc": str(ev.get("startTime") or ""),
        })
    return {"jogos": fora, "descartes": descartes}


def _extrair_eventos(payload: Any) -> List[Any]:
    """Cava os eventos e ESTOURA se o formato mudou.

    Devolver [] quando a API mudou seria o pior resultado possivel: o app
    mostraria "nenhum jogo hoje" com toda a confianca do mundo, num dia cheio
    de jogos.
    """
    if not isinstance(payload, dict):
        raise ValueError("resposta nao e um objeto JSON")
    dados = payload.get("data")
    if not isinstance(dados, dict):
        raise ValueError("resposta sem o campo 'data' (a API mudou?)")
    agenda = dados.get("schedule")
    if not isinstance(agenda, dict):
        raise ValueError("resposta sem 'data.schedule' (a API mudou?)")
    eventos = agenda.get("events")
    if not isinstance(eventos, list):
        raise ValueError("resposta sem 'data.schedule.events' (a API mudou?)")
    return eventos


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


def _quantos_ja_tem(caminho: Path) -> int:
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
        return len(d.get("jogos") or []) if isinstance(d, dict) else 0
    except (OSError, ValueError):
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Coleta a agenda de jogos de LoL.")
    ap.add_argument("--saida", default=str(DESTINO))
    ap.add_argument("--idioma", default="pt-BR")
    ap.add_argument("--incluir-jogados", action="store_true",
                    help="Tambem grava partidas ja encerradas (para conferencia).")
    ap.add_argument("--incluir-indefinidos", action="store_true",
                    help="Tambem grava chaves com TBD (nao dao para analisar).")
    args = ap.parse_args()

    import requests

    try:
        resp = requests.get(URL, params={"hl": str(args.idioma)}, timeout=30,
                            headers={"x-api-key": CHAVE, "User-Agent": AGENTE})
    except requests.RequestException as e:
        print("[agenda] rede fora do ar ou alvo inacessivel: {}".format(e))
        print("[agenda] nada foi escrito; tenta na proxima janela.")
        return RC_TEMPORARIO

    if resp.status_code in (429, 500, 502, 503, 504):
        print("[agenda] alvo respondeu {} (temporario). Nada escrito.".format(resp.status_code))
        return RC_TEMPORARIO
    if resp.status_code != 200:
        print("[agenda] ERRO: HTTP {}. A chave publica pode ter mudado.".format(resp.status_code))
        return RC_ERRO

    try:
        eventos = _extrair_eventos(resp.json())
    except ValueError as e:
        print("[agenda] ERRO DE FORMATO: {}".format(e))
        print("[agenda] Nada foi escrito. A agenda anterior continua valendo.")
        return RC_ERRO

    resultado = normalizar(eventos, incluir_jogados=bool(args.incluir_jogados),
                           incluir_indefinidos=bool(args.incluir_indefinidos))
    jogos = resultado["jogos"]
    descartes = resultado["descartes"]
    saida = Path(str(args.saida)).expanduser()
    tinha = _quantos_ja_tem(saida)

    if not jogos:
        if tinha:
            print("[agenda] ERRO: coleta veio VAZIA e ja existe agenda com {} jogo(s).".format(tinha))
            print("[agenda] Nao vou substituir. Agenda vazia num dia de jogo e pior que agenda velha.")
            return RC_ERRO
        print("[agenda] nenhum jogo por vir agora (e nao havia agenda anterior).")

    _gravar_atomico(saida, {
        "gerado_em": _agora_local().isoformat(timespec="seconds"),
        "fonte": URL,
        "fuso": FUSO,
        "n_eventos_recebidos": len(eventos),
        "descartes": descartes,
        "jogos": jogos,
    })
    print("[agenda] {} jogo(s) gravados em {} (de {} eventos recebidos).".format(
        len(jogos), saida.name, len(eventos)))
    # O descarte e DITO, nunca silencioso: sumir com jogo calado e como o app
    # dizer "nao tem jogo hoje" sem ninguem saber por que.
    print("[agenda] descartados: {} ja jogados, {} ja passaram da hora, "
          "{} com chave indefinida (TBD), {} sem dois times.".format(
              descartes["ja_jogados"], descartes["passados"],
              descartes["indefinidos"], descartes["sem_dois_times"]))
    por_liga: Dict[str, int] = {}
    for j in jogos:
        por_liga[j["league"]] = por_liga.get(j["league"], 0) + 1
    for lg, n in sorted(por_liga.items(), key=lambda kv: -kv[1])[:8]:
        print("    {:>3}  {}".format(n, lg))
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
