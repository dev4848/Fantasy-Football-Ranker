"""
synthetic_players.py
====================
Known-good test profiles used to validate the composite scoring engine.

Before connecting real data, run these through the engine and confirm:
  1. Elite player ranks above Rising player, who ranks above Boom-Bust,
     who ranks above Declining player.
  2. All flags are correctly assigned.
  3. Reasoning bullets are non-empty and sensible.

Each profile is expressed as the raw dicts the engine would receive
from ingestion.py — this lets tests run without any live data fetches.
"""

# ─── Test profile: Elite, consistent veteran ───────────────────────────────
ELITE_RB = {
    "player": {
        "player_id": "test_elite_rb",
        "full_name": "Alex Steady",
        "position": "RB",
        "nfl_team": "KC",
        "years_in_league": 5,
        "limited_history": False,
    },
    "seasons": [
        # oldest → newest
        {"season": 2020, "games_played": 16, "carries": 270, "rush_yards": 1200,
         "rush_tds": 9, "receptions": 55, "recv_yards": 420, "recv_tds": 3,
         "targets": 65, "snap_pct": 0.75, "rush_fumbles_lost": 1, "recv_fumbles_lost": 0,
         "rz_carries": 55, "rz_targets": 12, "rz_tds": 9},
        {"season": 2021, "games_played": 15, "carries": 255, "rush_yards": 1100,
         "rush_tds": 10, "receptions": 58, "recv_yards": 440, "recv_tds": 2,
         "targets": 70, "snap_pct": 0.78, "rush_fumbles_lost": 0, "recv_fumbles_lost": 0,
         "rz_carries": 52, "rz_targets": 14, "rz_tds": 9},
        {"season": 2022, "games_played": 16, "carries": 280, "rush_yards": 1350,
         "rush_tds": 11, "receptions": 62, "recv_yards": 500, "recv_tds": 4,
         "targets": 74, "snap_pct": 0.80, "rush_fumbles_lost": 0, "recv_fumbles_lost": 0,
         "rz_carries": 60, "rz_targets": 15, "rz_tds": 12},
        {"season": 2023, "games_played": 16, "carries": 295, "rush_yards": 1400,
         "rush_tds": 12, "receptions": 68, "recv_yards": 520, "recv_tds": 5,
         "targets": 80, "snap_pct": 0.82, "rush_fumbles_lost": 0, "recv_fumbles_lost": 0,
         "rz_carries": 64, "rz_targets": 18, "rz_tds": 14},
    ],
    # Expected flags: none (or "favorable_schedule" depending on schedule data)
    # Expected position rank: 1–3
}


# ─── Test profile: Rising WR, limited history ──────────────────────────────
RISING_WR = {
    "player": {
        "player_id": "test_rising_wr",
        "full_name": "Jordan Breakout",
        "position": "WR",
        "nfl_team": "SF",
        "years_in_league": 2,
        "limited_history": True,
    },
    "seasons": [
        {"season": 2022, "games_played": 10, "receptions": 38, "recv_yards": 480,
         "recv_tds": 3, "targets": 58, "air_yards": 820.0, "target_share": 0.18,
         "snap_pct": 0.55, "rush_fumbles_lost": 0, "recv_fumbles_lost": 0,
         "rz_targets": 6, "rz_tds": 2},
        {"season": 2023, "games_played": 16, "receptions": 88, "recv_yards": 1250,
         "recv_tds": 9, "targets": 118, "air_yards": 1680.0, "target_share": 0.28,
         "snap_pct": 0.85, "rush_fumbles_lost": 0, "recv_fumbles_lost": 0,
         "rz_targets": 18, "rz_tds": 7},
    ],
    # Expected flags: "rising", "limited_history"
    # Expected rank: mid-tier WR despite limited history (2023 was elite)
}


