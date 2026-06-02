from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_core.champion_knowledge_core import TRAIT_KEYS, STYLE_TRAITS, default_registry_path
from app_core.players_data_core import CHAMPION_ALIASES, load_player_rows


APP_ROOT = Path(__file__).resolve().parent.parent
CSV_GLOBS = (
    APP_ROOT / "CSV_HISTORICO",
    APP_ROOT / "CSV_DIARIO",
)

ROLE_ORDER = ("top", "jng", "mid", "bot", "sup")

TAG_DEFAULTS: dict[str, dict[str, float]] = {
    "Fighter": {"early": 1.0, "mid": 1.2, "late": 0.4, "lane_priority": 1.0, "all_in": 1.3, "dive": 1.2, "skirmish": 1.4, "teamfight": 0.7, "splitpush": 0.25, "mobility": 0.6},
    "Tank": {"early": -0.2, "mid": 0.8, "late": 1.4, "frontline": 2.4, "engage": 1.8, "teamfight": 1.8, "objective_control": 0.6},
    "Mage": {"early": 0.2, "mid": 1.4, "late": 1.5, "poke": 1.2, "waveclear": 1.6, "pick": 0.8, "teamfight": 1.2, "range": 0.8},
    "Assassin": {"early": 1.0, "mid": 1.7, "late": -0.4, "all_in": 1.2, "pick": 1.8, "dive": 1.4, "mobility": 1.7, "execution": 1.8},
    "Marksman": {"early": 0.1, "mid": 1.1, "late": 2.2, "range": 1.8, "siege": 1.6, "objective_control": 1.4, "teamfight": 1.0},
    "Support": {"early": 0.4, "mid": 0.8, "late": 0.7, "peel": 1.4, "engage": 0.8, "teamfight": 0.9},
}

ROLE_DEFAULTS: dict[str, dict[str, float]] = {
    "top": {"lane_priority": 0.4, "frontline": 0.5, "splitpush": 0.15},
    "jng": {"objective_control": 1.0, "skirmish": 0.8, "mobility": 0.4, "engage": 0.5},
    "mid": {"waveclear": 0.5, "pick": 0.5, "lane_priority": 0.4},
    "bot": {"range": 0.8, "siege": 0.8, "objective_control": 0.6},
    "sup": {"engage": 0.5, "peel": 0.7, "teamfight": 0.4},
}

ROLE_FALLBACKS = {
    "Support": "sup",
    "Marksman": "bot",
    "Assassin": "mid",
    "Mage": "mid",
    "Tank": "top",
    "Fighter": "top",
}

