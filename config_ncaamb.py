"""
config_ncaamb.py — NCAA Men's Basketball sport configuration.

Single source of truth for the tuning constants ncaamb_engine.py needs. Markets and market_map
live in sports.py's registry (one place for market definitions across every sport), not
duplicated here — same convention as config_wnba.py/config_nba.py.
"""

# How many of a team's recent games to pull per player for the projection (recency window).
# Kept at 10, same as every other sport on this platform, for consistency — not because NCAAMB's
# season length specifically calls for it. Worth revisiting: the 2026-27 season allows up to 32
# regular-season games (up from 28-29 previously, confirmed via the NCAA's own rule change), so
# there's more season to draw from than before if a wider window ever seems worth it.
RECENT_GAMES_N = 10

# Minimum recency-weighted average minutes for a player to be treated as "in the rotation" and
# included on the slate. Set to WNBA's value (12.0), not NBA's — NCAAMB games run 40 minutes
# (two 20-minute halves), the same length as WNBA's, not NBA's 48. That's the more defensible
# analog for "in the rotation" minutes than blindly copying NBA's number just because NBA was
# built more recently. Still a starting point, not backtested — worth revisiting once real
# NCAAMB slate data is available to sanity-check against.
MIN_AVG_MINUTES = 12.0

# Monte Carlo-style resample count for the bootstrap projection (see ncaamb_projections.py).
DEFAULT_SIMS = 10000

# No hardcoded TEAMS reference table here — same reasoning as config_nba.py's absence of one.
# Doubly true for NCAAMB: Division I alone is 350+ teams across dozens of conferences, with real
# realignment churn most seasons (confirmed during scoping: 29 schools are set to start play in
# new conferences for 2026-27 alone). ncaamb_engine.py gets team ids/names/abbreviations directly
# from each live scoreboard/roster response, not from this file, so a hardcoded list here would
# only be reference data nothing actually depends on — and considerably more likely to drift
# stale than WNBA's or NBA's much smaller, much more stable team lists.
