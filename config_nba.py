"""
config_nba.py — NBA sport configuration.

Single source of truth for the tuning constants nba_engine.py needs. Markets and market_map live
in sports.py's registry (one place for market definitions across every sport), not duplicated here
— same convention as config_wnba.py.
"""

# How many of a team's recent games to pull per player for the projection (recency window).
RECENT_GAMES_N = 10

# Minimum recency-weighted average minutes for a player to be treated as "in the rotation" and
# included on the slate. Filters out deep bench / two-way players with no meaningful playing-time
# signal. Carried over from WNBA's own 12.0 as a starting point — NBA games run 48 minutes (vs.
# WNBA's 40) and rotations vary more by team/coach than WNBA's, so this is worth revisiting once
# real NBA slate data is available to sanity-check against, not treated as a confirmed-correct
# number just because it matches WNBA's.
MIN_AVG_MINUTES = 12.0

# Monte Carlo-style resample count for the bootstrap projection (see nba_projections.py).
DEFAULT_SIMS = 10000

# No hardcoded TEAMS reference table here, unlike config_wnba.py's — deliberately. That table is
# explicitly "reference data only" there too (nba_engine.py, like wnba_engine.py, gets team ids/
# names/abbreviations directly from each live scoreboard/roster response, not from this file), and
# NBA's 30-team list, while stable, wasn't worth transcribing from memory here when it isn't
# actually needed for the engine to function. Add one later if something outside the engine wants
# the league's team list without a network call — same reasoning as config_wnba.TEAMS.