CHAMPION_OVERRIDES: dict[str, dict[str, float]] = {
    "Aatrox": {"mid": 0.6, "late": 0.4, "skirmish": 0.8, "teamfight": 0.8},
    "Ahri": {"pick": 1.0, "mobility": 0.6, "late": 0.4, "poke": 0.4},
    "Alistar": {"engage": 1.0, "frontline": 0.8, "late": -0.3, "pick": 0.4},
    "Ambessa": {"early": 1.1, "mid": 0.8, "dive": 0.8, "mobility": 0.6, "execution": 0.6},
    "Anivia": {"early": -1.0, "late": 1.6, "waveclear": 1.0, "teamfight": 0.8, "range": 0.5},
    "Annie": {"pick": 0.8, "engage": 0.4, "all_in": 0.6, "late": -0.3},
    "Aphelios": {"late": 1.2, "early": -0.5, "teamfight": 0.8, "execution": 0.6},
    "Ashe": {"pick": 1.2, "poke": 0.8, "late": 0.4},
    "Aurora": {"mid": 0.8, "late": 0.8, "mobility": 0.4, "execution": 0.6},
    "Azir": {"early": -0.5, "mid": 0.6, "late": 1.6, "teamfight": 1.0, "siege": 0.6, "range": 0.6},
    "Bard": {"pick": 0.9, "mobility": 0.8, "execution": 0.8},
    "Braum": {"peel": 1.0, "frontline": 0.6, "engage": -0.2, "late": 0.4},
    "Caitlyn": {"early": 1.4, "lane_priority": 1.0, "siege": 1.0, "late": 0.2, "poke": 0.5},
    "Cassiopeia": {"late": 1.0, "teamfight": 0.8, "early": -0.2},
    "Corki": {"early": -0.4, "mid": 0.7, "late": 1.2, "poke": 1.0, "siege": 0.4},
    "Dr. Mundo": {"late": 1.0, "frontline": 1.2, "splitpush": 0.7, "lane_priority": -0.6},
    "Ezreal": {"poke": 0.9, "mobility": 0.5, "late": 0.6, "all_in": -0.4},
    "Galio": {"engage": 0.8, "teamfight": 0.6, "waveclear": 0.4, "pick": 0.4},
    "Gnar": {"lane_priority": 0.8, "teamfight": 0.8, "splitpush": 0.4, "late": 0.4},
    "Gwen": {"late": 1.1, "splitpush": 0.9, "early": -0.3, "teamfight": 0.4},
    "Hwei": {"poke": 1.0, "waveclear": 1.0, "late": 0.8, "execution": 0.4},
    "Jarvan IV": {"engage": 1.0, "dive": 1.0, "objective_control": 0.4, "late": -1.3, "splitpush": -0.9},
    "Jax": {"late": 1.4, "splitpush": 1.2, "early": -0.4, "teamfight": -0.2},
    "Jayce": {"early": 1.2, "lane_priority": 1.0, "poke": 1.0, "late": -0.4, "siege": 0.5},
    "Jhin": {"pick": 0.8, "poke": 0.7, "late": 0.4, "all_in": -0.3},
    "Jinx": {"late": 1.4, "teamfight": 0.8, "siege": 0.6, "early": -0.6},
    "Kai'Sa": {"mid": 0.7, "late": 0.8, "dive": 0.8, "all_in": 0.4, "execution": 0.4},
    "Karma": {"poke": 0.9, "lane_priority": 0.8, "peel": 0.5, "late": -0.3},
    "K'Sante": {"frontline": 1.4, "teamfight": 0.8, "late": 0.6, "execution": 0.6},
    "Lee Sin": {"early": 1.4, "mid": 0.8, "late": -0.8, "mobility": 0.8, "execution": 0.8},
    "Leona": {"engage": 1.2, "all_in": 0.8, "late": -1.1, "peel": -0.2},
    "Lucian": {"early": 1.4, "lane_priority": 1.0, "all_in": 0.6, "late": -0.8},
    "Lulu": {"peel": 1.4, "late": 0.8, "engage": -0.4, "lane_priority": -0.2},
    "Maokai": {"engage": 0.8, "frontline": 1.0, "objective_control": 0.5, "late": 0.4},
    "Miss Fortune": {"early": 0.8, "mid": 0.8, "late": -0.2, "teamfight": 0.6, "poke": 0.3},
    "Nami": {"early": 0.8, "poke": 0.7, "peel": 0.6, "late": -0.2},
    "Nautilus": {"engage": 1.4, "pick": 0.8, "frontline": 0.6, "late": -0.3},
    "Neeko": {"engage": 0.8, "pick": 0.6, "teamfight": 0.7, "waveclear": 0.4},
    "Nocturne": {"dive": 1.4, "pick": 0.9, "mid": 0.8, "late": -0.2, "execution": 0.4},
    "Orianna": {"early": -0.4, "mid": 0.8, "late": 1.4, "teamfight": 1.2, "peel": 0.3},
    "Ornn": {"early": -1.4, "late": 1.8, "frontline": 1.4, "engage": 0.8, "teamfight": 1.0},
    "Pantheon": {"early": 1.6, "pick": 1.0, "late": -1.0, "dive": 0.6, "splitpush": -0.8},
    "Poppy": {"skirmish": 0.6, "frontline": 0.8, "pick": 0.4, "late": 0.2},
    "Qiyana": {"pick": 1.2, "mobility": 0.8, "execution": 1.0, "late": -0.6},
    "Rakan": {"engage": 1.0, "teamfight": 0.8, "mobility": 0.7, "peel": 0.4},
    "Rell": {"engage": 1.3, "teamfight": 0.9, "frontline": 0.6, "late": 0.2},
    "Renata Glasc": {"peel": 1.0, "late": 0.7, "engage": -0.3, "pick": 0.3},
    "Renekton": {"early": 1.8, "lane_priority": 1.4, "all_in": 1.0, "late": -1.2, "dive": 0.7},
    "Rek'Sai": {"early": 1.3, "pick": 0.7, "mobility": 0.6, "late": -0.9},
    "Rumble": {"early": 1.0, "mid": 0.8, "teamfight": 0.9, "waveclear": 0.3, "splitpush": -1.3},
    "Ryze": {"early": -0.3, "mid": 0.8, "late": 1.1, "waveclear": 0.8, "splitpush": 0.6},
    "Sejuani": {"engage": 0.8, "frontline": 0.9, "late": 0.4, "objective_control": 0.3},
    "Seraphine": {"late": 1.0, "peel": 0.8, "teamfight": 0.8, "waveclear": 0.6},
    "Sion": {"frontline": 1.4, "siege": 0.6, "late": 0.7, "lane_priority": -0.5},
    "Sivir": {"waveclear": 0.8, "siege": 0.7, "late": 0.6, "all_in": -0.3},
    "Skarner": {"engage": 1.2, "pick": 1.2, "frontline": 0.7, "mobility": 0.4},
    "Syndra": {"pick": 0.8, "poke": 0.7, "late": 0.7, "waveclear": 0.5},
    "Taliyah": {"mid": 0.9, "pick": 0.8, "objective_control": 0.4, "late": -0.1},
    "Thresh": {"pick": 1.0, "peel": 0.8, "engage": 0.5, "execution": 0.5, "late": -1.0},
    "Tristana": {"early": 0.7, "mid": 0.7, "late": 0.9, "siege": 0.6, "mobility": 0.5},
    "Trundle": {"skirmish": 0.6, "splitpush": 0.4, "objective_control": 0.5, "late": -0.2},
    "Varus": {"poke": 1.0, "pick": 0.8, "lane_priority": 0.4, "late": 0.3},
    "Vi": {"engage": 1.3, "pick": 1.2, "dive": 0.9, "mid": 0.8, "late": -0.2},
    "Viktor": {"early": -0.5, "late": 1.4, "waveclear": 0.9, "teamfight": 0.8},
    "Wukong": {"engage": 0.8, "teamfight": 1.0, "mid": 0.8, "late": 0.2},
    "Xayah": {"late": 1.0, "peel": 0.6, "teamfight": 0.7, "early": -0.2},
    "Xin Zhao": {"early": 1.1, "skirmish": 1.0, "engage": 0.6, "late": -0.4},
    "Yone": {"late": 1.0, "all_in": 0.7, "mobility": 0.7, "execution": 0.6},
    "Yorick": {"splitpush": 1.5, "late": 0.8, "teamfight": -0.6, "lane_priority": 0.2},
    "Zeri": {"late": 1.4, "mobility": 0.8, "early": -0.8, "execution": 0.6},
    "Ziggs": {"siege": 1.1, "waveclear": 1.0, "poke": 0.8, "late": 0.5},
}


