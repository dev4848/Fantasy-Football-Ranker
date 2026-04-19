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
      - Surface all flags with context-appropriate sentences.
      - Close with a confidence note if history is limited.

    The goal is 3–6 concise bullets that a drafter can read in 10 seconds.
    """
    bullets: list[str] = []

    # Sort modules by their weighted contribution (highest first)
    ranked_modules = sorted(
        module_scores, key=lambda m: m.weighted_contribution, reverse=True
    )

    # Top 2 modules
    for ms in ranked_modules[:2]:
        if ms.reasoning:
            bullets.append(ms.reasoning[0])   # first bullet from each module

    # Collect all flags across modules
    all_flags = {flag for ms in module_scores for flag in ms.flags}

    # Flag-specific sentences
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
            f"Limited data ({player.years_in_league} NFL season(s)) — projection confidence is moderate.",
        "qb_uncertainty":
            "Team has a new or unproven starting QB — pass-catcher upside may be capped.",
        "bad_team":
            "Playing on a team projected for few wins — volume may suffer.",
        "favorable_schedule":
            "Favorable schedule — faces soft defenses at key position in projected weeks.",
        "tough_schedule":
            "Difficult schedule — faces tough defenses at their position most weeks.",
    }

    for flag in sorted(all_flags):   # sorted for deterministic output
        if flag in flag_sentences and flag_sentences[flag] not in bullets:
            bullets.append(flag_sentences[flag])

    # Confidence note for limited-history players
    if player.limited_history and "limited_history" not in all_flags:
        bullets.append(
            f"Only {player.years_in_league} season(s) of NFL data — "
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

    module_names = list(raw_weights.keys())
    positions_in_use = list({p["position"] for p in players})

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
            normalized[module_name].update(norm)

    # Step 2 — Apply weights, build module_scores list per player
    player_composites: dict[str, float] = {}
    final_module_scores: dict[str, list[ModuleScore]] = {}

    for player in players:
        pid = player["player_id"]
        updated_modules = []
        composite = 0.0

        for ms in position_module_scores.get(pid, []):
            norm_score = normalized.get(ms.module_name, {}).get(pid, 0.0)
            w = weights.get(ms.module_name, 0.0)
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
