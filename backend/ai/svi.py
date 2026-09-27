"""Stress Vulnerability Index scoring engine.

The whole point of this module is that the number is *not* an AI guess. The
model supplies component signals; the arithmetic that turns them into an SVI
lives here, in plain Python, so it is transparent, reproducible and auditable.

Formula (fixed for the prototype):

    base_score      = 0.5 * distress_score + 0.5 * danger_score
    indicator_bonus = min(20, 5 * number_of_true_indicators)
    svi_score       = min(100, base_score + indicator_bonus)
    if safety_floor_triggered:
        svi_score   = max(svi_score, 80)     # deterministic Critical floor

Bands: lower bound inclusive, upper exclusive, with 100 falling in Critical.
"""
from __future__ import annotations

from typing import Dict, Mapping

INDICATOR_KEYS = (
    "fear",
    "threat",
    "high_stress",
    "emotional_distress",
    "social_isolation",
)

POINTS_PER_INDICATOR = 5
MAX_INDICATOR_BONUS = 20
SAFETY_FLOOR_SCORE = 80

BANDS = (
    (0, 40, "Low"),
    (40, 60, "Moderate"),
    (60, 80, "High"),
    (80, 101, "Critical"),
)


def band_for(score: float) -> str:
    """Map any 0-100 score onto its risk band."""
    s = clamp(score)
    for low, high, label in BANDS:
        if low <= s < high:
            return label
    return "Critical"


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def count_indicators(indicators: Mapping[str, bool]) -> int:
    return sum(1 for k in INDICATOR_KEYS if bool(indicators.get(k)))


def compute_svi(
    distress_score: float,
    danger_score: float,
    indicators: Mapping[str, bool],
    safety_floor_triggered: bool,
) -> Dict[str, object]:
    """Return the SVI plus every intermediate term, so the UI can explain it."""
    distress = clamp(distress_score)
    danger = clamp(danger_score)

    base_score = 0.5 * distress + 0.5 * danger
    n_indicators = count_indicators(indicators)
    indicator_bonus = min(MAX_INDICATOR_BONUS, POINTS_PER_INDICATOR * n_indicators)

    score = min(100.0, base_score + indicator_bonus)
    floor_applied = False
    if safety_floor_triggered and score < SAFETY_FLOOR_SCORE:
        score = float(SAFETY_FLOOR_SCORE)
        floor_applied = True

    svi_score = int(round(score))

    # A plain-language trail of the arithmetic, so the dashboard can show the
    # working rather than asking a counsellor to trust a number.
    explanation = [
        f"Distress {int(round(distress))} and danger {int(round(danger))} are averaged "
        f"equally, giving a base of {round(base_score, 1)}.",
    ]
    if n_indicators:
        fired = ", ".join(k.replace("_", " ") for k in INDICATOR_KEYS if indicators.get(k))
        explanation.append(
            f"{n_indicators} risk indicator(s) present ({fired}) add "
            f"{indicator_bonus} points, capped at {MAX_INDICATOR_BONUS}.")
    else:
        explanation.append("No risk indicators were flagged, so no bonus was added.")
    if floor_applied:
        explanation.append(
            f"A deterministic safety rule fired outside the model, so the score is raised "
            f"to the Critical floor of {SAFETY_FLOOR_SCORE}.")
    elif safety_floor_triggered:
        explanation.append(
            f"A safety rule fired, but the computed score was already at or above the "
            f"floor of {SAFETY_FLOOR_SCORE}, so no floor was needed.")
    explanation.append(
        f"Final SVI is {svi_score}, which falls in the {band_for(svi_score)} band.")

    return {
        "svi_score": svi_score,
        "score_explanation": explanation,
        "svi_category": band_for(svi_score),
        "distress_score": int(round(distress)),
        "danger_score": int(round(danger)),
        "distress_band": band_for(distress),
        "danger_band": band_for(danger),
        "base_score": round(base_score, 2),
        "indicator_count": n_indicators,
        "indicator_bonus": indicator_bonus,
        "safety_floor_triggered": bool(safety_floor_triggered),
        "safety_floor_applied": floor_applied,
    }
