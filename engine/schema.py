"""
schema.py
=========
Canonical data models for the Fantasy Football Ranker.

This file defines:
  1. Python dataclasses — used throughout the engine as typed containers.
  2. SQLite DDL strings — used by ingestion.py to initialise the cache DB.

Design principles:
  - Every table has a `last_updated` timestamp so stale records can be
    detected and re-fetched without nuking the whole cache.
  - Player identity is keyed on (player_id, source) so records from
    nfl-data-py, PFF, and future sources can coexist without collision.
  - Season-level and game-level records are kept separate so the engine
    can aggregate at whichever granularity a module needs.
  - All computed / derived fields live in Python, not the DB.
    The DB is a clean data store; the engine does the math.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import date

# ==============================================================
# 1. PYTHON DATACLASSES
# ==============================================================

@dataclass
class Player:
    """
    Core identity record. One row per real-world player.
    Populated during ingestion; never recomputed.
    """
    player_id: str              # nfl-data-py gsis_id (primary key)
    full_name: str
    position: str               # QB | RB | WR | TE
    nfl_team: str               # current team abbreviation
    birth_date: Optional[date]
    draft_year: Optional[int]
    draft_round: Optional[int]
    draft_pick: Optional[int]
    height_inches: Optional[int]
    weight_lbs: Optional[int]
    years_in_league: int        # computed at load time
    limited_history: bool       # True if < 3 seasons of data
    last_updated: str           # ISO timestamp


@dataclass
class SeasonStats:
    """
    Aggregated per-player, per-season stat line.
    One row per (player_id, season). Core input to most modules.
    """
    player_id: str
    season: int                 # e.g. 2023

    # --- Availability ---
    games_played: int
    games_started: int

    # --- Passing (QB) ---
    pass_attempts: Optional[int]
    completions: Optional[int]
    pass_yards: Optional[int]
    pass_tds: Optional[int]
    interceptions: Optional[int]
    sacks: Optional[int]
    sack_yards_lost: Optional[int]

    # --- Rushing ---
    carries: Optional[int]
    rush_yards: Optional[int]
    rush_tds: Optional[int]
    rush_fumbles_lost: Optional[int]
    yards_after_contact: Optional[float]  # per carry
    broken_tackles: Optional[int]

    # --- Receiving ---
    targets: Optional[int]
    receptions: Optional[int]
    recv_yards: Optional[int]
    recv_tds: Optional[int]
    recv_fumbles_lost: Optional[int]
    air_yards: Optional[float]            # total air yards on targets
    yards_after_catch: Optional[float]    # per reception
    target_share: Optional[float]         # % of team targets (0.0–1.0)
    air_yards_share: Optional[float]      # % of team air yards

    # --- Usage / efficiency ---
    snap_pct: Optional[float]             # % of team offensive snaps
    route_participation: Optional[float]  # routes run / team pass plays (WR/TE)
    touch_share: Optional[float]          # (carries + targets) / team plays

    # --- Red zone ---
    rz_targets: Optional[int]             # targets inside opp 20
    rz_carries: Optional[int]             # carries inside opp 10
    rz_tds: Optional[int]                 # total TDs from red zone

    # --- Special teams ---
    return_tds: Optional[int]

    last_updated: str


@dataclass
class InjuryRecord:
    """
    One row per injury event. Linked to player by player_id.
    Used to build career injury frequency and body-region patterns.
    """
    injury_id: str              # synthetic UUID
    player_id: str
    season: int
    week: int
    injury_type: str            # e.g. "hamstring", "ACL", "concussion"
    body_region: str            # "lower_body" | "upper_body" | "head"
    severity: str               # "questionable" | "doubtful" | "IR" | "PUP"
    games_missed: int
    returned_same_season: bool
    last_updated: str


@dataclass
class TeamContext:
    """
    Per-team, per-season contextual signals.
    Joined to player records during context module scoring.
    """
    team: str                   # abbreviation e.g. "KC"
    season: int

    # --- O-line ---
    oline_pff_grade: Optional[float]      # 0–100, higher = better
    oline_run_block_grade: Optional[float]
    oline_pass_block_grade: Optional[float]
    adjusted_line_yards: Optional[float]  # fallback if no PFF

    # --- Team performance ---
    wins: int
    losses: int
    ties: int
    points_scored: int
    points_allowed: int
    pass_rate: Optional[float]            # % of plays that are passes
    projected_wins: Optional[float]       # Vegas or model projection

    # --- QB situation ---
    starting_qb_id: str
    qb_is_new: bool                       # new starter vs prior season
    qb_years_of_starts: int               # career games started as starter
    qb_passer_rating: Optional[float]

    last_updated: str


@dataclass
class ScheduleEntry:
    """
    One row per (team, week, season). Used by schedule module
    to compute strength-of-schedule and matchup quality.
    """
    team: str
    season: int
    week: int
    opponent: str
    is_home: bool
    is_bye: bool

    # Points that opponent's defense allowed to each position
    # in the previous 2 seasons (rolling average)
    opp_pts_allowed_vs_qb: Optional[float]
    opp_pts_allowed_vs_rb: Optional[float]
    opp_pts_allowed_vs_wr: Optional[float]
    opp_pts_allowed_vs_te: Optional[float]

    last_updated: str


@dataclass
class ModuleScore:
    """
    Output of a single scoring module for one player.
    Six of these (one per module) are aggregated into PlayerRanking.
    """
    player_id: str
    season_evaluated: int       # the upcoming season being projected
    module_name: str            # e.g. "fantasy_points", "trend"
    raw_score: float            # module's native output (not normalized)
    normalized_score: float     # 0.0–1.0 relative to position peers
    weight_applied: float       # from config, post-normalization
    weighted_contribution: float
    flags: list[str]            # e.g. ["rising", "td_regression_risk"]
    reasoning: list[str]        # human-readable bullets for this module


@dataclass
class PlayerRanking:
    """
    Final output record for a single player.
    One row per player in the ranking output.
    """
    player_id: str
    full_name: str
    position: str
    nfl_team: str
    years_in_league: int
    limited_history: bool

    # --- Composite ---
    composite_score: float          # weighted sum of all module scores
    position_rank: int              # rank within position
    overall_rank: int               # rank across all positions (VBD-adjusted)
    vbd_score: float                # value above replacement baseline

    # --- Module breakdown ---
    module_scores: list[ModuleScore]

    # --- Flags ---
    flags: list[str]                # union of all module flags
    # Common flags:
    #   "rising"              — trajectory significantly above career mean
    #   "declining"           — trajectory below career mean
    #   "boom_bust"           — high coefficient of variation
    #   "injury_risk_high"    — career avg > 5 games missed/season
    #   "aggression_high"     — high contact absorption, elevated risk
    #   "td_regression_risk"  — last-year TD rate > 1.5σ above career
    #   "limited_history"     — fewer than 3 seasons of data
    #   "qb_uncertainty"      — team has new/unproven starting QB
    #   "bad_team"            — team projected for ≤5 wins
    #   "favorable_schedule"  — top-third SOS for their position
    #   "tough_schedule"      — bottom-third SOS for their position

    # --- Reasoning ---
    reasoning: list[str]            # consolidated bullets for CLI/export


# ==============================================================
# 2. SQLITE DDL
# ==============================================================

SCHEMA_DDL = """
-- Players table (identity only, no stats)
CREATE TABLE IF NOT EXISTS players (
    player_id           TEXT PRIMARY KEY,
    full_name           TEXT NOT NULL,
    position            TEXT NOT NULL,
    nfl_team            TEXT,
    birth_date          TEXT,
    draft_year          INTEGER,
    draft_round         INTEGER,
    draft_pick          INTEGER,
    height_inches       INTEGER,
    weight_lbs          INTEGER,
    years_in_league     INTEGER,
    limited_history     INTEGER DEFAULT 0,   -- 0=false, 1=true
    last_updated        TEXT NOT NULL
);

