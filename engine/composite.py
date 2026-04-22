"""
composite.py
============
Weighted aggregator that combines all six module scores into a single
composite player value, computes VBD (value over replacement), and
generates the human-readable reasoning bullets for each player.

Flow:
    raw module scores (0–∞, position-relative)
        → per-module normalization to 0.0–1.0 against position peers
        → multiply by config weights (auto-normalized to sum to 1.0)
        → sum to composite score
        → VBD adjustment (subtract positional baseline)
        → rank within position and overall
        → reasoning generation
"""

from __future__ import annotations
import statistics
from typing import Sequence
from engine.schema import ModuleScore, PlayerRanking


# ==============================================================
# Replacement baselines
# In a 12-team league, "replacement level" is roughly the last
# starter at each position. Adjust these for league size.
# E.g. 12 teams × 2 RBs = top 24 RBs are starters; RB25 = baseline.
# These are dynamically recomputed from the actual ranked pool
# in rank_all_players(), but the dict below serves as the fallback
# if there are fewer players than expected.
# ==============================================================
DEFAULT_REPLACEMENT_RANKS = {
    "QB":  13,   # 12 teams, 1 QB each
    "RB":  25,   # 12 teams, ~2 RBs each + FLEX
    "WR":  37,   # 12 teams, ~3 WRs each + FLEX
    "TE":  13,   # 12 teams, 1 TE each
}