def _norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _fetch_json(url: str) -> dict[str, Any] | list[Any]:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def _discover_csv_paths() -> list[Path]:
    out: list[Path] = []
    for base in CSV_GLOBS:
        out.extend(sorted(base.glob("*LoL_esports_match_data_from_OraclesElixir.csv")))
    return out


def _observed_roles() -> dict[str, Counter[str]]:
    by_champ: dict[str, Counter[str]] = defaultdict(Counter)
    for csv_path in _discover_csv_paths():
        try:
            df = load_player_rows(csv_path=str(csv_path))
        except Exception:
            continue
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            champ = str(row.get("champ") or "").strip()
            pos = str(row.get("pos_ml") or row.get("pos") or "").strip().lower()
            if not champ or pos not in ROLE_ORDER:
                continue
            by_champ[champ][pos] += 1
    return by_champ


def _merge_traits(*parts: dict[str, float]) -> dict[str, float]:
    out = {key: 0.0 for key in TRAIT_KEYS}
    for part in parts:
        for key, value in part.items():
            if key not in out:
                continue
            out[key] += float(value or 0.0)
    for key in out:
        lo = -2.0 if key in {"early", "mid", "late", "lane_priority"} else 0.0
        hi = 3.0
        out[key] = max(lo, min(hi, out[key]))
    return out