-- Season-level stats (one row per player per season)
CREATE TABLE IF NOT EXISTS season_stats (
    player_id               TEXT NOT NULL,
    season                  INTEGER NOT NULL,
    games_played            INTEGER,
    games_started           INTEGER,

    -- Passing
    pass_attempts           INTEGER,
    completions             INTEGER,
    pass_yards              INTEGER,
    pass_tds                INTEGER,
    interceptions           INTEGER,
    sacks                   INTEGER,
    sack_yards_lost         INTEGER,

    -- Rushing
    carries                 INTEGER,
    rush_yards              INTEGER,
    rush_tds                INTEGER,
    rush_fumbles_lost       INTEGER,
    yards_after_contact     REAL,
    broken_tackles          INTEGER,

    -- Receiving
    targets                 INTEGER,
    receptions              INTEGER,
    recv_yards              INTEGER,
    recv_tds                INTEGER,
    recv_fumbles_lost       INTEGER,
    air_yards               REAL,
    yards_after_catch       REAL,
    target_share            REAL,
    air_yards_share         REAL,

    -- Usage
    snap_pct                REAL,
    route_participation     REAL,
    touch_share             REAL,

    -- Red zone
    rz_targets              INTEGER,
    rz_carries              INTEGER,
    rz_tds                  INTEGER,

    -- Special teams
    return_tds              INTEGER,

    last_updated            TEXT NOT NULL,
    PRIMARY KEY (player_id, season)
);

