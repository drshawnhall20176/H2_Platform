"""
config_wnba.py — WNBA sport configuration.

Single source of truth for the tuning constants wnba_engine.py needs. Markets and market_map
live in sports.py's registry (Stage 1 decision — one place for market definitions across every
sport), not duplicated here.
"""

# Team ID -> (full name, abbreviation, conference). Verified live from https://www.wnba.com/teams
# on 2026-07-13. 15 teams for the 2026 season (incl. Portland Fire / Toronto Tempo expansion).
# Reference data only — wnba_engine.py (ESPN's API) gets team IDs and names directly from each
# scoreboard/roster response rather than cross-referencing this table, since ESPN's team ID space
# is its own numbering, unrelated to wnba.com's. Kept here for anywhere else that wants the
# league's real team list without a network call. Re-verify at the start of a future season in
# case of further expansion/relocation.
TEAMS = {
    1611661330: ("Atlanta Dream", "ATL", "East"),
    1611661329: ("Chicago Sky", "CHI", "East"),
    1611661323: ("Connecticut Sun", "CON", "East"),
    1611661325: ("Indiana Fever", "IND", "East"),
    1611661313: ("New York Liberty", "NY", "East"),
    1611661332: ("Toronto Tempo", "TOR", "East"),
    1611661322: ("Washington Mystics", "WSH", "East"),
    1611661321: ("Dallas Wings", "DAL", "West"),
    1611661331: ("Golden State Valkyries", "GS", "West"),
    1611661319: ("Las Vegas Aces", "LV", "West"),
    1611661320: ("Los Angeles Sparks", "LA", "West"),
    1611661324: ("Minnesota Lynx", "MIN", "West"),
    1611661317: ("Phoenix Mercury", "PHX", "West"),
    1611661327: ("Portland Fire", "POR", "West"),
    1611661328: ("Seattle Storm", "SEA", "West"),
}

# How many of a team's recent games to pull per player for the projection (recency window).
RECENT_GAMES_N = 10

# Minimum recency-weighted average minutes for a player to be treated as "in the rotation" and
# included on the slate. Filters out deep bench / two-way players with no meaningful playing-time
# signal, the same role LINEUP_SPOT_PA plays for MLB (excluding bottom-of-roster noise).
MIN_AVG_MINUTES = 12.0

# Monte Carlo-style resample count for the bootstrap projection (see wnba_projections.py).
DEFAULT_SIMS = 10000
