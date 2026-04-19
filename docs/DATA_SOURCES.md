# Data Sources Reference

## Primary stat source — nfl-data-py

Python wrapper around the nflfastR dataset (R package).
Covers play-by-play and player stats from 1999 to present.
No API key required. Data hosted on GitHub.

Install: `pip install nfl-data-py`

Key functions:
  - `nfl.import_pbp_data([2021, 2022, 2023])`  — play-by-play
  - `nfl.import_weekly_data([2021, 2022, 2023])` — weekly player stats
  - `nfl.import_seasonal_data([2021, 2022, 2023])` — season totals
  - `nfl.import_schedules([2024])` — upcoming schedule
  - `nfl.import_rosters([2024])` — current team rosters

Fields available (partial list):
  carries, rushing_yards, rushing_tds, rushing_fumbles_lost
  receptions, targets, receiving_yards, receiving_tds
  target_share, air_yards, yards_after_catch
  snap_counts, snap_pct (weekly only)
  broken_tackles, yards_after_contact (PBP-derived)

Rate limits: none (static file downloads from GitHub)
Attribution: nflfastR (Ben Baldwin, Sebastian Carl)


## Schedule / opponent strength — nfl-data-py

`nfl.import_schedules([2024])` returns full schedule including
team, opponent, week, and home/away for the upcoming season.

For "points allowed vs position" (the key schedule metric):
  Compute from weekly_data: group by opponent team × position,
  average fantasy points allowed. This is fully self-contained
  within nfl-data-py — no separate schedule API needed.


## O-line grades — PFF (Pro Football Focus)

PFF provides the most accurate O-line grades available.
A data subscription is required (~$100/yr for the Edge tier).

API: https://www.pff.com/grades
Fields: team, season, overall_grade, run_block_grade, pass_block_grade

Fallback (free): Adjusted Line Yards from Football Outsiders
  URL: https://www.footballoutsiders.com/stats/nfl/oline
  Scrape with requests + BeautifulSoup (see scripts/fetch_stats.py)

Caching strategy: O-line grades change once per season.
  Cache in SQLite team_context table. Refresh once in March-April
  after previous season grades are finalized.


## Injury records — Rotowire / InjuryMaster

For historical injury data (type, severity, games missed):
  - Rotowire has structured injury history per player
  - InjuryMaster (injurymaster.com) provides career injury logs
  - Pro Football Reference has "missed games" counts by season

Free alternative: Scrape Pro Football Reference injury transactions.
  URL pattern: https://www.pro-football-reference.com/players/{initial}/{player_id}/
  Fields: season, week, injury, games_missed

Rate limits: PFR — max 20 requests/minute. Cache aggressively.


## QB / team context — nfl-data-py + Vegas lines

Starting QB per team: available from `nfl.import_rosters()`
QB stats (passer rating, starts): from `nfl.import_seasonal_data()`

Team win projections:
  - Vegas over/under lines: available from The Odds API (free tier)
    URL: https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds
    API key: required (free tier = 500 requests/month — sufficient)
  - 538 projections (discontinued 2023 — use Vegas as primary)


## Aggression / contact metrics — nflfastR PBP

Derived from play-by-play:
  - `yards_after_contact` — available directly in PBP data
  - `broken_tackles` — available in weekly_data from nflfastR v5+
  - Contact rate — compute as: (carries with contact flag) / total carries
    Filter PBP on `tackle_for_loss == 1 OR yards_after_contact < 0`
    as proxy for pre-YAC contact.


## Red zone data — nfl-data-py PBP

Derived from PBP by filtering:
  `yardline_100 <= 20` for targets
  `yardline_100 <= 10` for carries

Group by player × season and count.


## VBD baseline calibration

No external source needed. Computed dynamically from the ranked pool.
Replacement rank = league_teams × starters_at_position + FLEX allocation.
Formula implemented in engine/composite.py → DEFAULT_REPLACEMENT_RANKS.


## API key storage

Store keys in a `.env` file (never commit to git):

```
ODDS_API_KEY=your_key_here
PFF_API_KEY=your_key_here   # if PFF subscription
```

Load with `python-dotenv`:
```python
from dotenv import load_dotenv
import os
load_dotenv()
key = os.getenv("ODDS_API_KEY")
```

Add `.env` to `.gitignore` immediately.
