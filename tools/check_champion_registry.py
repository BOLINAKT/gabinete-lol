# -*- coding: utf-8 -*-
"""VIGIA DO REGISTRO DE CAMPEOES — campeao novo nao pode faltar calado.

Motivo (16/08/2026): ele foi montar um draft e o Locke nao estava la. O registro
estava DEZ patches atras (16.6.1 contra 16.16.1 no jogo) e ninguem tinha como
saber: nada quebra, nada avisa, nenhum teste falha. So a tela fica sem o boneco
— e o Radar le a composicao errado, porque falta uma peca.

Mesma familia dos outros silencios do dia: o sistema segue funcionando enquanto
serve informacao incompleta.

O que ele faz:
  - compara o registro local com o Data Dragon (a fonte oficial do Riot)
  - CAMPEAO FALTANDO e defeito: com --fix, roda o gerador e conserta
  - so a versao atrasada, sem campeao faltando, e cosmetico: avisa e segue

Uso:  python tools/check_champion_registry.py [--fix]
Sai com 1 quando falta campeao e nao foi consertado (para o vigia alarmar).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
REGISTRO = ROOT / "champion_knowledge_registry.json"
DDRAGON = "https://ddragon.leagueoflegends.com"


def _get(url: str):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true",
                    help="roda o gerador quando houver campeao faltando")
    args = ap.parse_args()

    try:
        local = json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"registro ilegivel ({e}) — isso e falha, nao aviso")
        return 1
    tenho = set(local.get("champions") or {})
    versao_local = str((local.get("meta") or {}).get("version") or "?")

    try:
        versoes = _get(f"{DDRAGON}/api/versions.json")
        atual = str(versoes[0])
        oficiais = _get(f"{DDRAGON}/cdn/{atual}/data/en_US/champion.json")["data"]
    except Exception as e:
        print(f"nao consegui falar com o Data Dragon ({type(e).__name__}) — sem veredito")
        return 0                      # rede fora nao e defeito do projeto

    # A chave do registro vem do NOME normalizado, nao do id do Riot — sao
    # diferentes em 3 casos e comparar pelo id dava falso positivo:
    #   id "MonkeyKing" -> nome "Wukong" | "Nunu" -> "Nunu & Willump"
    #   "Renata" -> "Renata Glasc"
    # Usa o normalizador do proprio projeto para nao inventar um segundo.
    from app_core.champion_knowledge_core import _norm_key
    deveria = {_norm_key(v.get("name") or k) for k, v in oficiais.items()}
    faltando = sorted(deveria - tenho)
    sobrando = sorted(tenho - deveria)

    print(f"registro local : versao {versao_local} · {len(tenho)} campeoes")
    print(f"Data Dragon    : versao {atual} · {len(deveria)} campeoes")
    if sobrando:
        print(f"  no registro e nao na fonte ({len(sobrando)}): {', '.join(sobrando[:8])}")
    if not faltando:
        if versao_local != atual:
            print(f"  aviso: versao atrasada ({versao_local} -> {atual}), mas nenhum "
                  "campeao faltando — cosmetico, sem acao")
        else:
            print("  em dia")
        return 0

    print(f"\nFALTAM {len(faltando)} campeao(oes): {', '.join(faltando)}")
    if not args.fix:
        print("  rode com --fix (ou python tools/build_champion_knowledge_registry.py)")
        return 1

    print("  rodando o gerador...")
    r = subprocess.run([sys.executable, "tools/build_champion_knowledge_registry.py"],
                       cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800)
    if r.returncode != 0:
        cauda = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
        print(f"  GERADOR FALHOU (exit {r.returncode}):")
        for l in cauda:
            print(f"      {l}")
        return 1
    depois = set(json.loads(REGISTRO.read_text(encoding="utf-8")).get("champions") or {})
    ainda = sorted(deveria - depois)
    if ainda:
        print(f"  gerador rodou mas AINDA faltam: {', '.join(ainda)}")
        return 1
    print(f"  consertado: +{len(depois - tenho)} campeao(oes) -> {sorted(depois - tenho)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
