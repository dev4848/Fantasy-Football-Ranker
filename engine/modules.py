"""
fantasy_points.py
=================
Module 1 — Historical fantasy point production.

Applies the user's scoring rules to raw stat lines and produces
a weighted per-game average as the module's raw_score.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from engine.schema import ModuleScore


SCORING_PRESETS = {
    "standard": {
        "pass_yards_per_point": 25, "pass_td": 4, "pass_int": -2,
        "rush_yards_per_point": 10, "rush_td": 6,
        "reception": 0, "recv_yards_per_point": 10, "recv_td": 6,
        "fumble_lost": -2, "return_td": 6,
    },
    "half_ppr": {
        "pass_yards_per_point": 25, "pass_td": 4, "pass_int": -2,
        "rush_yards_per_point": 10, "rush_td": 6,
        "reception": 0.5, "recv_yards_per_point": 10, "recv_td": 6,
        "fumble_lost": -2, "return_td": 6,
    },
    "ppr": {
        "pass_yards_per_point": 25, "pass_td": 4, "pass_int": -2,
        "rush_yards_per_point": 10, "rush_td": 6,
        "reception": 1.0, "recv_yards_per_point": 10, "recv_td": 6,
        "fumble_lost": -2, "return_td": 6,
    },
}


def resolve_scoring_rules(config: dict) -> dict:
    """Return the scoring rule dict, resolving preset name if set."""
    scoring = config.get("scoring", {})
    preset_name = scoring.get("preset", "").strip()
    if preset_name and preset_name in SCORING_PRESETS:
        return SCORING_PRESETS[preset_name]
    return scoring.get("custom", SCORING_PRESETS["half_ppr"])


def calc_season_fantasy_points(stats: dict, rules: dict) -> float:
    """
    Apply scoring rules to a single season's stat dict.
    stat keys match SeasonStats field names.
    Returns total fantasy points for the season.
    """
    pts = 0.0

    # Passing
    pts += (stats.get("pass_yards") or 0) / rules.get("pass_yards_per_point", 25)
    pts += (stats.get("pass_tds") or 0) * rules.get("pass_td", 4)
    pts += (stats.get("interceptions") or 0) * rules.get("pass_int", -2)

    # Rushing
    pts += (stats.get("rush_yards") or 0) / rules.get("rush_yards_per_point", 10)
    pts += (stats.get("rush_tds") or 0) * rules.get("rush_td", 6)

    # Receiving
    pts += (stats.get("receptions") or 0) * rules.get("reception", 0.5)
    pts += (stats.get("recv_yards") or 0) / rules.get("recv_yards_per_point", 10)
    pts += (stats.get("recv_tds") or 0) * rules.get("recv_td", 6)

    # Misc
    fumbles = (stats.get("rush_fumbles_lost") or 0) + (stats.get("recv_fumbles_lost") or 0)
    pts += fumbles * rules.get("fumble_lost", -2)
    pts += (stats.get("return_tds") or 0) * rules.get("return_td", 6)

    return pts


def score_fantasy_points(
    player_id: str,
    seasons: list[dict],           # list of SeasonStats as dicts, oldest→newest
    recency_weights: list[float],  # normalized effective weights
    rules: dict,
    min_games: int,
    upcoming_season: int,
) -> ModuleScore:
    """
    Compute the fantasy points module score.

    raw_score = weighted average of per-game fantasy points across seasons.
    """
    if not seasons:
        return ModuleScore(
            player_id=player_id, season_evaluated=upcoming_season,
            module_name="fantasy_points", raw_score=0.0, normalized_score=0.0,
            weight_applied=0.0, weighted_contribution=0.0,
            flags=["no_data"], reasoning=["No stat history available."],
        )

    per_game_pts = []
    effective_weights = []
    season_summaries = []

    for i, season in enumerate(seasons):
        gp = max(season.get("games_played", 0), 1)
        games_factor = min(gp / min_games, 1.0)
        base_weight = recency_weights[i] if i < len(recency_weights) else 0.1
        eff_w = base_weight * games_factor

        total_pts = calc_season_fantasy_points(season, rules)
        pg = total_pts / gp

        per_game_pts.append(pg)
        effective_weights.append(eff_w)
        season_summaries.append(
            f"{season['season']}: {pg:.1f} pts/gm ({gp} games)"
        )

    total_w = sum(effective_weights)
    wmean = (
        sum(v * w for v, w in zip(per_game_pts, effective_weights)) / total_w
        if total_w > 0 else 0.0
    )

    reasoning = [
        f"Weighted avg: {wmean:.1f} fantasy pts/game over {len(seasons)} season(s).",
        "Season breakdown: " + " | ".join(season_summaries),
    ]

    return ModuleScore(
        player_id=player_id, season_evaluated=upcoming_season,
        module_name="fantasy_points", raw_score=wmean, normalized_score=0.0,
        weight_applied=0.0, weighted_contribution=0.0,
        flags=[], reasoning=reasoning,
    )


# =============================================================

"""
consistency.py — Module 6
Measures reliability: how tightly clustered a player's per-game output
is (low CV = consistent floor). Also computes floor/ceiling stats.
"""


def score_consistency(
    player_id: str,
    per_game_scores: list[float],   # all individual game fantasy scores
    upcoming_season: int,
) -> ModuleScore:
    """
    raw_score = 1 / (1 + CV)  — higher is more consistent.

    Also surfaces floor (10th percentile) and ceiling (90th percentile).
    """
    import statistics

    flags: list[str] = []
    reasoning: list[str] = []

    if len(per_game_scores) < 4:
        return ModuleScore(
            player_id=player_id, season_evaluated=upcoming_season,
            module_name="consistency", raw_score=0.5, normalized_score=0.0,
            weight_applied=0.0, weighted_contribution=0.0,
            flags=["limited_game_sample"],
            reasoning=["Insufficient game-level data for consistency scoring."],
        )

    mean = statistics.mean(per_game_scores)
    std = statistics.pstdev(per_game_scores)
    cv = std / mean if mean > 0 else 0.0

    # Floor / ceiling (approximate percentiles without scipy)
    sorted_scores = sorted(per_game_scores)
    n = len(sorted_scores)
    floor = sorted_scores[max(0, int(n * 0.10))]
    ceiling = sorted_scores[min(n - 1, int(n * 0.90))]

    # Consistency score: inverse of CV, scaled to 0–1 range
    # CV of 0 → 1.0, CV of 1.0 → 0.5, CV of 2.0+ → ~0.33
    raw_score = 1.0 / (1.0 + cv)

    if cv >= 0.45:
        flags.append("boom_bust")

    reasoning.append(
        f"Consistency score: {raw_score:.2f} (CV={cv:.2f}) — "
        f"floor {floor:.1f}, ceiling {ceiling:.1f} pts/game."
    )
    if "boom_bust" in flags:
        reasoning.append(
            "Wide score variance — weekly start/sit decisions matter more for this player."
        )
    else:
        reasoning.append(
            "Reliable weekly output — low variance makes this a safer floor play."
        )

    return ModuleScore(
        player_id=player_id, season_evaluated=upcoming_season,
        module_name="consistency", raw_score=raw_score, normalized_score=0.0,
        weight_applied=0.0, weighted_contribution=0.0,
        flags=flags, reasoning=reasoning,
    )


# =============================================================

"""
context.py — Module 5
O-line quality, team win projection, QB situation.
"""


def score_context(
    player_id: str,
    position: str,
    team_context: dict,         # TeamContext as dict for upcoming season
    config: dict,
    upcoming_season: int,
) -> ModuleScore:
    """
    Combines O-line grade, team win projection, and QB situation
    into a single context modifier (0.0–1.0 scale).
    """
    ctx_cfg = config.get("context", {})
    flags: list[str] = []
    reasoning: list[str] = []
    components: list[float] = []

    # --- O-line ---
    if position in ("RB",):
        grade = team_context.get("oline_run_block_grade") or team_context.get("oline_pff_grade")
    else:
        grade = team_context.get("oline_pass_block_grade") or team_context.get("oline_pff_grade")

    if grade is not None:
        # PFF grades 0–100; normalize to 0–1
        oline_norm = grade / 100.0
        components.append(oline_norm)
        label = "elite" if grade >= 75 else "solid" if grade >= 60 else "average" if grade >= 50 else "poor"
        reasoning.append(f"O-line grade: {grade:.0f}/100 ({label}) for {position} play.")
    else:
        components.append(0.5)   # neutral if unavailable

    # --- Team win projection ---
    proj_wins = team_context.get("projected_wins")
    bad_team_threshold = ctx_cfg.get("bad_team_threshold_wins", 5)
    if proj_wins is not None:
        win_norm = min(proj_wins / 17.0, 1.0)
        components.append(win_norm)
        if proj_wins <= bad_team_threshold:
            flags.append("bad_team")
            reasoning.append(
                f"Team projected for {proj_wins:.0f} wins — low win total "
                "limits volume and game-script opportunities."
            )
        else:
            reasoning.append(f"Team projected for {proj_wins:.0f} wins — healthy team context.")
    else:
        components.append(0.5)

    # --- QB situation (WR / TE only) ---
    if position in ("WR", "TE"):
        qb_new = team_context.get("qb_is_new", False)
        qb_starts = team_context.get("qb_years_of_starts", 99)

        if qb_new and qb_starts < 1:
            flags.append("qb_uncertainty")
            components.append(0.25)
            reasoning.append(
                "New starting QB with no prior NFL starts — pass-catcher production is harder to project."
            )
        elif qb_new:
            flags.append("qb_uncertainty")
            components.append(0.40)
            reasoning.append(
                f"New starting QB ({qb_starts} prior year(s) of starts) — "
                "some adjustment period expected."
            )
        else:
            components.append(0.70)   # incumbent QB = stable baseline

    raw_score = sum(components) / len(components) if components else 0.5

    return ModuleScore(
        player_id=player_id, season_evaluated=upcoming_season,
        module_name="context", raw_score=raw_score, normalized_score=0.0,
        weight_applied=0.0, weighted_contribution=0.0,
        flags=flags, reasoning=reasoning,
    )


# =============================================================

"""
schedule.py — Module 4
Strength of schedule based on opponents' historical points allowed
vs the player's position.
"""


def score_schedule(
    player_id: str,
    position: str,
    schedule_entries: list[dict],   # list of ScheduleEntry dicts
    config: dict,
    upcoming_season: int,
) -> ModuleScore:
    """
    raw_score = average pts-allowed-vs-position across evaluated weeks.
    Higher = easier schedule (opponent allows more pts to that position).
    """
    flags: list[str] = []
    reasoning: list[str] = []
    sched_cfg = config.get("schedule", {})
    eval_weeks = set(sched_cfg.get("evaluate_weeks", range(1, 15)))
    pts_key = f"opp_pts_allowed_vs_{position.lower()}"

    relevant = [
        e for e in schedule_entries
        if not e.get("is_bye") and e.get("week") in eval_weeks
    ]

    if not relevant:
        return ModuleScore(
            player_id=player_id, season_evaluated=upcoming_season,
            module_name="schedule", raw_score=0.5, normalized_score=0.0,
            weight_applied=0.0, weighted_contribution=0.0,
            flags=["no_schedule_data"],
            reasoning=["Schedule data unavailable."],
        )

    scores = [e.get(pts_key) for e in relevant if e.get(pts_key) is not None]

    if not scores:
        return ModuleScore(
            player_id=player_id, season_evaluated=upcoming_season,
            module_name="schedule", raw_score=0.5, normalized_score=0.0,
            weight_applied=0.0, weighted_contribution=0.0,
            flags=[], reasoning=["Opponent position data unavailable."],
        )

    avg_pts_allowed = sum(scores) / len(scores)

    reasoning.append(
        f"Opponents allow avg {avg_pts_allowed:.1f} pts/game vs {position} "
        f"over {len(scores)} evaluated weeks."
    )

    # Flags are applied post-normalization in composite.py
    # (needs population context to know if this is top/bottom third)

    return ModuleScore(
        player_id=player_id, season_evaluated=upcoming_season,
        module_name="schedule", raw_score=avg_pts_allowed, normalized_score=0.0,
        weight_applied=0.0, weighted_contribution=0.0,
        flags=flags, reasoning=reasoning,
    )
