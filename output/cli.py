"""
cli.py
======
Command-line output for the Fantasy Football Ranker.

Displays ranked results in a clean table with per-player reasoning.
Supports filtering by position and toggling detailed module breakdowns.

Usage (from main.py):
    from output.cli import print_rankings
    print_rankings(rankings, position="RB", show_detail=True)
"""

from __future__ import annotations
from engine.schema import PlayerRanking

# ANSI color codes — gracefully degraded if terminal doesn't support them
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
WHITE  = "\033[97m"

FLAG_COLORS = {
    "rising":              GREEN,
    "favorable_schedule":  GREEN,
    "declining":           RED,
    "injury_risk_high":    RED,
    "aggression_high":     RED,
    "bad_team":            RED,
    "tough_schedule":      RED,
    "boom_bust":           YELLOW,
    "td_regression_risk":  YELLOW,
    "qb_uncertainty":      YELLOW,
    "limited_history":     YELLOW,
}

MODULE_DISPLAY_NAMES = {
    "fantasy_points": "Fantasy pts",
    "trend":          "Trajectory ",
    "injury_risk":    "Injury risk",
    "schedule":       "Schedule   ",
    "context":        "Context    ",
    "consistency":    "Consistency",
}


def _flag_str(flags: list[str]) -> str:
    """Return a colored comma-separated flag string."""
    if not flags:
        return ""
    parts = []
    for f in flags:
        color = FLAG_COLORS.get(f, DIM)
        parts.append(f"{color}{f}{RESET}")
    return "  [" + ", ".join(parts) + "]"


def _bar(score: float, width: int = 12) -> str:
    """ASCII progress bar for normalized 0–1 score."""
    filled = round(score * width)
    return "█" * filled + "░" * (width - filled)


def print_rankings(
    rankings: list[PlayerRanking],
    position: str | None = None,
    show_detail: bool = False,
    show_reasoning: bool = True,
    top_n: int | None = None,
) -> None:
    """
    Print the ranking table to stdout.

    Parameters
    ----------
    rankings:
        Sorted list of PlayerRanking objects (output of composite.py).
    position:
        If set, filter to only this position (e.g. "RB").
    show_detail:
        If True, print per-module score bars under each player.
    show_reasoning:
        If True, print the reasoning bullets under each player.
    top_n:
        If set, only print the top N players (after position filter).
    """
    filtered = rankings
    if position:
        filtered = [r for r in rankings if r.position == position.upper()]

    if top_n:
        filtered = filtered[:top_n]

    if not filtered:
        print(f"{RED}No players found for filter: position={position}{RESET}")
        return

    pos_label = position.upper() if position else "ALL"
    header = (
        f"\n{BOLD}{WHITE}"
        f"{'OVR':>4}  {'POS':>4}  {'PLAYER':<28}  {'TEAM':<5}  "
        f"{'SCORE':>7}  {'VBD':>7}  FLAGS"
        f"{RESET}"
    )
    divider = "─" * 90

    print(f"\n{BOLD}{CYAN}  ★ Fantasy Football Ranker — {pos_label} Rankings{RESET}")
    print(divider)
    print(header)
    print(divider)

    for r in filtered:
        pos_rank_label = f"{r.position}{r.position_rank}"
        flag_display = _flag_str(r.flags)
        lh_note = f" {DIM}†{RESET}" if r.limited_history else "  "

        row = (
            f"{BOLD}{r.overall_rank:>4}{RESET}  "
            f"{CYAN}{pos_rank_label:>4}{RESET}  "
            f"{r.full_name:<28}  "
            f"{r.nfl_team:<5}  "
            f"{r.composite_score:>7.3f}  "
            f"{r.vbd_score:>+7.3f}"
            f"{lh_note}"
            f"{flag_display}"
        )
        print(row)

        # Per-module score bars
        if show_detail and r.module_scores:
            for ms in sorted(r.module_scores, key=lambda m: m.weighted_contribution, reverse=True):
                label = MODULE_DISPLAY_NAMES.get(ms.module_name, ms.module_name)
                bar = _bar(ms.normalized_score)
                contrib = ms.weighted_contribution
                print(
                    f"          {DIM}{label}{RESET}  "
                    f"{bar}  "
                    f"{ms.normalized_score:.2f}  "
                    f"(contributes {contrib:.3f})"
                )

        # Reasoning bullets
        if show_reasoning and r.reasoning:
            for bullet in r.reasoning:
                print(f"          {DIM}• {bullet}{RESET}")
            print()

    print(divider)
    if any(r.limited_history for r in filtered):
        print(f"  {DIM}† Limited history — fewer than 3 seasons of data{RESET}")
    print()


def print_player_profile(ranking: PlayerRanking) -> None:
    """Print a full drill-down profile for a single player."""
    r = ranking
    print(f"\n{BOLD}{WHITE}{'─'*60}")
    print(f"  {r.full_name}  |  {r.position}  |  {r.nfl_team}")
    print(f"  Overall #{r.overall_rank}  |  {r.position}#{r.position_rank}")
    print(f"  VBD: {r.vbd_score:+.3f}  |  Composite: {r.composite_score:.3f}")
    print(f"{'─'*60}{RESET}")

    print(f"\n{BOLD}Module scores:{RESET}")
    for ms in sorted(r.module_scores, key=lambda m: m.weighted_contribution, reverse=True):
        label = MODULE_DISPLAY_NAMES.get(ms.module_name, ms.module_name)
        bar = _bar(ms.normalized_score)
        print(f"  {label}  {bar}  {ms.normalized_score:.2f}  (×{ms.weight_applied:.2f} = {ms.weighted_contribution:.3f})")
        for bullet in ms.reasoning:
            print(f"    {DIM}• {bullet}{RESET}")

    if r.flags:
        print(f"\n{BOLD}Flags:{RESET}")
        for f in r.flags:
            color = FLAG_COLORS.get(f, DIM)
            print(f"  {color}▸ {f}{RESET}")

    print(f"\n{BOLD}Summary:{RESET}")
    for bullet in r.reasoning:
        print(f"  • {bullet}")
    print()
