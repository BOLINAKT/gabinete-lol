import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    p = root / "ml_trace_last.json"
    if not p.exists():
        print("FAIL: ml_trace_last.json nao encontrado.")
        return 1

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"FAIL: nao foi possivel ler/parsear JSON: {e}")
        return 1

    req_top = ["generated_at", "ml_trace", "resumo_markets_trace", "players_trace"]
    missing = [k for k in req_top if k not in data]
    if missing:
        # Compat legado: arquivo antigo tinha apenas o trace base em raiz.
        legacy_ok = isinstance(data.get("matchup"), dict) and isinstance(data.get("probabilities"), dict)
        if not legacy_ok:
            print(f"FAIL: chaves faltando no trace: {missing}")
            return 1
        print("WARN: ml_trace_last.json em formato legado (somente ml_trace base).")
        print("WARN: abra o app e rode 1 analise em Resumo/Players para gerar o trace combinado novo.")
        return 0

    ml_trace = data.get("ml_trace") if isinstance(data.get("ml_trace"), dict) else {}
    probs = ml_trace.get("probabilities") if isinstance(ml_trace.get("probabilities"), dict) else {}

    p_map = probs.get("p_map_used")
    if p_map is None:
        print("WARN: p_map_used ausente no ml_trace.probabilities.")

    mkt = data.get("resumo_markets_trace")
    ply = data.get("players_trace")
    mkt_n = len(mkt) if isinstance(mkt, list) else 0
    ply_n = len(ply) if isinstance(ply, list) else 0

    print("OK: trace combinado valido.")
    print(f"- resumo_markets_trace: {mkt_n} linhas")
    print(f"- players_trace: {ply_n} linhas")
    if p_map is not None:
        print(f"- p_map_used: {p_map}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
