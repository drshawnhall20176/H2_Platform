"""
league_structure.py — static conference/division/league reference tables, one per sport, for
grouping the "Today's Schedule" section on Home.py.

WHY STATIC, NOT FETCHED LIVE: conference/division alignment is real, but essentially never
changes mid-season (NBA/NFL/MLB divisions have been stable for years; the one live exception --
the Athletics -- kept their AL West slot through their Sacramento/Las Vegas relocation, confirmed
directly, not assumed). A live lookup would mean an extra network call on every Home.py load for
data that's genuinely static almost all the time. Re-verify at the start of a season in case of
expansion/realignment, same maintenance posture config_wnba.py's own TEAMS table already documents.

KEYING CHOICE, PER SPORT: each table is keyed by whatever field that sport's own get_schedule()
ALREADY returns reliably, specifically to avoid guessing at a data source's own abbreviation
quirks (confirmed real risk -- ESPN's own listing style, e.g. "LA Clippers" not "Los Angeles
Clippers", differs from other sources' conventions):
  - MLB: full team name, matching mlb_engine.MLB_TEAM_ABBR's own keys exactly (the same 30 real
    names the MLB Stats API's home_name/away_name fields return) -- reused directly, not
    reimplemented, so the two tables can never drift on team-name spelling.
  - NBA / WNBA: full team display name, matching nba_engine/wnba_engine's own home_name/away_name
    (ESPN's own displayName field) -- avoids trusting a hand-typed guess at ESPN's abbreviation
    for each team when the full name is already captured reliably.
  - NFL: nflreadr's own standard team abbreviation (confirmed against nflreadr's own
    clean_team_abbrs() reference: "LA" for the Rams, not "LAR"; "LV" for the Raiders; "LAC" for
    the Chargers) -- nfl_engine.get_schedule only returns home_team/away_team as this exact
    abbreviation, no full-name field exists in that function's current return shape to key on
    instead.

FAILS SAFE ON A MISS: any team name/abbreviation not found in these tables (a typo here, a future
relocation, an unmapped edge case) simply doesn't get a conference/division -- the calling code
must treat this as "ungrouped," never crash. See schedule_board.py's own docstring for how the
miss is actually handled in the UI (an "Other" bucket, not a dropped game).
"""

# --------------------------------------------------------------------------------------- MLB
# League + division, keyed by the exact same 30 full team names mlb_engine.MLB_TEAM_ABBR uses.
# The Athletics keep their AL West slot through the Sacramento/Las Vegas relocation -- confirmed
# live (2026 AL West standings still list "Athletics" alongside Mariners/Rangers/Astros), not a
# holdover assumption from before the move.
MLB_TEAM_LEAGUE = {
    "Baltimore Orioles": ("AL", "East"), "Boston Red Sox": ("AL", "East"),
    "New York Yankees": ("AL", "East"), "Tampa Bay Rays": ("AL", "East"),
    "Toronto Blue Jays": ("AL", "East"),
    "Chicago White Sox": ("AL", "Central"), "Cleveland Guardians": ("AL", "Central"),
    "Detroit Tigers": ("AL", "Central"), "Kansas City Royals": ("AL", "Central"),
    "Minnesota Twins": ("AL", "Central"),
    "Athletics": ("AL", "West"), "Houston Astros": ("AL", "West"),
    "Los Angeles Angels": ("AL", "West"), "Seattle Mariners": ("AL", "West"),
    "Texas Rangers": ("AL", "West"),
    "Atlanta Braves": ("NL", "East"), "Miami Marlins": ("NL", "East"),
    "New York Mets": ("NL", "East"), "Philadelphia Phillies": ("NL", "East"),
    "Washington Nationals": ("NL", "East"),
    "Chicago Cubs": ("NL", "Central"), "Cincinnati Reds": ("NL", "Central"),
    "Milwaukee Brewers": ("NL", "Central"), "Pittsburgh Pirates": ("NL", "Central"),
    "St. Louis Cardinals": ("NL", "Central"),
    "Arizona Diamondbacks": ("NL", "West"), "Colorado Rockies": ("NL", "West"),
    "Los Angeles Dodgers": ("NL", "West"), "San Diego Padres": ("NL", "West"),
    "San Francisco Giants": ("NL", "West"),
}

