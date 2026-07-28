"""
config_ncaaf.py — NCAA Football (FBS) sport configuration.

Single source of truth for the tuning constants ncaaf_engine.py needs. Markets and market_map
live in sports.py's registry (one place for market definitions across every sport), not
duplicated here — same convention as every other sport's config module.

DATA SOURCE, DIFFERENT FROM EVERY OTHER SPORT HERE, ON PURPOSE: CollegeFootballData.com (CFBD),
via the official `cfbd` Python client (PyPI, actively maintained, OpenAPI-generated). Every other
sport's engine (MLB Stats API, ESPN's public endpoints, nflreadpy) is free and effectively
unlimited, so those engines fetch live, per Streamlit page load. CFBD's FREE TIER IS METERED —
roughly 1,000 API calls per month per the provider's own published limit (confirmed via
CFBD's blog: "The free tier has been set at 1000 monthly calls"). Fetching live per-page-load the
way every other sport does would exhaust that budget in days, not months. NCAAF is built on the
OTHER pattern this codebase already has precedent for: refresh_statcast.py / refresh_matchups.py's
nightly batch-cache — a scheduled job (refresh_ncaaf.py) pulls once, writes to
data/ncaaf_player_stats.csv / data/ncaaf_rosters.csv / data/ncaaf_schedule.csv, and ncaaf_engine.py
only ever reads those cached files, the same way matchup_data.py already works for pitch-level
Statcast data. This is a real architectural difference from MLB/WNBA/NBA/NCAAMB/NFL's engines,
not an oversight — see refresh_ncaaf.py's own docstring for the call-budget accounting.

HONEST CAVEAT, same posture this codebase already carries for ESPN's endpoints and NFL's
nflreadpy: field names below are confirmed against CFBD's OWN PUBLISHED OpenAPI documentation
(github.com/CFBD/cfbd-python/blob/main/docs/), not against a live response — this sandbox's
network is allowlisted to a fixed domain set that doesn't include api.collegefootballdata.com,
so nothing here has been exercised against real data the way nflreadpy's columns were (see
nfl_engine.py's own docstring for that contrast). One specific, real unknown flagged directly in
refresh_ncaaf.py: get_player_season_stats returns rows in LONG format (one row per
player-category-stat_type, with `stat` typed as a string) rather than one row per player with
columns -- the exact string values CFBD uses for each stat_type (e.g. is passing yards "YDS"
under category "passing", or something else) can only be confirmed against a real response. The
first real refresh run against a real key is the actual verification step, the same role NFL's
first live nflreadpy pull played for that engine.
"""

# How many of a team's recent games to pull per player for the projection (recency window).
# Same reasoning as NFL's own RECENT_GAMES_N=5, not NHTL/MLB's longer windows: an FBS regular
# season is only 12 games (13 for a team that scheduled a Hawaii game), even shorter than the
# NFL's 17 -- a longer window would swallow most or all of the season, diluting the recency
# signal the window exists to capture in the first place.
RECENT_GAMES_N = 4

# Minimum recency-weighted average of a player's PRIMARY opportunity stat to be treated as "in
# the rotation" and included on the slate. Same position-specific-floor reasoning as NFL's own
# config (see config_nfl.py's own comment) -- an opportunity-stat floor needs no extra data
# source and directly targets what a PROP model needs (real usage), not just snap counts CFBD may
# not expose per-play. NOT backtested against real NCAAF usage patterns yet -- a starting point,
# the same honest caveat every other tuning constant in this file carries.
MIN_QB_ATTEMPTS = 8.0
MIN_RB_TOUCHES = 4.0     # carries + targets combined
MIN_WR_TARGETS = 2.0

# Monte Carlo-style resample count for the bootstrap projection (see ncaaf_projections.py).
DEFAULT_SIMS = 10000

# 2026 season: Week 0 begins Thursday, August 27, 2026 (confirmed against multiple independent
# sources during scoping -- NCAA.com, ESPN's own published Week 1 schedule, and Athlon Sports --
# not a placeholder or a guessed "always late August" rule). The FULL FBS slate doesn't start
# until Saturday, August 29, and most Power-conference teams don't play until the Labor Day
# weekend window of September 3-7 ("Week 1 proper") -- so, same lesson NFL's own config recorded
# about not hardcoding a day-of-week rule, always resolve which week a given date falls in from
# the real schedule data (CFBD's /calendar endpoint), never assume "college football starts the
# last Saturday of August" as a fixed rule; Week 0 participants and Week 1 participants are
# genuinely different sets of teams in the same season.
SEASON_START = "2026-08-27"

# No hardcoded TEAMS reference table here — same reasoning as every other sport's config module.
# ncaaf_engine.py gets team names/conferences directly from CFBD's own roster/team data, not from
# this file.
