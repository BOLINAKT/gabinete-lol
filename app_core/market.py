from __future__ import annotations

from typing import List, Optional, Tuple
import math
import re

from mlcore.utils import decimal_odds_to_prob, prob_to_decimal_odds


def parse_lines_text(text: str) -> List[float]:
    """Parse a comma/space/semicolon-separated string of numeric lines into a list of floats."""
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"[,\s;]+", text)
    out: List[float] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            out.append(float(p))
        except Exception:
            continue
    return out


def parse_time_lines_text(text: str) -> List[float]:
    """Parse game-time lines in MM:00, MM:30, integer, or decimal formats into fractional minutes."""
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"[,\s;]+", text)
    out: List[float] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue

        m = re.fullmatch(r"(\d+):(00|30)", p)
        if m:
            mm = float(m.group(1))
            ss = float(m.group(2))
            out.append(mm + ss / 60.0)
            continue

        if re.fullmatch(r"\d+", p):
            out.append(float(p))
            continue

        m = re.fullmatch(r"(\d+)\.(0|5)", p)
        if m:
            out.append(float(p))
            continue

    return out


def matchup_key(season_label: str, team_a: str, team_b: str) -> str:
    """Build a canonical matchup key with sorted teams to ensure A vs B == B vs A."""
    a = (team_a or "").strip()
    b = (team_b or "").strip()
    s = (season_label or "").strip()
    pair = "|".join(sorted([a, b]))
    return f"{s}::{pair}" if s else pair


def odd_from_prob(p: float) -> Optional[float]:
    """Convert a win probability to decimal odds (1/p). Returns None for invalid inputs."""
    if p is None or not math.isfinite(float(p)):
        return None
    try:
        return float(prob_to_decimal_odds(float(p)))
    except Exception:
        return None


def prob_from_odd(odd: float) -> Optional[float]:
    """Convert decimal odds to implied probability. Returns None for odds <= 1 or non-finite."""
    try:
        p = float(decimal_odds_to_prob(float(odd)))
        if not math.isfinite(p):
            return None
        return p
    except Exception:
        return None


def combine_ml_totals_probs(
    p_ml: float,
    p_over: float,
    *,
    p_over_given_ml: Optional[float] = None,
    dependence: float = 0.0,
) -> Tuple[float, float]:
    """Return (P(ML&Over), P(ML&Under)) with coherent bounds.

    Behavior:
    - No conditional input: starts from independence baseline.
    - With conditional input: uses P(ML) * P(Over|ML), then clamps to Fréchet bounds.
    - Optional dependence in [-1, 1] nudges toward Fréchet-extreme comonotonic/countermonotonic
      joint around the marginal baseline.
    """

    try:
        p_ml_f = float(p_ml)
        p_over_f = float(p_over)
    except Exception:
        return float("nan"), float("nan")
    if not (math.isfinite(p_ml_f) and math.isfinite(p_over_f)):
        return float("nan"), float("nan")

    p_ml_f = max(0.0, min(1.0, p_ml_f))
    p_over_f = max(0.0, min(1.0, p_over_f))

    low = max(0.0, p_ml_f + p_over_f - 1.0)
    high = min(p_ml_f, p_over_f)

    # Marginal-only baseline.
    p_joint_ind = p_ml_f * p_over_f

    # Dependence template around baseline (Fréchet-consistent by construction).
    dep = max(-1.0, min(1.0, float(dependence) if math.isfinite(float(dependence)) else 0.0))
    if dep >= 0.0:
        p_joint_dep = p_joint_ind + dep * (high - p_joint_ind)
    else:
        p_joint_dep = p_joint_ind - abs(dep) * (p_joint_ind - low)

    p_joint = p_joint_dep
    has_cond = p_over_given_ml is not None
    if has_cond:
        try:
            cond = float(p_over_given_ml)
        except Exception:
            cond = float("nan")
        if not math.isfinite(cond):
            has_cond = False
        else:
            cond = max(0.0, min(1.0, cond))
            p_joint = p_ml_f * cond
    if not has_cond:
        p_joint = p_joint_dep
    else:
        # Keep optional dependence as a bounded nudge on top of conditional estimate.
        alpha = abs(dep)
        p_joint = (1.0 - alpha) * p_joint + alpha * p_joint_dep

    p_joint = max(low, min(high, p_joint))
    p_ml_under = max(0.0, p_ml_f - p_joint)
    return float(p_joint), float(p_ml_under)
