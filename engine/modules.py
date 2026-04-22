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
        "pass_yards_per_point": 25, "pass_td": 4, "pass_int": -2, "pass_2pt": 2,
        "rush_yards_per_point": 10, "rush_td": 6, "rush_2pt": 2,
        "reception": 0, "recv_yards_per_point": 10, "recv_td": 6, "recv_2pt": 2,
        "fumble_lost": -2, "fumble_recovery_td": 6,
    },
    "half_ppr": {
        "pass_yards_per_point": 25, "pass_td": 4, "pass_int": -2, "pass_2pt": 2,
        "rush_yards_per_point": 10, "rush_td": 6, "rush_2pt": 2,
        "reception": 0.5, "recv_yards_per_point": 10, "recv_td": 6, "recv_2pt": 2,
        "fumble_lost": -2, "fumble_recovery_td": 6,
    },
    "ppr": {
        "pass_yards_per_point": 25, "pass_td": 4, "pass_int": -2, "pass_2pt": 2,
        "rush_yards_per_point": 10, "rush_td": 6, "rush_2pt": 2,
        "reception": 1.0, "recv_yards_per_point": 10, "recv_td": 6, "recv_2pt": 2,
        "fumble_lost": -2, "fumble_recovery_td": 6,
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
    pts += (stats.get("interceptions") or 0) * rules.get("pass_int", -1)  # league uses -1

    # Rushing
    pts += (stats.get("rush_yards") or 0) / rules.get("rush_yards_per_point", 10)
    pts += (stats.get("rush_tds") or 0) * rules.get("rush_td", 6)

    # Receiving — full PPR
    pts += (stats.get("receptions") or 0) * rules.get("reception", 1.0)
    pts += (stats.get("recv_yards") or 0) / rules.get("recv_yards_per_point", 10)
    pts += (stats.get("recv_tds") or 0) * rules.get("recv_td", 6)

    # Fumbles
    pts += (stats.get("rush_fumbles_lost") or 0) * rules.get("fumble_lost", -2)
    pts += (stats.get("recv_fumbles_lost") or 0) * rules.get("fumble_lost", -2)
    pts += (stats.get("fumble_recovery_tds") or 0) * rules.get("fumble_recovery_td", 6)

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
        n = len(seasons)
        rw_idx = n - 1 - i   # align: newest season (i=n-1) → recency_weights[0]
        base_weight = recency_weights[rw_idx] if rw_idx < len(recency_weights) else 0.1
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

    flags: list[str] = []

    reasoning = [
        f"Weighted avg: {wmean:.1f} fantasy pts/game over {len(seasons)} season(s).",
        "Season breakdown: " + " | ".join(season_summaries),
    ]

    return ModuleScore(
        player_id=player_id, season_evaluated=upcoming_season,
        module_name="fantasy_points", raw_score=wmean, normalized_score=0.0,
        weight_applied=0.0, weighted_contribution=0.0,
        flags=flags, reasoning=reasoning,
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

    # Minimum 8 individual games for meaningful consistency scoring
    if len(per_game_scores) < 8:
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

    # Threshold recalibrated for game-level data (not season averages).
    # Individual games naturally vary more than season means — a CV of 0.65+
    # across 60+ games indicates genuinely unreliable weekly output.
    if cv >= 0.65:
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
    team_context: dict,
    config: dict,
    upcoming_season: int,
    player_age: int | None = None,
    recent_target_share: float | None = None,
    recent_snap_pct: float | None = None,
    snap_pct_delta: float | None = None,
    avg_games_per_season: float | None = None,
    num_seasons: int = 0,
    recent_air_yards_share: float | None = None,
    recent_touch_share: float | None = None,
    recent_ypc: float | None = None,
    recent_ypt: float | None = None,
) -> ModuleScore:
    """
    Combines O-line grade, team win projection, QB situation, player age,
    target share, snap participation, and offensive dominance signals into a
    single context modifier (0.0–1.0 scale).

    Dominance signals added to improve top-6 accuracy:
      - Air yards market share (WR): differentiates WR1 from WR2
      - Touch share (RB): workhorse vs committee usage
      - YPC efficiency (RB): yards per carry
      - Y/TGT efficiency (WR/TE): yards per target
    """
    ctx_cfg = config.get("context", {})
    age_cfg = config.get("age_curve", {})
    ts_cfg  = config.get("target_share", {})
    dom_cfg = config.get("dominance_signals", {})
    flags: list[str] = []
    reasoning: list[str] = []
    components: list[float] = []
    multiplier = 1.0  # all penalties/bonuses accumulate here; applied to base at end

    # --- O-line ---
    if position in ("RB",):
        grade = team_context.get("oline_run_block_grade") or team_context.get("oline_pff_grade")
    else:
        grade = team_context.get("oline_pass_block_grade") or team_context.get("oline_pff_grade")

    if grade is not None:
        oline_norm = grade / 100.0
        components.append(oline_norm)
        label = "elite" if grade >= 75 else "solid" if grade >= 60 else "average" if grade >= 50 else "poor"
        reasoning.append(f"O-line grade: {grade:.0f}/100 ({label}) for {position} play.")
    else:
        components.append(0.5)

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
            components.append(0.70)

    # --- Base score from structural components ---
    base_score = sum(components) / len(components) if components else 0.5

    # --- Age-based decline multiplier ---
    if player_age is not None:
        age_penalty = 0.0
        if position == "RB":
            mild     = age_cfg.get("rb_mild_age", 28)
            moderate = age_cfg.get("rb_moderate_age", 30)
            heavy    = moderate + 2
        elif position in ("WR", "TE"):
            mild     = age_cfg.get("wr_mild_age", 30)
            moderate = age_cfg.get("wr_moderate_age", 32)
            heavy    = moderate + 2
        elif position == "QB":
            mild     = age_cfg.get("qb_mild_age", 36)
            moderate = age_cfg.get("qb_moderate_age", 39)
            heavy    = moderate + 2
        else:
            mild = moderate = heavy = 99

        mild_p     = age_cfg.get("mild_penalty",     0.08)
        moderate_p = age_cfg.get("moderate_penalty", 0.18)
        heavy_p    = age_cfg.get("heavy_penalty",    0.30)

        if player_age >= heavy:
            age_penalty = heavy_p
            flags.append("age_decline")
            reasoning.append(
                f"Age {player_age} — significant decline risk for {position} at this stage of career."
            )
        elif player_age >= moderate:
            age_penalty = moderate_p
            flags.append("age_decline")
            reasoning.append(
                f"Age {player_age} — entering prime decline window for {position}; production may dip."
            )
        elif player_age >= mild:
            age_penalty = mild_p
            reasoning.append(
                f"Age {player_age} — approaching typical {position} decline age; mild projection discount."
            )

        if age_penalty > 0:
            multiplier *= (1.0 - age_penalty)

    # --- Recent target share floor (WR / TE only) ---
    if position in ("WR", "TE") and recent_target_share is not None:
        if position == "WR":
            floor = ts_cfg.get("wr_meaningful_share", 0.12)
        else:
            floor = ts_cfg.get("te_meaningful_share", 0.10)
        ts_penalty_max = ts_cfg.get("low_share_penalty", 0.20)

        if recent_target_share < floor:
            severity = 1.0 - (recent_target_share / floor)
            ts_penalty = ts_penalty_max * severity
            flags.append("low_target_share")
            reasoning.append(
                f"Target share last season: {recent_target_share:.1%} — "
                f"below the {floor:.0%} meaningful-role threshold; role may have diminished."
            )
            multiplier *= (1.0 - ts_penalty)

    # --- Snap participation (WR only) ---
    if position == "WR" and recent_snap_pct is not None:
        snap_cfg = config.get("snap_participation", {})
        starter_threshold = snap_cfg.get("wr_starter_snap_pct", 0.75)
        backup_threshold  = snap_cfg.get("wr_backup_snap_pct", 0.50)
        expanding_delta   = snap_cfg.get("role_expanding_delta", 0.08)
        starter_bonus     = snap_cfg.get("starter_bonus", 0.08)
        backup_penalty    = snap_cfg.get("backup_penalty", 0.12)

        if recent_snap_pct >= starter_threshold:
            multiplier *= (1.0 + starter_bonus)
            if snap_pct_delta is not None and snap_pct_delta >= expanding_delta:
                flags.append("role_expanding")
                reasoning.append(
                    f"Snap share {recent_snap_pct:.0%} and rising (+{snap_pct_delta:.0%} YoY) "
                    "— expanding role in the offense."
                )
            else:
                reasoning.append(
                    f"High snap share ({recent_snap_pct:.0%}) confirms starter-level role."
                )
        elif snap_pct_delta is not None and snap_pct_delta >= expanding_delta:
            flags.append("role_expanding")
            multiplier *= (1.0 + starter_bonus * 0.5)
            reasoning.append(
                f"Snap share rising ({snap_pct_delta:+.0%} YoY to {recent_snap_pct:.0%}) "
                "— role expanding, watch for continued growth."
            )
        elif recent_snap_pct < backup_threshold:
            multiplier *= (1.0 - backup_penalty)
            flags.append("limited_role")
            reasoning.append(
                f"Limited snap share ({recent_snap_pct:.0%}) — role in offense is restricted."
            )

    # --- Air yards market share (WR) ---
    # Differentiates true WR1s from volume WR2s; top-6 WRs typically own 25%+ AYMS.
    if position == "WR" and recent_air_yards_share is not None:
        ayms_elite = dom_cfg.get("wr_ayms_elite", 0.25)
        ayms_solid = dom_cfg.get("wr_ayms_solid", 0.18)
        ayms_low   = dom_cfg.get("wr_ayms_low",   0.12)
        if recent_air_yards_share >= ayms_elite:
            multiplier *= 1.15
            flags.append("ayms_elite")
            reasoning.append(
                f"Air yards share {recent_air_yards_share:.1%} — dominates team's deep passing game."
            )
        elif recent_air_yards_share >= ayms_solid:
            multiplier *= 1.07
        elif recent_air_yards_share < ayms_low:
            multiplier *= 0.92
            reasoning.append(
                f"Low air yards share ({recent_air_yards_share:.1%}) — limited role in downfield passing."
            )

    # --- Touch dominance (RB) ---
    # True top-6 RBs are the clear workhorse; committee backs rarely crack top-6.
    if position == "RB" and recent_touch_share is not None:
        rb_workhorse = dom_cfg.get("rb_workhorse_touch_share", 0.28)
        rb_featured  = dom_cfg.get("rb_featured_touch_share",  0.20)
        rb_committee = dom_cfg.get("rb_committee_touch_share", 0.14)
        if recent_touch_share >= rb_workhorse:
            multiplier *= 1.15
            flags.append("workhorse")
            reasoning.append(
                f"Touch share {recent_touch_share:.1%} — workhorse usage in team's offense."
            )
        elif recent_touch_share >= rb_featured:
            multiplier *= 1.06
        elif recent_touch_share < rb_committee:
            multiplier *= 0.88
            flags.append("committee_back")
            reasoning.append(
                f"Low touch share ({recent_touch_share:.1%}) — likely in a committee role."
            )

    # --- Per-carry efficiency (RB) ---
    if position == "RB" and recent_ypc is not None:
        ypc_elite = dom_cfg.get("rb_ypc_elite", 5.0)
        ypc_solid = dom_cfg.get("rb_ypc_solid", 4.5)
        ypc_poor  = dom_cfg.get("rb_ypc_poor",  3.5)
        if recent_ypc >= ypc_elite:
            multiplier *= 1.08
            reasoning.append(f"Elite YPC ({recent_ypc:.1f}) — efficient runner even in heavy workload.")
        elif recent_ypc >= ypc_solid:
            multiplier *= 1.04
        elif recent_ypc < ypc_poor:
            multiplier *= 0.95

    # --- Yards-per-target efficiency (WR only) ---
    # High Y/TGT for TE reflects deep-threat role, not fantasy production dominance —
    # elite TEs (Kelce, Andrews) have moderate Y/TGT from heavy slot usage.
    if position == "WR" and recent_ypt is not None:
        ypt_elite = dom_cfg.get("wr_ypt_elite", 10.0)
        ypt_solid = dom_cfg.get("wr_ypt_solid",  8.5)
        ypt_poor  = dom_cfg.get("wr_ypt_poor",   6.0)
        if recent_ypt >= ypt_elite:
            multiplier *= 1.08
            reasoning.append(f"Elite yards-per-target ({recent_ypt:.1f}) — high-value receiver.")
        elif recent_ypt >= ypt_solid:
            multiplier *= 1.04
        elif recent_ypt < ypt_poor:
            multiplier *= 0.95

    raw_score = base_score * multiplier

    # --- QB starter-volume filter ---
    # Only applied when we have 2+ seasons so legitimate new starters aren't penalized.
    if position == "QB" and avg_games_per_season is not None and num_seasons >= 2:
        qb_min_games = ctx_cfg.get("qb_starter_min_avg_games", 12)
        qb_max_penalty = ctx_cfg.get("qb_starter_penalty", 0.25)
        if avg_games_per_season < qb_min_games:
            severity = 1.0 - (avg_games_per_season / qb_min_games)
            qb_penalty = qb_max_penalty * severity
            flags.append("fringe_starter")
            reasoning.append(
                f"Avg {avg_games_per_season:.1f} games/season — fringe starter risk; "
                "projection assumes starting role not guaranteed."
            )
            raw_score *= (1.0 - qb_penalty)

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