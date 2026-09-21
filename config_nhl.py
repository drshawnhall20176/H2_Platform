"""
config_nhl.py — NHL sport configuration.

Single source of truth for the tuning constants nhl_engine.py / nhl_projections.py need. Markets
and market_map live in sports.py's registry (one place for market definitions across every sport),
not duplicated here — same convention as config_wnba.py / config_nba.py.

Every number below is a STARTING POINT, not a calibrated value — same honest caveat every other
tuning constant on this platform carries (NBA's MIN_AVG_MINUTES, WNBA's BLOWOUT_THRESHOLD, ...).
They are worth re-checking against real graded NHL slates once there are some.
"""

# How many of a team's recent games to pull per player for the projection (recency window). Ten
# matches every other sport here. NOTE the real cost difference from basketball: ESPN's hockey
# per-game summary is ~400 KB (it carries play-by-play), so nhl_engine parses each game ONCE into a
# compact record and throws the raw response away — see nhl_engine.get_game.
RECENT_GAMES_N = 10

# How far back the recent-form scan looks for those games. 45 days comfortably holds ten games at
# the NHL's ~3-4 games/week pace. Early in the season it also reaches back into preseason games —
# deliberately: in the first weeks that is the only current-team data there is (see sports.py's
# NHL registry note).
RECENT_DAYS_BACK = 45

# Minimum average time on ice (minutes) for a SKATER to count as "in the lineup" and be included on
# the slate. A fourth-line forward typically plays 8-11 minutes and a top-pair defenseman 22+; 10.0
# drops the true bottom-of-the-roster / press-box-adjacent players (whose shot and point props
# aren't posted anyway) without dropping regular fourth-liners who are. Same role as
# MIN_AVG_MINUTES for basketball.
MIN_AVG_TOI = 10.0

# A goalie only gets a saves projection if he was his team's goalie of record (most ice time, at
# least this many minutes) in one of the team's last GOALIE_LOOKBACK_GAMES games. Starting goalies
# are only confirmed on game day, so "recent starter" is the honest proxy — see nhl_engine.build_slate.
GOALIE_MIN_TOI = 20.0
GOALIE_LOOKBACK_GAMES = 5

# Monte Carlo-style resample count for the bootstrap projection (see nhl_projections.py).
DEFAULT_SIMS = 10000