-- Injury events
CREATE TABLE IF NOT EXISTS injury_records (
    injury_id               TEXT PRIMARY KEY,
    player_id               TEXT NOT NULL,
    season                  INTEGER NOT NULL,
    week                    INTEGER,
    injury_type             TEXT,
    body_region             TEXT,
    severity                TEXT,
    games_missed            INTEGER,
    returned_same_season    INTEGER DEFAULT 1,
    last_updated            TEXT NOT NULL
);

-- Team context (O-line, QB, team projections)
CREATE TABLE IF NOT EXISTS team_context (
    team                    TEXT NOT NULL,
    season                  INTEGER NOT NULL,
    oline_pff_grade         REAL,
    oline_run_block_grade   REAL,
    oline_pass_block_grade  REAL,
    adjusted_line_yards     REAL,
    wins                    INTEGER,
    losses                  INTEGER,
    ties                    INTEGER,
    points_scored           INTEGER,
    points_allowed          INTEGER,
    pass_rate               REAL,
    projected_wins          REAL,
    starting_qb_id          TEXT,
    qb_is_new               INTEGER DEFAULT 0,
    qb_years_of_starts      INTEGER,
    qb_passer_rating        REAL,
    last_updated            TEXT NOT NULL,
    PRIMARY KEY (team, season)
);

-- Schedule matchups
CREATE TABLE IF NOT EXISTS schedule (
    team                        TEXT NOT NULL,
    season                      INTEGER NOT NULL,
    week                        INTEGER NOT NULL,
    opponent                    TEXT,
    is_home                     INTEGER DEFAULT 1,
    is_bye                      INTEGER DEFAULT 0,
    opp_pts_allowed_vs_qb       REAL,
    opp_pts_allowed_vs_rb       REAL,
    opp_pts_allowed_vs_wr       REAL,
    opp_pts_allowed_vs_te       REAL,
    last_updated                TEXT NOT NULL,
    PRIMARY KEY (team, season, week)
);

-- Indices for common query patterns
CREATE INDEX IF NOT EXISTS idx_season_stats_player
    ON season_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_season_stats_season
    ON season_stats(season);
CREATE INDEX IF NOT EXISTS idx_injuries_player
    ON injury_records(player_id);
CREATE INDEX IF NOT EXISTS idx_schedule_team_season
    ON schedule(team, season);
"""