def normalize_scores(
    module_name: str,
    scores: dict[str, float],   # {player_id: raw_score}
) -> dict[str, float]:
    """
    Min-max normalize a dict of raw module scores to [0.0, 1.0].
    Players at the max get 1.0; at the min get 0.0.
    Handles edge case where all scores are equal (returns 0.5 for all).
    """
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi == lo:
        return {pid: 0.5 for pid in scores}
    return {pid: (v - lo) / (hi - lo) for pid, v in scores.items()}


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Ensure module weights sum to exactly 1.0."""
    total = sum(weights.values())
    if total == 0:
        raise ValueError("All module weights are zero.")
    return {k: v / total for k, v in weights.items()}


def compute_composite(
    player_id: str,
    module_scores: list[ModuleScore],
) -> float:
    """Sum weighted contributions from all modules."""
    return sum(ms.weighted_contribution for ms in module_scores)


def compute_vbd(
    player_id: str,
    composite_score: float,
    position: str,
    all_players_by_position: dict[str, list[tuple[str, float]]],
    replacement_ranks: dict[str, int],
) -> float:
    """
    Value over baseline: composite score minus the composite score of
    the replacement-level player at that position.

    Returns a positive float (elite players score much higher than
    baseline) or negative (below-replacement players).
    """
    peers = all_players_by_position.get(position, [])
    # peers is already sorted descending by composite score
    baseline_rank = replacement_ranks.get(position, 13)
    if len(peers) >= baseline_rank:
        baseline_score = peers[baseline_rank - 1][1]
    elif peers:
        baseline_score = peers[-1][1]   # last available if pool is thin
    else:
        baseline_score = 0.0
    return composite_score - baseline_score


def generate_reasoning(
    player: PlayerRanking,
    module_scores: list[ModuleScore],
) -> list[str]:
    """
    Build the plain-English reasoning list shown in CLI and exports.

    Strategy:
      - Lead with the top 2 contributing modules (highest weighted_contribution).
      - Surface remaining flags whose source module wasn't already in the top 2
        (prevents semantic duplicates where module reasoning and flag sentence
        say the same thing in different words).
      - Close with a confidence note if history is limited.

    The goal is 3–6 concise bullets that a drafter can read in 10 seconds.
    """
    bullets: list[str] = []
    seen: set[str] = set()   # exact-match dedup guard

    def _add(text: str) -> None:
        if text and text not in seen:
            bullets.append(text)
            seen.add(text)

    # Sort modules by their weighted contribution (highest first)
    ranked_modules = sorted(
        module_scores, key=lambda m: m.weighted_contribution, reverse=True
    )

    # Top 2 modules — add first reasoning bullet from each
    top_module_names: set[str] = set()
    for ms in ranked_modules[:2]:
        if ms.reasoning:
            _add(ms.reasoning[0])
            top_module_names.add(ms.module_name)

    # Collect all flags across modules
    all_flags = {flag for ms in module_scores for flag in ms.flags}

    # Flag → source module mapping — used to skip flags whose module is already
    # represented in the top-2 (avoids saying the same thing twice in different words)
    flag_source = {
        "rising":             "trend",
        "declining":          "trend",
        "boom_bust":          "trend",
        "td_regression_risk": "trend",
        "injury_risk_high":   "injury_risk",
        "aggression_high":    "injury_risk",
        "bad_team":           "context",
        "qb_uncertainty":     "context",
        "age_decline":        "context",
        "low_target_share":   "context",
        "role_expanding":     "context",
        "limited_role":       "context",
        "fringe_starter":     "context",
        "ayms_elite":         "context",
        "workhorse":          "context",
        "committee_back":     "context",
        "favorable_schedule": "schedule",
        "tough_schedule":     "schedule",
    }

    flag_sentences = {
        "rising":
            "Trajectory is trending upward — last season significantly above career mean.",
        "declining":
            "Production is trending downward — last season below career average.",
        "boom_bust":
            "High variance player — ceiling is elite but floor is inconsistent.",
        "injury_risk_high":
            "Elevated injury risk — averaged 5+ games missed per season in career.",
        "aggression_high":
            "High-contact playing style increases injury risk; monitor closely.",
        "td_regression_risk":
            "Last season's TD rate was unusually high; some regression expected.",
        "limited_history":
            f"Limited data ({player.years_in_league + 1} NFL season(s)) — projection confidence is moderate.",
        "qb_uncertainty":
            "Team has a new or unproven starting QB — pass-catcher upside may be capped.",
        "bad_team":
            "Playing on a team projected for few wins — volume may suffer.",
        "favorable_schedule":
            "Favorable schedule — faces soft defenses at key position in projected weeks.",
        "tough_schedule":
            "Difficult schedule — faces tough defenses at their position most weeks.",
        "age_decline":
            f"Age-related decline risk — {player.position} production often drops at this stage.",
        "low_target_share":
            "Target share was low last season — role may have diminished in the offense.",
        "role_expanding":
            "Snap share trending up — expanding role suggests more opportunity ahead.",
        "limited_role":
            "Below-average snap share last season — role in offense is limited.",
        "fringe_starter":
            "Averaged below starter-level games per season — not a guaranteed Week 1 starter.",
        "ayms_elite":
            "Dominant air yards share — the clear WR1 target in the passing game.",
        "workhorse":
            "Workhorse usage — leads team in combined carries and targets.",
        "committee_back":
            "Committee role — low touch share indicates shared backfield workload.",
    }

    for flag in sorted(all_flags):
        if flag not in flag_sentences:
            continue
        # Skip if this flag's source module already contributed a top-2 bullet —
        # that bullet already communicates the signal; repeating it wastes a slot.
        if flag_source.get(flag) in top_module_names:
            continue
        _add(flag_sentences[flag])

    # Confidence note for limited-history players
    if player.limited_history and "limited_history" not in all_flags:
        _add(
            f"Only {player.years_in_league + 1} season(s) of NFL data — "
            "weights normalized to available history."
        )

    return bullets[:6]   # cap at 6 bullets to keep output scannable


def rank_all_players(
    players: list[dict],            # list of player dicts from engine
    position_module_scores: dict,   # {player_id: list[ModuleScore]}
    config: dict,
) -> list[PlayerRanking]:
    """
    Master ranking function. Called once per run after all modules
    have scored every eligible player.

    Steps:
      1. Normalize each module's raw scores across position peers.
      2. Apply config weights and compute per-player composite.
      3. Group by position, sort, compute VBD.
      4. Sort overall by VBD score.
      5. Generate reasoning for each player.
      6. Return sorted list of PlayerRanking objects.
    """
    raw_weights = config["module_weights"]
    weights = normalize_weights(raw_weights)
    pos_weight_overrides = config.get("position_module_weights", {})

    # Pre-compute per-position weight vectors (merges base + overrides, renormalized)
    pos_weights: dict[str, dict[str, float]] = {}
    all_positions = list({p["position"] for p in players})
    for pos in all_positions:
        override = pos_weight_overrides.get(pos, {})
        if override:
            merged = {**raw_weights, **override}
            pos_weights[pos] = normalize_weights(merged)
        else:
            pos_weights[pos] = weights

    module_names = list(raw_weights.keys())
    positions_in_use = all_positions

    # Step 1 — Normalize per module × per position
    # {module_name: {player_id: normalized_score}}
    normalized: dict[str, dict[str, float]] = {}

    for module_name in module_names:
        # Collect raw scores for this module, keyed by player_id
        raw_by_pos: dict[str, dict[str, float]] = {pos: {} for pos in positions_in_use}
        for player in players:
            pid = player["player_id"]
            pos = player["position"]
            for ms in position_module_scores.get(pid, []):
                if ms.module_name == module_name:
                    raw_by_pos[pos][pid] = ms.raw_score

        # Normalize within position
        normalized[module_name] = {}
        for pos in positions_in_use:
            norm = normalize_scores(module_name, raw_by_pos[pos])
            # injury_risk raw_score is a risk level (higher = worse).
            # Invert so low risk players get high contribution.
            if module_name == "injury_risk":
                norm = {pid: 1.0 - v for pid, v in norm.items()}
            normalized[module_name].update(norm)

    # Step 2 — Apply weights, build module_scores list per player
    player_composites: dict[str, float] = {}
    final_module_scores: dict[str, list[ModuleScore]] = {}

    # Pre-compute per-player flag sets (needed for declining+injury discount)
    player_all_flags: dict[str, set[str]] = {
        player["player_id"]: {
            f for ms in position_module_scores.get(player["player_id"], [])
            for f in ms.flags
        }
        for player in players
    }

    declining_injury_cfg  = config.get("declining_injury_discount", {})
    fp_reduction          = declining_injury_cfg.get("fp_reduction", 0.0)

    lh_cfg                = config.get("limited_history_discount", {})
    lh_one_season         = lh_cfg.get("one_season_discount",   0.12)
    lh_two_season         = lh_cfg.get("two_season_discount",   0.06)

    # Build per-player season count from their module_inputs seasons list
    player_season_counts: dict[str, int] = {
        player["player_id"]: len(position_module_scores.get(player["player_id"], []))
        for player in players
    }
    # Season count comes from the seasons list passed to score_fantasy_points —
    # use the fantasy_points module's raw reasoning to infer it, or store it
    # directly from the module score count. We track it via ingestion metadata.
    # Simpler: read num_seasons stored on the player dict (set below from seasons list).

    for player in players:
        pid = player["player_id"]
        pos = player["position"]
        player_weights = pos_weights.get(pos, weights)
        updated_modules = []
        composite = 0.0

        all_flags   = player_all_flags.get(pid, set())
        num_seasons = player.get("num_seasons", 3)   # passed through from ingestion

        # Declining + injury discount
        fp_modifier = 1.0
        if (fp_reduction > 0
                and "declining" in all_flags
                and "injury_risk_high" in all_flags):
            fp_modifier = 1.0 - fp_reduction

        # Limited history discount — fewer seasons = less confidence in the avg.
        # Applied to RB and TE only: both positions show clear sophomore regression.
        # WR development curves are more linear (year-1 WR breakouts sustain), so
        # applying this to WR incorrectly penalises legitimately elite young receivers.
        if pos in ("RB", "TE"):
            if num_seasons == 1:
                fp_modifier *= (1.0 - lh_one_season)
            elif num_seasons == 2:
                fp_modifier *= (1.0 - lh_two_season)

        for ms in position_module_scores.get(pid, []):
            norm_score = normalized.get(ms.module_name, {}).get(pid, 0.0)
            if ms.module_name == "fantasy_points":
                norm_score *= fp_modifier
            w = player_weights.get(ms.module_name, 0.0)
            contribution = norm_score * w
            composite += contribution

            updated_modules.append(ModuleScore(
                player_id=pid,
                season_evaluated=ms.season_evaluated,
                module_name=ms.module_name,
                raw_score=ms.raw_score,
                normalized_score=norm_score,
                weight_applied=w,
                weighted_contribution=contribution,
                flags=ms.flags,
                reasoning=ms.reasoning,
            ))

        player_composites[pid] = composite
        final_module_scores[pid] = updated_modules

    # Step 3 — Group by position, sort, compute VBD
    by_position: dict[str, list[tuple[str, float]]] = {pos: [] for pos in positions_in_use}
    for player in players:
        pid = player["player_id"]
        by_position[player["position"]].append((pid, player_composites[pid]))

    for pos in by_position:
        by_position[pos].sort(key=lambda x: x[1], reverse=True)

    replacement_ranks = config.get(
        "replacement_ranks", DEFAULT_REPLACEMENT_RANKS
    )

    # Step 4 — Build PlayerRanking objects
    rankings: list[PlayerRanking] = []

    for pos in positions_in_use:
        for pos_rank, (pid, composite) in enumerate(by_position[pos], start=1):
            player = next(p for p in players if p["player_id"] == pid)
            vbd = compute_vbd(pid, composite, pos, by_position, replacement_ranks)
            module_scores_for_player = final_module_scores.get(pid, [])

            all_flags = sorted({f for ms in module_scores_for_player for f in ms.flags})

            pr = PlayerRanking(
                player_id=pid,
                full_name=player["full_name"],
                position=pos,
                nfl_team=player["nfl_team"],
                years_in_league=player["years_in_league"],
                limited_history=player.get("limited_history", False),
                composite_score=composite,
                position_rank=pos_rank,
                overall_rank=0,   # filled in step 5
                vbd_score=vbd,
                module_scores=module_scores_for_player,
                flags=all_flags,
                reasoning=[],     # filled after
            )
            pr.reasoning = generate_reasoning(pr, module_scores_for_player)
            rankings.append(pr)

    # Step 5 — Overall rank by VBD
    rankings.sort(key=lambda r: r.vbd_score, reverse=True)
    for overall_rank, ranking in enumerate(rankings, start=1):
        ranking.overall_rank = overall_rank

    return rankings
