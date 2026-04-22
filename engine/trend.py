"""
trend.py
========
Module 2 — Trajectory & trend analysis.

For each player, this module analyzes their fantasy point output
across seasons to determine whether they are rising, declining,
consistent, or volatile.

Outputs a raw_score that feeds the composite engine, plus flags
and reasoning bullets.

Key concepts:
    - Weighted mean:    career mean with recency bias applied
    - Year-over-year delta: last season minus prior season (normalized)
    - Linear regression slope: fitted across all seasons (normalized)
    - Coefficient of variation (CV): std dev / mean — consistency proxy
    - Rising flag: last season > (career mean + threshold × std dev)
    - Declining flag: last season < (career mean - threshold × std dev)
    - Boom-bust flag: CV above configured threshold
    - TD regression risk: last-season TD rate > threshold σ above career
"""

from __future__ import annotations
import statistics
from dataclasses import dataclass
from typing import Optional
from engine.schema import ModuleScore


@dataclass
class SeasonPoint:
    """A single season's fantasy point total with its games-played factor."""
    season: int
    fantasy_points: float       # total for the season
    games_played: int
    recency_weight: float       # from config (e.g. 1.0, 0.7, 0.45...)
    games_factor: float         # games_played / min_games_threshold, capped at 1.0
    effective_weight: float     # recency_weight × games_factor


def _linear_slope(xs: list[float], ys: list[float]) -> float:
    """
    Ordinary least squares slope for a small series.
    Returns 0.0 if fewer than 2 points.
    """
    n = len(xs)
    if n < 2:
        return 0.0
    x_bar = sum(xs) / n
    y_bar = sum(ys) / n
    num = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys))
    den = sum((x - x_bar) ** 2 for x in xs)
    return num / den if den != 0 else 0.0


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    """Weighted arithmetic mean. Returns 0.0 if total weight is zero."""
    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_w