# ─── Test profile: High-injury, high-aggression RB ────────────────────────
BOOM_BUST_RB = {
    "player": {
        "player_id": "test_boom_bust_rb",
        "full_name": "Marcus Crasher",
        "position": "RB",
        "nfl_team": "DAL",
        "years_in_league": 4,
        "limited_history": False,
    },
    "seasons": [
        {"season": 2020, "games_played": 16, "carries": 310, "rush_yards": 1450,
         "rush_tds": 14, "receptions": 20, "recv_yards": 140, "recv_tds": 1,
         "targets": 25, "snap_pct": 0.85, "rush_fumbles_lost": 3, "recv_fumbles_lost": 1,
         "rz_carries": 75, "rz_targets": 5, "rz_tds": 12},
        {"season": 2021, "games_played": 6, "carries": 90, "rush_yards": 380,
         "rush_tds": 3, "receptions": 8, "recv_yards": 55, "recv_tds": 0,
         "targets": 10, "snap_pct": 0.80, "rush_fumbles_lost": 1, "recv_fumbles_lost": 0,
         "rz_carries": 20, "rz_targets": 2, "rz_tds": 2},
        {"season": 2022, "games_played": 13, "carries": 220, "rush_yards": 980,
         "rush_tds": 9, "receptions": 18, "recv_yards": 120, "recv_tds": 1,
         "targets": 24, "snap_pct": 0.78, "rush_fumbles_lost": 2, "recv_fumbles_lost": 0,
         "rz_carries": 48, "rz_targets": 4, "rz_tds": 8},
        {"season": 2023, "games_played": 9, "carries": 155, "rush_yards": 720,
         "rush_tds": 7, "receptions": 14, "recv_yards": 95, "recv_tds": 0,
         "targets": 18, "snap_pct": 0.80, "rush_fumbles_lost": 2, "recv_fumbles_lost": 0,
         "rz_carries": 35, "rz_targets": 3, "rz_tds": 5},
    ],
    # Expected flags: "injury_risk_high", "boom_bust", "aggression_high"
    # Expected rank: discounted significantly due to injury history
}


# ─── Test profile: Declining veteran QB ───────────────────────────────────
DECLINING_QB = {
    "player": {
        "player_id": "test_declining_qb",
        "full_name": "Gary Fading",
        "position": "QB",
        "nfl_team": "NYG",
        "years_in_league": 8,
        "limited_history": False,
    },
    "seasons": [
        {"season": 2020, "games_played": 16, "pass_attempts": 580, "completions": 380,
         "pass_yards": 4500, "pass_tds": 32, "interceptions": 10,
         "carries": 45, "rush_yards": 210, "rush_tds": 3, "rush_fumbles_lost": 1},
        {"season": 2021, "games_played": 15, "pass_attempts": 545, "completions": 355,
         "pass_yards": 4100, "pass_tds": 28, "interceptions": 12,
         "carries": 38, "rush_yards": 170, "rush_tds": 2, "rush_fumbles_lost": 2},
        {"season": 2022, "games_played": 14, "pass_attempts": 510, "completions": 320,
         "pass_yards": 3600, "pass_tds": 22, "interceptions": 14,
         "carries": 30, "rush_yards": 110, "rush_tds": 1, "rush_fumbles_lost": 1},
        {"season": 2023, "games_played": 13, "pass_attempts": 480, "completions": 295,
         "pass_yards": 3100, "pass_tds": 18, "interceptions": 16,
         "carries": 22, "rush_yards": 65, "rush_tds": 1, "rush_fumbles_lost": 2},
    ],
    # Expected flags: "declining"
    # Expected rank: low QB — clear year-over-year production drop
}


ALL_TEST_PLAYERS = [ELITE_RB, RISING_WR, BOOM_BUST_RB, DECLINING_QB]


def describe_expectations():
    """Print what the engine should produce for each synthetic player."""
    expectations = [
        ("Alex Steady (RB)",   "Top 3 RB, no major flags, high consistency score"),
        ("Jordan Breakout (WR)", "Mid WR, flags: rising + limited_history"),
        ("Marcus Crasher (RB)", "Penalized RB, flags: injury_risk_high + boom_bust"),
        ("Gary Fading (QB)",   "Low QB tier, flag: declining"),
    ]
    print("\nSynthetic player expectations:")
    print("─" * 60)
    for name, expectation in expectations:
        print(f"  {name:<30}  {expectation}")
    print("─" * 60)


if __name__ == "__main__":
    describe_expectations()