def _fallback_role(tags: list[str]) -> str:
    for tag in tags:
        if tag in ROLE_FALLBACKS:
            return ROLE_FALLBACKS[tag]
    return "mid"


def _styles_from_traits(traits: dict[str, float]) -> list[str]:
    ordered = sorted(((name, float(traits.get(name, 0.0) or 0.0)) for name in STYLE_TRAITS), key=lambda item: item[1], reverse=True)
    return [name for name, score in ordered if score > 0.6][:3]


def _window_label(traits: dict[str, float]) -> str:
    windows = {name: float(traits.get(name, 0.0) or 0.0) for name in ("early", "mid", "late")}
    ordered = sorted(windows.items(), key=lambda item: item[1], reverse=True)
    if not ordered:
        return "mid"
    top_name, top_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else top_score
    if abs(top_score - second_score) <= 0.35:
        return "balanced"
    return top_name


def _build_entry(champ: dict[str, Any], observed: Counter[str]) -> dict[str, Any]:
    name = str(champ.get("name") or "")
    tags = [str(value) for value in list(champ.get("tags") or []) if str(value)]
    primary_role = observed.most_common(1)[0][0] if observed else _fallback_role(tags)
    secondary_roles = [role for role, _count in observed.most_common() if role != primary_role][:2]
    traits = _merge_traits(
        *(TAG_DEFAULTS.get(tag, {}) for tag in tags),
        ROLE_DEFAULTS.get(primary_role, {}),
        CHAMPION_OVERRIDES.get(name, {}),
    )
    styles = _styles_from_traits(traits)
    entry = {
        "id": str(champ.get("id") or ""),
        "key": str(champ.get("key") or ""),
        "name": name,
        "tags": tags,
        "partype": str(champ.get("partype") or ""),
        "primary_role": primary_role,
        "secondary_roles": secondary_roles,
        "observed_roles": {role: int(count) for role, count in observed.items()},
        "window": _window_label(traits),
        "styles": styles,
        "traits": traits,
    }
    return entry


def build_registry() -> dict[str, Any]:
    versions = _fetch_json("https://ddragon.leagueoflegends.com/api/versions.json")
    version = str((versions or [""])[0] or "")
    payload = _fetch_json(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/championFull.json")
    champs = (payload or {}).get("data") or {}
    observed_roles = _observed_roles()
    champions_out: dict[str, Any] = {}
    aliases_out: dict[str, str] = {}
    for raw in champs.values():
        entry = _build_entry(dict(raw or {}), observed_roles.get(str(raw.get("name") or ""), Counter()))
        norm = _norm_key(entry["name"])
        champions_out[norm] = entry
        aliases_out[norm] = norm
        aliases_out[_norm_key(str(raw.get("id") or ""))] = norm
        aliases_out[_norm_key(str(raw.get("name") or "").replace(".", ""))] = norm
    for alias_key, target in CHAMPION_ALIASES.items():
        target_norm = _norm_key(target)
        if target_norm in champions_out:
            aliases_out[_norm_key(alias_key)] = target_norm
    return {
        "meta": {
            "source": "Riot Data Dragon + Oracle player rows",
            "version": version,
            "champion_count": len(champions_out),
            "csv_files": [str(path) for path in _discover_csv_paths()],
        },
        "aliases": aliases_out,
        "champions": champions_out,
    }


def main() -> int:
    registry = build_registry()
    out_path = default_registry_path()
    out_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Champions: {len((registry.get('champions') or {}))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