def score_trend(
    player_id: str,
    season_points: list[SeasonPoint],     # sorted oldest → newest
    season_td_rates: list[tuple[int, float]],  # [(season, td_rate), ...] oldest→newest
    config: dict,
    upcoming_season: int,
) -> ModuleScore:
    """
    Compute the trend module score for a single player.

    Parameters
    ----------
    player_id:
        Unique player identifier.
    season_points:
        List of SeasonPoint objects, one per season in lookback window,
        sorted oldest to newest.
    season_td_rates:
        List of (season, td_rate) tuples where td_rate = TDs / touches_or_targets.
        Used only for the TD regression flag.
    config:
        Full parsed config dict (from league_config.yaml).
    upcoming_season:
        The season being projected (for labelling purposes).

    Returns
    -------
    ModuleScore with:
        raw_score       — weighted mean of per-game fantasy points
                          adjusted by trajectory direction
        flags           — "rising", "declining", "boom_bust",
                          "td_regression_risk" as applicable
        reasoning       — list of plain-English explanation bullets
    """
    trend_cfg = config.get("trend", {})
    rising_threshold = trend_cfg.get("rising_threshold_stdev", 1.0)
    declining_threshold = trend_cfg.get("declining_threshold_stdev", 1.5)
    boom_bust_threshold = trend_cfg.get("boom_bust_cv_threshold", 0.55)
    td_reg_threshold = trend_cfg.get("td_regression_stdev_threshold", 1.5)
    min_games = config["history"].get("min_games_threshold", 12)

    flags: list[str] = []
    reasoning: list[str] = []

    if not season_points:
        return ModuleScore(
            player_id=player_id,
            season_evaluated=upcoming_season,
            module_name="trend",
            raw_score=0.0,
            normalized_score=0.0,
            weight_applied=0.0,
            weighted_contribution=0.0,
            flags=["no_data"],
            reasoning=["No historical data available for trend analysis."],
        )

    # --- Per-game normalisation ---
    # Convert season totals to per-game to remove games-played distortion
    per_game = [
        sp.fantasy_points / max(sp.games_played, 1)
        for sp in season_points
    ]
    eff_weights = [sp.effective_weight for sp in season_points]

    # --- Weighted mean ---
    wmean = _weighted_mean(per_game, eff_weights)

    # --- Standard deviation (unweighted, population) ---
    if len(per_game) >= 2:
        std = statistics.pstdev(per_game)
    else:
        std = 0.0

    # --- Coefficient of variation ---
    cv = (std / wmean) if wmean > 0 else 0.0

    # --- Last season's per-game output ---
    last_sp = season_points[-1]   # newest season
    last_per_game = last_sp.fantasy_points / max(last_sp.games_played, 1)

    # --- Year-over-year delta ---
    if len(season_points) >= 2:
        prev_sp = season_points[-2]
        prev_per_game = prev_sp.fantasy_points / max(prev_sp.games_played, 1)
        yoy_delta = last_per_game - prev_per_game
    else:
        yoy_delta = 0.0

    # --- Linear regression slope (positive = upward trend) ---
    xs = [float(sp.season) for sp in season_points]
    slope = _linear_slope(xs, per_game)

    # --- Trajectory score: base is weighted mean, adjusted by slope ---
    # Positive slope adds up to 15% bonus; negative subtracts up to 15%.
    # Slope is normalized against a typical range of ±2 pts/game/season.
    slope_factor = max(-0.15, min(0.15, slope / 2.0 * 0.15))
    trajectory_score = wmean * (1.0 + slope_factor)

    # --- Rising / declining flags ---
    if std > 0:
        if last_per_game > wmean + rising_threshold * std:
            flags.append("rising")
            reasoning.append(
                f"Last season's output ({last_per_game:.1f} pts/game) was "
                f"significantly above career mean ({wmean:.1f}), suggesting "
                "upward momentum."
            )
        elif last_per_game < wmean - declining_threshold * std:
            flags.append("declining")
            reasoning.append(
                f"Last season's output ({last_per_game:.1f} pts/game) was "
                f"well below career mean ({wmean:.1f}) — sustained decline or role change."
            )

    # --- Boom-bust flag ---
    if cv >= boom_bust_threshold:
        flags.append("boom_bust")
        reasoning.append(
            f"High game-to-game variance (CV={cv:.2f}) — ceiling is elite "
            "but weekly floor is inconsistent."
        )

    # --- TD regression flag ---
    if len(season_td_rates) >= 2:
        td_rates = [r for _, r in season_td_rates]
        last_td_rate = td_rates[-1]
        if len(td_rates) >= 2:
            td_mean = statistics.mean(td_rates[:-1])
            td_std = statistics.pstdev(td_rates[:-1]) if len(td_rates) > 2 else 0.0
            if td_std > 0 and last_td_rate > td_mean + td_reg_threshold * td_std:
                flags.append("td_regression_risk")
                reasoning.append(
                    f"Last season's TD rate ({last_td_rate:.3f}) was unusually high "
                    f"relative to prior seasons ({td_mean:.3f} avg) — some regression "
                    "in touchdowns is likely."
                )

    # --- YoY reasoning (only if notable and no rising/declining flag) ---
    if "rising" not in flags and "declining" not in flags:
        if abs(yoy_delta) > 1.0:
            direction = "up" if yoy_delta > 0 else "down"
            reasoning.append(
                f"Year-over-year production was {direction} "
                f"{abs(yoy_delta):.1f} pts/game vs prior season."
            )

    # --- Fallback reasoning ---
    if not reasoning:
        reasoning.append(
            f"Production is stable — {wmean:.1f} pts/game career average "
            f"over {len(season_points)} season(s)."
        )

    return ModuleScore(
        player_id=player_id,
        season_evaluated=upcoming_season,
        module_name="trend",
        raw_score=trajectory_score,
        normalized_score=0.0,       # filled by composite.py
        weight_applied=0.0,         # filled by composite.py
        weighted_contribution=0.0,  # filled by composite.py
        flags=flags,
        reasoning=reasoning,
    )