# --------------------------------------------------------------------------------------- NBA
# Conference + division, keyed by ESPN's own displayName (confirmed convention: "LA Clippers",
# not "Los Angeles Clippers" -- the one real naming quirk in this table). 30 teams, unchanged
# since the 2004/2008 realignment (confirmed live) -- no relocation/expansion pending.
NBA_TEAM_CONFERENCE = {
    "Boston Celtics": ("Eastern", "Atlantic"), "Brooklyn Nets": ("Eastern", "Atlantic"),
    "New York Knicks": ("Eastern", "Atlantic"), "Philadelphia 76ers": ("Eastern", "Atlantic"),
    "Toronto Raptors": ("Eastern", "Atlantic"),
    "Chicago Bulls": ("Eastern", "Central"), "Cleveland Cavaliers": ("Eastern", "Central"),
    "Detroit Pistons": ("Eastern", "Central"), "Indiana Pacers": ("Eastern", "Central"),
    "Milwaukee Bucks": ("Eastern", "Central"),
    "Atlanta Hawks": ("Eastern", "Southeast"), "Charlotte Hornets": ("Eastern", "Southeast"),
    "Miami Heat": ("Eastern", "Southeast"), "Orlando Magic": ("Eastern", "Southeast"),
    "Washington Wizards": ("Eastern", "Southeast"),
    "Denver Nuggets": ("Western", "Northwest"), "Minnesota Timberwolves": ("Western", "Northwest"),
    "Oklahoma City Thunder": ("Western", "Northwest"), "Portland Trail Blazers": ("Western", "Northwest"),
    "Utah Jazz": ("Western", "Northwest"),
    "Golden State Warriors": ("Western", "Pacific"), "LA Clippers": ("Western", "Pacific"),
    "Los Angeles Lakers": ("Western", "Pacific"), "Phoenix Suns": ("Western", "Pacific"),
    "Sacramento Kings": ("Western", "Pacific"),
    "Dallas Mavericks": ("Western", "Southwest"), "Houston Rockets": ("Western", "Southwest"),
    "Memphis Grizzlies": ("Western", "Southwest"), "New Orleans Pelicans": ("Western", "Southwest"),
    "San Antonio Spurs": ("Western", "Southwest"),
}

# --------------------------------------------------------------------------------------- NFL
# Conference + division, keyed by nflreadr's own standard current-location abbreviation
# (confirmed against nflreadr's clean_team_abbrs() reference table -- "LA" for the Rams, "LV" for
# the Raiders, "LAC" for the Chargers). One entry (Washington: "WAS") verified against nflreadr's
# own convention but not against a live pull from inside this sandbox (no network path to
# nflreadpy's data here) -- if this one specific team lands in the "Other" bucket on first real
# deploy instead of NFC East, that's the one to check first, not a sign the whole table is wrong.
NFL_TEAM_CONFERENCE = {
    "BUF": ("AFC", "East"), "MIA": ("AFC", "East"), "NE": ("AFC", "East"), "NYJ": ("AFC", "East"),
    "BAL": ("AFC", "North"), "CIN": ("AFC", "North"), "CLE": ("AFC", "North"), "PIT": ("AFC", "North"),
    "HOU": ("AFC", "South"), "IND": ("AFC", "South"), "JAX": ("AFC", "South"), "TEN": ("AFC", "South"),
    "DEN": ("AFC", "West"), "KC": ("AFC", "West"), "LV": ("AFC", "West"), "LAC": ("AFC", "West"),
    "DAL": ("NFC", "East"), "NYG": ("NFC", "East"), "PHI": ("NFC", "East"), "WAS": ("NFC", "East"),
    "CHI": ("NFC", "North"), "DET": ("NFC", "North"), "GB": ("NFC", "North"), "MIN": ("NFC", "North"),
    "ATL": ("NFC", "South"), "CAR": ("NFC", "South"), "NO": ("NFC", "South"), "TB": ("NFC", "South"),
    "ARI": ("NFC", "West"), "LA": ("NFC", "West"), "SF": ("NFC", "West"), "SEA": ("NFC", "West"),
}


def wnba_team_conference() -> dict:
    """{full team name: conference} for WNBA -- East/West only, no division level (the real
    WNBA structure has none). Derived directly from config_wnba.TEAMS rather than duplicated, so
    the two tables can never drift apart on team names or conference assignment. Local import
    (not module-level) to avoid a circular import, since config_wnba.py has no reason to import
    this module back."""
    import config_wnba
    return {name: conf for _tid, (name, _abbr, conf) in config_wnba.TEAMS.items()}
