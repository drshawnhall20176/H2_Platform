"""
config_nfl.py — NFL sport configuration.

Single source of truth for the tuning constants nfl_engine.py needs. Markets and market_map live
in sports.py's registry (one place for market definitions across every sport), not duplicated
here — same convention as every other sport's config module.

REPLACES an earlier draft of this file that had a real, load-bearing bug worth recording: its
SUPPORTED_MARKETS used entirely fabricated Odds API market keys ("quarterback_passing_yards",
"player_rushing_yards", "player_receiving_yards") that don't exist in Odds API's real market
taxonomy at all. Edge Board would have fetched zero real odds for NFL — not an error, just
silently empty results, the exact failure mode this platform's diagnostic-print discipline exists
to catch. The real, confirmed keys (player_pass_yds, player_rush_yds, player_receptions,
player_reception_yds) now live in sports.py's registry, matching every other sport's convention.
"""

# How many of a team's recent games to pull per player for the projection (recency window).
# Deliberately SHORTER than every other sport's RECENT_GAMES_N=10: an NFL regular season is only
# 17 games total, not the 40-90+ games other sports' seasons run — a 10-game "recent form" window
# would be more than half the season, diluting exactly the recency signal the window exists to
# capture. 5 is a starting point, not backtested — worth revisiting once real usage exists to
# check calibration against, same honest caveat every other tuning constant here carries.
RECENT_GAMES_N = 5

# Minimum recency-weighted average of a player's PRIMARY opportunity stat (attempts for QBs,
# carries+targets for RBs, targets for WR/TE) to be treated as "in the rotation" and included on
# the slate. Deliberately NOT a snap-share threshold (nflreadpy's load_snap_counts is a separate
# fetch this module doesn't make in v1) — an opportunity-stat floor is simpler, needs no extra
# data source, and directly targets what actually matters for a PROP model: a player who barely
# touches the ball produces noise, not a real projection, regardless of how many snaps they logged
# doing it (e.g. a blocking-only TE snaps plenty but never sees a target). Position-specific
# thresholds, not one shared number — the stats aren't on the same scale (a floor useful for QB
# attempts would be meaningless for WR targets).
MIN_QB_ATTEMPTS = 10.0
MIN_RB_TOUCHES = 4.0     # carries + targets combined
MIN_WR_TARGETS = 2.0

# Monte Carlo-style resample count for the bootstrap projection (see nfl_projections.py).
DEFAULT_SIMS = 10000

# 2026 NFL regular season: September 9, 2026 – January 10, 2027. CONFIRMED LIVE during scoping
# (the NFL's own schedule release, cross-checked against Wikipedia's 2026 NFL season page), not a
# placeholder. Worth noting as a genuinely unusual, specifically-confirmed detail: 2026 opens on a
# WEDNESDAY, not the traditional Thursday — the first Wednesday opener in 14 years (Seahawks
# hosting the Patriots) — so "week 1 starts the Thursday after Labor Day" is NOT a safe assumption
# to hardcode elsewhere; always resolve from the real schedule data, never from a day-of-week rule.
SEASON_START = "2026-09-09"

# No hardcoded TEAMS reference table here — same reasoning as every other sport's config module.
# nfl_engine.py gets team abbreviations directly from nflreadpy's own schedule/roster data, not
# from this file.
