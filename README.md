# Fantasy Football Ranker

A configurable, data-driven player ranking system that weighs historical
performance, context signals, injury risk, schedule, and consistency to
produce customized draft boards and player valuations.

---

## Project philosophy

Most fantasy tools give you a single ranking list with no explanation.
This system is different in three ways:

1. **Transparent**: every player's rank includes a human-readable reasoning
   breakdown showing which modules drove the score up or down.
2. **Configurable**: league format, scoring rules, lookback window, and
   module weights are all user-controlled via a single config file.
3. **Extensible**: the architecture is designed from day one to support
   future features (rookies, waiver wire, trade analyzer, league sync)
   without schema rewrites.

---

## Roadmap

### v1 — Core engine (current)
- Historical stat ingestion and normalization
- Configurable fantasy point model
- Six scoring modules with weighted composite
- CLI output with per-player reasoning
- CSV / spreadsheet export

### v2 — Rookie integration
- College stat ingestion (cfbfastR)
- Positional translation models (college → NFL)
- Rookie-specific ranking tier (separate or blended, user choice)

### v3 — In-season tools
- Weekly waiver wire rankings with adds/drops suggestions
- Injury news integration (real-time feed)
- Start/sit recommendations

### v4 — League sync
- ESPN / Sleeper / Yahoo API connectors
- Trade analyzer with value differential
- Your roster vs. league outlook

### v5 — App
- Web UI with connected league dashboard
- Push notifications for injury/news events
- Draft assistant mode (live pick tracking)

---

## Directory structure

```
ff_ranker/
├── config/
│   ├── league_config.yaml       # User's league settings
│   ├── scoring_presets/         # ESPN, Yahoo, Sleeper, DraftKings templates
│   └── module_weights.yaml      # Per-module weight tuning
├── data/
│   ├── raw/                     # Unmodified API/scrape outputs
│   ├── processed/               # Cleaned, merged per-player records
│   └── cache/                   # SQLite DB for avoiding re-fetches
├── engine/
│   ├── ingestion.py             # Data fetch + normalization
│   ├── fantasy_points.py        # Module 1: scoring model
│   ├── trend.py                 # Module 2: trajectory & rise/fall
│   ├── injury_risk.py           # Module 3: injury history + aggression
│   ├── schedule.py              # Module 4: SOS + opponent adjustments
│   ├── context.py               # Module 5: O-line, team, QB signals
│   ├── consistency.py           # Module 6: CV, floor/ceiling
│   ├── vbd.py                   # Value over replacement (cross-pos)
│   └── composite.py             # Weighted aggregator + reasoning gen
├── output/
│   ├── cli.py                   # CLI ranking display
│   ├── export.py                # CSV / Excel export
│   └── report.py                # Per-player profile printer
├── scripts/
│   ├── fetch_stats.py           # One-off data pull scripts
│   └── backfill.py              # Historical data seeding
├── tests/
│   ├── synthetic_players.py     # Known-good test cases
│   └── test_modules.py          # Unit tests per module
├── docs/
│   └── DATA_SOURCES.md          # API keys, rate limits, attribution
├── main.py                      # Entry point
└── requirements.txt
```
