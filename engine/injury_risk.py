"""
injury_risk.py
==============
Module 3 — Injury history and aggression risk.

Produces a risk score from 0 (no risk) to 1 (maximum risk).
The composite engine inverts this when applying weight:
    contribution = (1.0 - normalized_risk_score) × weight

Two components:
    1. Historical injury frequency — games missed per season, averaged
       across career. Tiered into low/medium/high/severe buckets.
    2. Aggression index — composite of contact metrics indicating whether
       the player's style puts them at elevated future risk.
"""

from __future__ import annotations
import statistics
from dataclasses import dataclass
from typing import Optional
from engine.schema import ModuleScore


@dataclass
class InjurySummary:
    """Aggregated injury data for a single player's career."""
    player_id: str
    seasons_played: int
    total_games_missed: int
    avg_games_missed_per_season: float
    injury_types: list[str]             # all body regions in career
    had_acl_or_achilles: bool           # high-severity structural injury
    returned_same_season_rate: float    # % of injuries returned from in-year


@dataclass
class AggressionMetrics:
    """
    Contact and style metrics. All values are career averages.
    Sources: nflfastR play-by-play (broken_tackles, yards_after_contact),
             PFF (contact_rate, elusive_rating).
    """
    player_id: str
    contact_rate: Optional[float]           # % of touches with pre-catch contact
    broken_tackle_attempts_per_touch: Optional[float]
    yards_after_contact_per_touch: Optional[float]   # low = absorbs w/o benefit
    # Derived index — computed in score_injury_risk()
    aggression_index: Optional[float]       # 0.0 (avoid contact) to 1.0 (maximum)


def _compute_aggression_index(
    metrics: AggressionMetrics,
    cfg: dict,
) -> float:
    """
    Weighted combination of contact metrics into a 0–1 aggression index.

    High contact_rate         → higher risk
    High broken_tackle_att    → higher risk (seeking contact)
    Low yards_after_contact   → higher risk (absorbing punishment w/o reward)

    Components are first min-max normalized against position population averages
    (hardcoded here as reasonable NFL population bounds — refine with real data).
    """
    comp_weights = cfg.get("aggression_components", {
        "contact_rate": 0.40,
        "broken_tackle_attempts": 0.35,
        "yards_after_contact": 0.25,
    })

    components: dict[str, float] = {}

    # Contact rate: 0.20 = low, 0.70 = high (population bounds)
    if metrics.contact_rate is not None:
        components["contact_rate"] = _norm(metrics.contact_rate, 0.20, 0.70)

    # Broken tackle attempts per touch: 0.05 = low, 0.35 = high
    if metrics.broken_tackle_attempts_per_touch is not None:
        components["broken_tackle_attempts"] = _norm(
            metrics.broken_tackle_attempts_per_touch, 0.05, 0.35
        )

    # Yards after contact per touch: INVERTED — high YAC = escaping,
    # low YAC = absorbing. Range: 1.0 (low) to 3.5 (high)
    if metrics.yards_after_contact_per_touch is not None:
        components["yards_after_contact"] = 1.0 - _norm(
            metrics.yards_after_contact_per_touch, 1.0, 3.5
        )

    if not components:
        return 0.5   # neutral if no data

    total_w = sum(comp_weights[k] for k in components)
    if total_w == 0:
        return 0.5

    index = sum(components[k] * comp_weights[k] for k in components) / total_w
    return max(0.0, min(1.0, index))


def _norm(value: float, lo: float, hi: float) -> float:
    """Clamp-then-normalize to [0, 1]."""
    if hi == lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def score_injury_risk(
    player_id: str,
    injury_summary: Optional[InjurySummary],
    aggression_metrics: Optional[AggressionMetrics],
    config: dict,
    upcoming_season: int,
) -> ModuleScore:
    """
    Compute injury risk module score.

    The raw_score returned is the risk level (higher = more risky).
    The composite engine treats this module as an inverse contributor:
    a player with raw_score=0.9 (high risk) gets LOW composite credit
    from this module.

    Parameters
    ----------
    player_id:
        Player identifier.
    injury_summary:
        Aggregated career injury data. None if no injury records exist
        (treated as low risk — benefit of the doubt).
    aggression_metrics:
        Career contact metrics. None if data unavailable (index = 0.5).
    config:
        Full config dict.
    upcoming_season:
        Season being projected.
    """
    inj_cfg = config.get("injury_risk", {})
    aggression_weight = inj_cfg.get("aggression_weight", 0.35)
    frequency_weight = 1.0 - aggression_weight

    tiers = inj_cfg.get("injury_frequency_tiers", {
        "low":    {"max_games_missed": 2,  "multiplier": 1.00},
        "medium": {"max_games_missed": 5,  "multiplier": 0.90},
        "high":   {"max_games_missed": 9,  "multiplier": 0.78},
        "severe": {"max_games_missed": 99, "multiplier": 0.62},
    })

    flags: list[str] = []
    reasoning: list[str] = []

    # --- Frequency component ---
    if injury_summary and injury_summary.seasons_played > 0:
        avg_missed = injury_summary.avg_games_missed_per_season

        if avg_missed <= tiers["low"]["max_games_missed"]:
            tier_label = "low"
            freq_score = 0.10    # low risk
        elif avg_missed <= tiers["medium"]["max_games_missed"]:
            tier_label = "medium"
            freq_score = 0.35
        elif avg_missed <= tiers["high"]["max_games_missed"]:
            tier_label = "high"
            freq_score = 0.65
            flags.append("injury_risk_high")
        else:
            tier_label = "severe"
            freq_score = 0.90
            flags.append("injury_risk_high")

        reasoning.append(
            f"Career injury frequency: {avg_missed:.1f} games missed/season "
            f"({tier_label} risk tier)."
        )

        # Structural injury (ACL/Achilles) — adds context note
        if injury_summary.had_acl_or_achilles:
            reasoning.append(
                "Has a prior ACL or Achilles injury in career — "
                "long-term structural concern."
            )
    else:
        freq_score = 0.10   # no injury records → low risk
        reasoning.append("No significant injury history on record.")

    # --- Aggression component ---
    if aggression_metrics:
        agg_index = _compute_aggression_index(aggression_metrics, inj_cfg)
        aggression_metrics.aggression_index = agg_index

        if agg_index >= 0.70:
            flags.append("aggression_high")
            reasoning.append(
                f"High-contact playing style (aggression index: {agg_index:.2f}) — "
                "seeks or absorbs contact frequently, elevating injury probability."
            )
        elif agg_index >= 0.45:
            reasoning.append(
                f"Moderate contact rate (aggression index: {agg_index:.2f})."
            )
        else:
            reasoning.append(
                f"Contact-avoidant style (aggression index: {agg_index:.2f}) "
                "reduces injury risk."
            )
    else:
        agg_index = 0.50   # neutral if unavailable

    # --- Composite risk score ---
    raw_risk = (freq_score * frequency_weight) + (agg_index * aggression_weight)
    raw_risk = max(0.0, min(1.0, raw_risk))

    # Note: composite.py will invert this — high risk → low contribution
    return ModuleScore(
        player_id=player_id,
        season_evaluated=upcoming_season,
        module_name="injury_risk",
        raw_score=raw_risk,
        normalized_score=0.0,
        weight_applied=0.0,
        weighted_contribution=0.0,
        flags=flags,
        reasoning=reasoning,
    )
