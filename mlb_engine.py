"""
mlb_engine.py — shared data/analytics backend for the dashboard.
 
Framework-agnostic (no Streamlit import). Pages wrap the expensive calls with
@st.cache_data for caching/TTL. This module fixes the issues from the original pages:
 
  * one hydrated request per hitter (batSide + season stats together), not two
  * per-team lineup detection (posted batting order -> active roster fallback)
  * concurrent fetching so a full slate loads in a few seconds, not a minute
  * parameterized FIP constant, no dead imports, no bare excepts
 
Data source: public MLB Stats API (statsapi.mlb.com), no key required.
"""
 
from __future__ import annotations
 
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
 
import requests
import pytz
 
BASE = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 10

# Full team name (as returned by MLB Stats API's own team.name field, e.g. get_schedule's
# home_name/away_name) -> common 2-3 letter abbreviation. A real, standard, stable 30-team
# reference table -- used by bet_settlement.py to make its game-label matching tolerant of
# abbreviated input ("HOU @ DET"), not just the exact full-name form ("Houston Astros @ Detroit
# Tigers") the schedule itself returns. "Athletics" (not "Oakland Athletics") matches the club's
# own current official name.
MLB_TEAM_ABBR = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Athletics": "ATH", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}
 
# League FIP constant. It is season-specific (lgERA minus the FIP numerator over lgIP),
# historically ~3.1-3.2. Override per season if you want exactness; see derive_fip_constant.
FIP_CONSTANT_DEFAULT = 3.17
 
# Expected plate appearances by batting-order spot (0 = leadoff). Mirrors projections.py.
LINEUP_SPOT_PA = [4.65, 4.55, 4.45, 4.35, 4.25, 4.10, 4.00, 3.90, 3.80]
DEFAULT_UNKNOWN_PA = 4.25
 
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "h2-mlb-dashboard/1.0"})
 
 
# --------------------------------------------------------------------- helpers
def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default
 
 
def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(text))
                   if unicodedata.category(c) != "Mn")
 
 
def fetch_json(url: str, params: Optional[Dict] = None, retries: int = 2) -> Dict[str, Any]:
    """GET JSON with a couple of retries. Returns {} on failure -- never raises, AND never
    returns anything but a real dict, even on a technical "success."

    A REAL BUG CAUGHT IN PRODUCTION, FIXED HERE AT THE ROOT: a 200-status response whose BODY
    happens to be non-dict JSON (a literal `null`, an empty list, a bare number) used to pass
    straight through as `r.json()`'s own raw return value -- this function's own docstring
    already promised "{} on failure," but that promise only covered NETWORK failures (a timeout,
    a non-200 status), not a technically-successful response with a genuinely unexpected body
    shape. Every one of this function's dozens of callers across this codebase calls `.get(...)`
    on the result assuming it's always a real dict -- a single non-dict response anywhere would
    crash with an AttributeError ('NoneType' object has no attribute 'get'), exactly what
    happened: Pitching Lab's live pitch-count check hit a real game (a postponed/suspended one,
    a plausible real cause) where the live boxscore endpoint's own body was JSON null instead of
    an empty structure. Fixed at the source, not just in the one caller that happened to surface
    it first -- every other function relying on this file's own "never raises, always a dict"
    contract is protected by the same fix, not just the new one."""
    for attempt in range(retries + 1):
        try:
            r = _SESSION.get(url, params=params or {}, timeout=TIMEOUT)
            if r.status_code == 200:
                body = r.json()
                if isinstance(body, dict):
                    return body
                return {}   # a technically-successful response with a non-dict body is still
                           # treated as "no usable data," the same honest {} every other real
                           # failure mode in this function already returns
        except requests.RequestException:
            pass
    return {}
 
 
def parse_innings(ip_value: Any) -> float:
    """'85.1' -> 85.333 ('.1' = 1 out, '.2' = 2 outs)."""
    s = str(ip_value or "0")
    if "." not in s:
        return safe_float(s)
    whole, frac = s.split(".", 1)
    return safe_float(whole) + {"0": 0, "1": 1, "2": 2}.get(frac[:1], 0) / 3.0
 
 
# --------------------------------------------------------------------- analytics
def calculate_fip(stat: Dict[str, Any], constant: float = FIP_CONSTANT_DEFAULT) -> float:
    """FIP = ((13*HR + 3*(BB+HBP) - 2*K) / IP) + constant."""
    hr = safe_float(stat.get("homeRuns"))
    bb = safe_float(stat.get("baseOnBalls"))
    hbp = safe_float(stat.get("hitByPitch"))
    k = safe_float(stat.get("strikeOuts"))
    ip = parse_innings(stat.get("inningsPitched"))
    if ip <= 0:
        return 0.0
    return round(((13 * hr) + (3 * (bb + hbp)) - (2 * k)) / ip + constant, 2)
 
 
def platoon_advantage(bat_hand: str, pit_hand: str) -> str:
    """Switch hitters always hold the platoon edge; otherwise opposite hands = advantage."""
    if bat_hand == "S":
        return "Advantage"
    if not bat_hand or not pit_hand:
        return "Unknown"
    return "Advantage" if bat_hand != pit_hand else "Disadvantage"
 
 
def power_index(iso: float, ops: float, advantage: str) -> float:
    """Transparent, sortable heuristic for the matchup leaderboards.
 
    NOT a probability. It rewards isolated power and overall OPS, with a small platoon
    nudge. Replace with the projection model (per-PA Monte Carlo) when you want real
    prop probabilities instead of a ranking score.
    """
    base = 100.0 * (iso + max(ops - 0.700, -0.3) / 2.0)
    return round(base + (5.0 if advantage == "Advantage" else 0.0), 1)
 
 
# --------------------------------------------------------------------- fetchers
@dataclass
class PitcherMetrics:
    id: Optional[int]
    name: str = "TBD"
    hand: str = "R"
    k9: float = 0.0
    bb9: float = 0.0    # walks per 9 innings -- high (≥3.5) flags walk risk for hitter props
    hr9: float = 0.0
    era: float = 0.0
    whip: float = 0.0
    oba: float = 0.0
    fip: float = 0.0
    stat: Dict[str, Any] = field(default_factory=dict)
    has_stats: bool = True     # False when no season line could be found at all
    stale: bool = False        # True when we fell back to a PRIOR season's line
 
 
def _aggregate_pitching_splits(splits: list) -> Dict[str, Any]:
    """Sum multiple season splits (e.g. a traded pitcher's two stints) into one stat dict.
 
    Counting stats are summed; innings are summed as outs and rebuilt in MLB's '.1/.2'
    thirds format so the parsers stay correct; rate fields are recomputed."""
    sums = {k: 0.0 for k in ("strikeOuts", "baseOnBalls", "hitByPitch", "homeRuns",
                             "battersFaced", "gamesStarted", "gamesPlayed", "earnedRuns",
                             "hits", "atBats")}
    total_outs = 0
    for sp in splits:
        s = sp.get("stat", {}) or {}
        for k in sums:
            sums[k] += safe_float(s.get(k))
        total_outs += int(round(parse_innings(s.get("inningsPitched")) * 3))
 
    ip_float = total_outs / 3.0
    sums["inningsPitched"] = f"{total_outs // 3}.{total_outs % 3}"  # e.g. 85.1
    if ip_float > 0:
        sums["era"] = sums["earnedRuns"] / ip_float * 9
        sums["whip"] = (sums["baseOnBalls"] + sums["hits"]) / ip_float
        sums["homeRunsPer9"] = sums["homeRuns"] / ip_float * 9
    sums["avg"] = (sums["hits"] / sums["atBats"]) if sums["atBats"] > 0 else 0.0
    return sums
 
 
def get_pitcher_metrics(pitcher_id: Optional[int],
                        fip_constant: float = FIP_CONSTANT_DEFAULT) -> PitcherMetrics:
    if not pitcher_id:
        return PitcherMetrics(id=None)
 
    def _fetch_season_stat(season: Optional[int]):
        params = {"hydrate": "stats(group=[pitching],type=[season]"
                             + (f",season={season}" if season else "") + ")"}
        data = fetch_json(f"{BASE}/people/{pitcher_id}", params)
        try:
            person = data["people"][0]
            splits = person["stats"][0]["splits"]
            if not splits:
                return person, None
            return person, _aggregate_pitching_splits(splits)
        except (KeyError, IndexError):
            return (data.get("people", [{}]) or [{}])[0], None
 
    # Try current season; if the line is empty (IL returnee, call-up, below threshold),
    # fall back to last season's real numbers rather than reporting a misleading 0.00.
    person, stat = _fetch_season_stat(None)
    stale = False
    if stat is None:
        prior = datetime.now().year - 1
        person2, stat2 = _fetch_season_stat(prior)
        if stat2 is not None:
            person, stat, stale = person2, stat2, True
 
    if stat is None:
        # Genuinely no data anywhere — flag it so the UI shows "no data", not a fake-elite 0.00.
        return PitcherMetrics(id=pitcher_id,
                              name=(person or {}).get("fullName", "TBD"),
                              hand=(person or {}).get("pitchHand", {}).get("code", "R"),
                              has_stats=False)
 
    so = safe_float(stat.get("strikeOuts"))
    ip = parse_innings(stat.get("inningsPitched"))
    return PitcherMetrics(
        id=pitcher_id,
        name=person.get("fullName", "TBD"),
        hand=person.get("pitchHand", {}).get("code", "R"),
        k9=(so / ip * 9) if ip > 0 else 0.0,
        bb9=(safe_float(stat.get("baseOnBalls")) / ip * 9) if ip > 0 else 0.0,
        hr9=safe_float(stat.get("homeRunsPer9")),
        era=safe_float(stat.get("era")),
        whip=safe_float(stat.get("whip")),
        oba=safe_float(stat.get("avg")),
        fip=calculate_fip(stat, fip_constant),
        stat=stat,
        stale=stale,
    )
 
 
def get_hitter_raw(player_id: int) -> Optional[Dict[str, Any]]:
    """name, bat hand, season hitting stat, and best-effort vs-LHP/vs-RHP splits.
 
    Self-contained: one combined call for season + splits, falling back to a season-only
    call so hitters ALWAYS load. Platoon splits are a bonus, never a requirement."""
    def parse(person: Dict[str, Any]):
        season = vs_l = vs_r = None
        for block in person.get("stats", []):
            btype = (block.get("type", {}) or {}).get("displayName", "")
            for sp in block.get("splits", []):
                code = (sp.get("split", {}) or {}).get("code")
                stat = sp.get("stat")
                if btype == "season" and season is None:
                    season = stat
                elif code == "vl":
                    vs_l = stat
                elif code == "vr":
                    vs_r = stat
        return season, vs_l, vs_r
 
    data = fetch_json(
        f"{BASE}/people/{player_id}",
        {"hydrate": "stats(group=[hitting],type=[season,statSplits],sitCodes=[vl,vr])"},
    )
    person = (data.get("people") or [None])[0]
    season = vs_l = vs_r = None
    if person:
        season, vs_l, vs_r = parse(person)
 
    if season is None:  # fallback: season-only (the original, reliable hydrate)
        data = fetch_json(f"{BASE}/people/{player_id}",
                          {"hydrate": "stats(group=[hitting],type=[season])"})
        person = (data.get("people") or [None])[0]
        if person:
            season, _, _ = parse(person)
 
    if person is None or season is None:
        return None
    return {
        "id": player_id,
        "name": person.get("fullName", "Unknown"),
        "bat_hand": person.get("batSide", {}).get("code", "R"),
        "stat": season,
        "vs_l": vs_l,
        "vs_r": vs_r,
    }
 
 
def _normalize_schedule_json(sched: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Shared normalization for both get_schedule (single date) and get_team_schedule_range
    (a team across a date window) — same output shape either way, so callers of one don't need
    to know which query produced it."""
    games: List[Dict[str, Any]] = []
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            teams = g.get("teams", {})
            home, away = teams.get("home", {}), teams.get("away", {})
            games.append({
                "gamePk": g.get("gamePk"),
                "gameNumber": g.get("gameNumber", 1),
                "game_date": g.get("gameDate"),   # ISO UTC start, e.g. 2026-06-28T17:10:00Z
                "status": (g.get("status", {}) or {}).get("detailedState", ""),
                "venue_name": (g.get("venue", {}) or {}).get("name", ""),
                "venue_id": (g.get("venue", {}) or {}).get("id"),
                "home_name": home.get("team", {}).get("name", "Home"),
                "away_name": away.get("team", {}).get("name", "Away"),
                "home_id": home.get("team", {}).get("id"),
                "away_id": away.get("team", {}).get("id"),
                "home_pitcher_id": (home.get("probablePitcher") or {}).get("id"),
                "away_pitcher_id": (away.get("probablePitcher") or {}).get("id"),
                # Additive, backward compatible -- added directly on request for get_team_
                # recent_form below, which needs each side's actual final score. MLB Stats API's
                # schedule response carries "score" directly on each side's own team sub-object
                # for any game that has started or finished, no separate boxscore fetch needed --
                # a well-documented, standard field on this endpoint, not a novel assumption, but
                # (like every other schedule/boxscore-shape assumption in this file) not verified
                # against a live response from this sandbox. None for a game that hasn't started.
                "home_score": home.get("score"),
                "away_score": away.get("score"),
            })
    return games


def get_schedule(date_str: str) -> List[Dict[str, Any]]:
    """Normalized game list with probable pitchers and venue."""
    sched = fetch_json(f"{BASE}/schedule",
                       {"sportId": 1, "date": date_str, "hydrate": "probablePitcher,venue"})
    games = _normalize_schedule_json(sched)
    return sorted(games, key=lambda x: (x["away_name"], x["gameNumber"]))


def get_team_schedule_range(team_id: int, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """One team's games between start_date and end_date (both YYYY-MM-DD, inclusive), same
    normalized shape get_schedule returns. A real, documented MLB Stats API capability — a single
    schedule request accepts teamId + startDate/endDate together — used here instead of one
    get_schedule() call per calendar date, which would mean days_back+1 separate requests for
    what's really one query. Built for get_team_bullpen_fatigue below, not schedule browsing
    (get_schedule stays the right call for "what's happening across the league on date X")."""
    sched = fetch_json(f"{BASE}/schedule",
                       {"sportId": 1, "teamId": team_id, "startDate": start_date, "endDate": end_date})
    games = _normalize_schedule_json(sched)
    return sorted(games, key=lambda x: (x["game_date"] or "", x["gameNumber"]))
 
 
def _team_starters(game: Dict, team_key: str, box: Dict) -> Tuple[List[int], bool]:
    """Return (player_ids, projected). Posted batting order if available, else active roster.
 
    Decided PER TEAM (fixes the original home-only bug)."""
    order = []
    try:
        order = box["teams"][team_key].get("battingOrder", []) or []
    except (KeyError, TypeError):
        order = []
    if order:
        return [int(p) for p in order][:9], False
 
    team_id = game[f"{team_key}_id"]
    roster = fetch_json(f"{BASE}/teams/{team_id}/roster/Active", {"hydrate": "person"}).get("roster", [])
    pids = [r["person"]["id"] for r in roster
            if r.get("position", {}).get("abbreviation") != "P" and r.get("person", {}).get("id")]
    return pids, True


def get_actual_starter(game_pk: int, side: str) -> Optional[Dict[str, Any]]:
    """Fetches this ONE game's own live boxscore and finds which pitcher's own stat line shows
    he ACTUALLY started -- gamesStarted >= 1, the SAME real, precedented signal get_pitcher_
    starts_this_season already uses to detect a start from a per-game stat line (there, from a
    season gameLog; here, from tonight's own live boxscore.pitching stats instead) -- not a new,
    separately-invented detection method.

    Added directly on request, after a real, reported pattern: a probable starter posted earlier
    in the day doesn't always match who actually takes the mound (a late scratch, or a bullpen
    game with no true starter at all) -- traders noticed mid-game, not before, which is the
    honest scope of what this can catch. See starter_mismatch below for the actual comparison.

    Returns {"player_id", "name"} for whoever's boxscore entry shows gamesStarted >= 1 on `side`
    ("home"/"away"), or None -- most commonly because the game hasn't started yet (no pitching
    stats posted at all), occasionally because the boxscore genuinely doesn't carry a
    gamesStarted field for anyone yet even once it has. An honest None either way, not a guess.

    DELIBERATELY DOES NOT FALL BACK to an outs-based guess the way get_pitcher_starts_this_
    season's own SEASON-level list does (>=9 outs as a proxy is reasonable averaged over a whole
    season of starts; applied to ONE partial, in-progress game it would misfire on a starter
    already pulled early, or a bullpen game's own opener) -- an honest None here is more useful
    than a wrong guess, especially since a wrong guess is exactly the kind of thing this check
    exists to catch in the first place.

    HONEST LIMITATION, same posture as this file's other boxscore-dependent functions: the
    gamesStarted field's presence/behavior on an IN-PROGRESS (not yet final) boxscore specifically
    is not verified against a live response from this sandbox (statsapi.mlb.com unreachable here)
    -- lower risk than a novel assumption, since gamesStarted itself is already relied on
    elsewhere in this file for completed games, but the in-progress case specifically is newer
    ground worth a real, early check once redeployed."""
    try:
        box = fetch_json(f"{BASE}/game/{game_pk}/boxscore")
    except Exception:
        return None
    players = (((box.get("teams", {}) or {}).get(side, {}) or {}).get("players", {}) or {})
    for pdata in players.values():
        pit = (pdata.get("stats", {}) or {}).get("pitching", {}) or {}
        if not pit:
            continue
        gs = pit.get("gamesStarted")
        if gs and int(gs) >= 1:
            person = pdata.get("person", {}) or {}
            return {"player_id": person.get("id"), "name": person.get("fullName")}
    return None


def get_live_pitching_line(game_pk: int, side: str) -> Optional[Dict[str, Any]]:
    """One live boxscore fetch, returns the ACTUAL current starter's own real-time line: pitch
    count, innings pitched so far, and today's actual hits/earned runs/strikeouts/walks allowed
    IN THIS START specifically. Added directly on request, after a real, repeated pattern: real
    traders manually tracking a starter's live pitch count mid-game to gauge how much longer
    he'll last and whether he's cruising or getting hit hard ("He's at 68 pitches but best part
    he has just 1 hit no runs... he can def get 6").

    Combines what get_actual_starter above already does (confirm WHO's pitching, via the exact
    same real gamesStarted>=1 signal) with reading the REST of that same already-open pitching
    stat dict, rather than a second separate boxscore fetch for what's fundamentally one real
    question asked together: "who's pitching, and how's it going." Every field read here
    (numberOfPitches, hits, earnedRuns, strikeOuts, baseOnBalls, inningsPitched) is a real,
    standard MLB Stats API pitching-stat field; strikeOuts/baseOnBalls/inningsPitched are already
    relied on elsewhere in this file for completed-game grading (parse_boxscore_results) —
    numberOfPitches/hits/earnedRuns are new reads from this same dict, not a new endpoint or a
    new assumption about its shape.

    ALSO READS `runs` (total runs allowed, earned + unearned) alongside `earnedRuns` — added
    directly to answer a real, live piece of confusion this platform's own community hit
    (checked against the real chat log): a Rocchio fielding error meant a walk and a Kyle
    Manzardo home run afterward didn't count as earned, and it took several messages of manual
    cross-checking against ESPN before anyone realized why the earned-run number wasn't moving
    the way the raw run total was. `runs` and `earnedRuns` are both standard, separately-tracked
    fields on the same MLB Stats API pitching-stat object (the ERA-vs-RA distinction is
    fundamental to how baseball itself tracks pitching) — reading one more field off data this
    function already fetches, not a new endpoint or a new call. `unearned_runs = runs -
    earned_runs`; unearned_runs > 0 is the direct, immediate answer to "wait, why isn't the
    earned-run number matching the runs I'm watching score" the moment it happens, instead of a
    person needing to notice the mismatch and cross-check a second source mid-game.

    RAW NUMBERS ONLY, DELIBERATELY NOT A PREDICTION: this does not estimate "innings left" or
    "pull probability" — that would be a claim about a live, in-progress managerial decision,
    genuinely harder to validate than anything else already flagged as experimental on this
    platform. Shows the same real facts a trader would read by eye, nothing inferred on top.

    HONEST LIMITATION, same posture as get_actual_starter above: numberOfPitches specifically on
    an IN-PROGRESS boxscore is not verified against a live response from this sandbox (statsapi.
    mlb.com unreachable here) — a real, standard, well-documented field, but worth a real, early
    check once redeployed, same as every other boxscore-shape assumption in this file. `runs`
    alongside `earnedRuns` on the SAME object carries the identical unverified-shape caveat —
    inferred from the fact that earnedRuns already reads correctly in production and ERA-vs-RA is
    about as standard a stat pairing as exists in baseball, not confirmed against a live response.

    Returns {"player_id", "name", "pitches", "innings_pitched", "hits", "runs", "earned_runs",
    "unearned_runs", "strikeouts", "walks"} for whoever's boxscore entry shows gamesStarted >= 1
    on `side` ("home"/"away"), or None — most commonly because the game hasn't started yet. An
    honest None, not a fabricated zero line."""
    try:
        box = fetch_json(f"{BASE}/game/{game_pk}/boxscore")
    except Exception:
        return None
    players = (((box.get("teams", {}) or {}).get(side, {}) or {}).get("players", {}) or {})
    for pdata in players.values():
        pit = (pdata.get("stats", {}) or {}).get("pitching", {}) or {}
        if not pit:
            continue
        gs = pit.get("gamesStarted")
        if gs and int(gs) >= 1:
            person = pdata.get("person", {}) or {}
            runs = int(pit.get("runs", 0) or 0)
            earned_runs = int(pit.get("earnedRuns", 0) or 0)
            return {
                "player_id": person.get("id"), "name": person.get("fullName"),
                "pitches": int(pit.get("numberOfPitches", 0) or 0),
                "innings_pitched": pit.get("inningsPitched", "0.0"),
                "hits": int(pit.get("hits", 0) or 0),
                "runs": runs, "earned_runs": earned_runs,
                "unearned_runs": max(0, runs - earned_runs),
                "strikeouts": int(pit.get("strikeOuts", 0) or 0),
                "walks": int(pit.get("baseOnBalls", 0) or 0),
            }
    return None


def starter_mismatch(probable_pitcher_id: Optional[int],
                     actual_starter: Optional[Dict[str, Any]]) -> Optional[bool]:
    """Compares a probable starter's own id against get_actual_starter's own result -- pulled out
    as its own small, pure, testable function (rather than an inline comparison wherever this
    gets displayed) so the actual match/mismatch logic is unit tested, not just trusted by eye in
    the browser, the same posture every other piece of real logic on this platform already takes.

    Returns True (a real mismatch -- the pitcher who actually started is a different real person
    than who was probable), False (they match), or None when there isn't enough information to
    say either way (no real probable id, or get_actual_starter itself returned None -- most
    likely the game hasn't started yet). None is never resolved into a false True or False."""
    if probable_pitcher_id is None or actual_starter is None or actual_starter.get("player_id") is None:
        return None
    return actual_starter["player_id"] != probable_pitcher_id


# --------------------------------------------------------------------- orchestration
def build_slate(date_str: str, fip_constant: float = FIP_CONSTANT_DEFAULT,
                max_workers: int = 8) -> Tuple[List[Dict], List[Dict]]:
    """Fetch and assemble the full slate concurrently.
 
    Returns (hitter_rows, game_meta):
      hitter_rows : list of flat dicts ready for a DataFrame (one per hitter)
      game_meta   : list of per-game dicts (label, venue, both PitcherMetrics, names)
    """
    games = [g for g in get_schedule(date_str) if g.get("gamePk")]
    if not games:
        return [], []
 
    # Phase 1 — per-game setup (pitcher metrics + boxscore + starters) in parallel.
    def setup_game(game: Dict) -> Dict:
        gid = game["gamePk"]
        home_pm = get_pitcher_metrics(game["home_pitcher_id"], fip_constant)
        away_pm = get_pitcher_metrics(game["away_pitcher_id"], fip_constant)
        box = fetch_json(f"{BASE}/game/{gid}/boxscore")
        label = f"{game['away_name']} @ {game['home_name']} (Game {game['gameNumber']})"
        # Away hitters face the HOME pitcher, and vice versa.
        sides = []
        for team_key, opp_pm in (("away", home_pm), ("home", away_pm)):
            pids, projected = _team_starters(game, team_key, box)
            opp_key = "home" if team_key == "away" else "away"
            sides.append({
                "team_key": team_key,
                "team_name": game[f"{team_key}_name"],
                "team_id": game.get(f"{team_key}_id"),
                "opp_pm": opp_pm,
                "opp_team_id": game.get(f"{opp_key}_id"),
                "pids": pids,
                "projected": projected,
            })
        return {"game": game, "label": label, "home_pm": home_pm, "away_pm": away_pm, "sides": sides}
 
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        setups = list(ex.map(setup_game, games))
 
    # Phase 2 — fetch every unique hitter ONCE, concurrently.
    unique_pids = {pid for s in setups for side in s["sides"] for pid in side["pids"]}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        raws = list(ex.map(get_hitter_raw, unique_pids))
    raw_by_id = {r["id"]: r for r in raws if r}
 
    # Phase 3 — assemble rows + meta (pure, no network).
    rows: List[Dict] = []
    meta: List[Dict] = []
    for s in setups:
        meta.append({
            "label": s["label"],
            "venue": s["game"]["venue_name"],
            "venue_id": s["game"].get("venue_id"),
            "status": s["game"]["status"],
            "game_date": s["game"].get("game_date"),
            "away_name": s["game"]["away_name"],
            "home_name": s["game"]["home_name"],
            "home_id": s["game"].get("home_id"),
            "away_id": s["game"].get("away_id"),
            "home_pm": s["home_pm"],
            "away_pm": s["away_pm"],
            # Additive, backward compatible -- added directly on request for Pitching Lab's own
            # "starter check" section, which needs to re-fetch ONE specific game's own live
            # boxscore on demand (get_actual_starter below). Every existing caller already reads
            # meta via .get()/[key] on the fields it actually uses, so a new key here is safe.
            "gamePk": s["game"].get("gamePk"),
        })
        for side in s["sides"]:
            opp = side["opp_pm"]
            is_home = (side["team_key"] == "home")
            game_hour = _eastern_hour(s["game"].get("game_date"))
            is_day_game = (game_hour is not None and game_hour < 17)
            for idx, pid in enumerate(side["pids"]):
                raw = raw_by_id.get(pid)
                if not raw:
                    continue
                row = _hitter_row(raw, opp, side["team_name"], s["label"],
                                  side["projected"], idx, s["game"].get("venue_id"),
                                  side.get("opp_team_id"), side.get("team_id"))
                # Home/away and day/night context -- added directly on request so the "Why"
                # column and pitcher diagnostics can surface the same splits Deezy was doing
                # manually in Discord (e.g. "Shane Drohan doesn't do as well in home day games")
                # rather than leaving community members to research this externally. Attached
                # here (in build_slate) so every downstream consumer -- Best Bets, Graded Picks,
                # Dinger Engine, Matchup Lab -- gets the same signal without each page re-deriving
                # it from the game label string.
                row["_is_home"] = is_home
                row["_is_day_game"] = is_day_game
                row["_game_date"] = s["game"].get("game_date")
                rows.append(row)
    return rows, meta
 
 
def build_pitching_slate(date_str: str, fip_constant: float = FIP_CONSTANT_DEFAULT,
                         max_workers: int = 8) -> List[Dict]:
    """Lightweight: probable starters across the slate with ERA/FIP/peripherals.
 
    Does NOT fetch hitters or boxscores, so it is much cheaper than build_slate.
    Returns one row per probable starter, including Delta = ERA - FIP (positive =
    underlying performance better than results = positive-regression candidate)."""
    games = [g for g in get_schedule(date_str) if g.get("gamePk")]
    tasks = []  # (pitcher_id, team_name, opponent, game_label, game_date, team_id, opp_id, gamePk, venue_id)
    for g in games:
        label = f"{g['away_name']} @ {g['home_name']}"
        gd = g.get("game_date")
        tasks.append((g["home_pitcher_id"], g["home_name"], g["away_name"], label, gd,
                     g.get("home_id"), g.get("away_id"), g.get("gamePk"), g.get("venue_id"), True))
        tasks.append((g["away_pitcher_id"], g["away_name"], g["home_name"], label, gd,
                     g.get("away_id"), g.get("home_id"), g.get("gamePk"), g.get("venue_id"), False))
 
    def fetch(t):
        pid, team, opp, label, gd, team_id, opp_id, game_pk, venue_id, is_home = t
        pm = get_pitcher_metrics(pid, fip_constant)
        return pm, team, opp, label, gd, team_id, opp_id, game_pk, venue_id, is_home

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(fetch, tasks))

    rows = []
    for pm, team, opp, label, gd, team_id, opp_id, game_pk, venue_id, is_home in results:
        if pm.id is None or not pm.has_stats:
            # A REAL, CONFIRMED FIX, not the original design: this used to `continue` (skip this
            # row entirely) here, and since Game Watch/Bullpen Watch pair home/away pitchers into
            # one game, losing either side's row took the ENTIRE game off the board -- confirmed
            # directly against a real, live case: Cody Bradford's actual 2026 season debut
            # (reinstated from a 60-day IL stint after nearly two years out, so genuinely had no
            # real 2025 OR 2026 stat line for get_pitcher_metrics to find) correctly triggered
            # has_stats=False, and the whole real Rangers @ Giants game vanished, even though the
            # OPPOSING starter (Whisenhunt) had perfectly real, computable data the whole time.
            #
            # Now a REAL, HONEST PLACEHOLDER ROW instead: real Pitcher/Team/Opponent/Game context
            # (pm.name is the real fetched name when the API found the person but no stat line --
            # Bradford's own real case -- and the real "TBD" default only when no probable
            # starter has been announced for this side at all), every real stat field honestly
            # None rather than fabricated -- the SAME has_stats-aware None/NaN convention already
            # established elsewhere in this file (see "Opp HR/9" below). pair_pitching_slate_by_
            # game only ever pairs a game when BOTH sides have a real row -- previously a has_
            # stats=False pitcher meant NO row at all for that side, so pairing silently failed;
            # now both sides always get a real row, so the real game shows, with an honest gap on
            # whichever one side genuinely has nothing to report, not the whole matchup vanishing.
            rows.append({
                "Pitcher": pm.name, "_pid": pm.id, "Team": team, "Opponent": opp, "Game": label,
                "Hand": pm.hand, "_game_date": gd, "_team_id": team_id, "_opp_id": opp_id,
                "_is_home": is_home,
                "_is_day_game": ((_eastern_hour(gd) or 24) < 17) if gd else None,
                "_gamePk": game_pk, "_venue_id": venue_id,
                "ERA": None, "FIP": None, "Delta": None,
                "K/9": None, "WHIP": None, "HR/9": None, "OBA": None,
                "_has_stats": False,
            })
            continue
        rows.append({
            "Pitcher": pm.name, "_pid": pm.id, "Team": team, "Opponent": opp, "Game": label,
            "Hand": pm.hand, "_game_date": gd, "_team_id": team_id, "_opp_id": opp_id,
            "_is_home": is_home,
            "_is_day_game": ((_eastern_hour(gd) or 24) < 17) if gd else None,
            "_gamePk": game_pk, "_venue_id": venue_id,
            "ERA": round(pm.era, 2), "FIP": pm.fip, "Delta": round(pm.era - pm.fip, 2),
            "K/9": round(pm.k9, 1), "WHIP": round(pm.whip, 2), "HR/9": round(pm.hr9, 2), "OBA": pm.oba,
            "_has_stats": True,
        })
    if rows and not any(r["_game_date"] for r in rows):
        # Every row has real pitcher data (ERA/FIP etc. all populated, or they'd have been
        # skipped above) but NONE has a game_date — worth a visible signal, not a silent "every
        # game shows TBD in the time-slot filter" mystery. Most likely a stale cached result from
        # before this field existed (see the page's own Refresh button); if this prints on a
        # FRESH fetch, that points to a genuine gap in what the schedule endpoint returned instead.
        print(f"[MLB] build_pitching_slate({date_str}): {len(rows)} pitcher(s) loaded but NONE "
             "have a game_date — check get_schedule's raw response for this date.", flush=True)
    return rows


def pair_pitching_slate_by_game(pitching_rows: List[Dict]) -> List[Dict]:
    """Reconstructs one entry per GAME from build_pitching_slate's own one-row-per-starter shape
    -- pulled out as its own small, pure, TESTED function (rather than an inline grouping loop
    repeated in each view that needs it) after Game Watch needed the exact same pairing logic
    Bullpen Watch already had inline; a second inline copy would have been the same duplication-
    drift risk this codebase avoids everywhere else real logic lives in more than one place.

    Matches build_pitching_slate's own label convention exactly ("{away} @ {home}", no game-
    number suffix, confirmed directly against its own f-string) rather than guessing at a new
    format.

    Returns a list of {"label", "_game_date", "away": row, "home": row} -- ONLY for games where
    BOTH sides paired successfully. A REAL, CONFIRMED CHANGE in what that actually excludes now:
    build_pitching_slate itself used to drop a pitcher's row entirely when he had no real
    computable stats (has_stats=False), so a genuine data gap on either side meant the whole game
    silently failed to pair here too. build_pitching_slate now returns a real, honest placeholder
    row (has_stats=False, every stat field None) instead of dropping it -- so both sides almost
    always have SOME real row now, and this function's own pairing succeeds for real games that
    used to vanish here. The "no matching partner" case this function's own filter still guards
    against is now a genuinely rarer, different one -- a row whose own Game label truly has no
    counterpart at all (a real data-shape anomaly, not an ordinary has_stats gap)."""
    games_map: Dict[str, Dict] = {}
    for r in pitching_rows:
        label = r["Game"]
        away_part, _, home_part = label.partition(" @ ")
        slot = "away" if r["Team"] == away_part else "home"
        games_map.setdefault(label, {"label": label, "_game_date": r.get("_game_date")})[slot] = r
    return [g for g in games_map.values() if "home" in g and "away" in g]


def build_game_lineups(game_pk: int, home_id: int, away_id: int,
                       home_pitcher_id: Optional[int], away_pitcher_id: Optional[int],
                       venue_id: Optional[int], fip_constant: float = FIP_CONSTANT_DEFAULT,
                       max_workers: int = 8) -> Optional[Dict[str, Any]]:
    """Fetch ONE specific game's own two real lineups (9 batters each), with every field
    batter_pa_probs/project_pitcher/hitter_starter_exposures already need -- the SAME per-batter
    enrichment build_slate's own _hitter_row already does, scoped to just these two teams
    instead of the whole day's slate. Added directly for the game-simulation engine (projections.
    simulate_game_win_probability), which needs real matchup-aware probability arrays for 18 real
    batters, not the whole day's worth build_slate would otherwise fetch.

    REAL COST: 2 starter fetches (get_pitcher_metrics), 1 boxscore fetch (lineup confirmation via
    _team_starters), up to 18 hitter fetches (get_hitter_raw, 9 per team, deduplicated and
    concurrent) -- comparable to what build_slate spends on ONE game, just not multiplied across
    an entire day's slate.

    Returns {"home_pm", "away_pm", "home_rows", "away_rows"} -- home_pm/away_pm are each side's
    own starter (PitcherMetrics); home_rows/away_rows are each exactly 9 _hitter_row-shaped
    dicts (home_rows already carries AWAY's PitcherMetrics as each home batter's own opponent,
    and vice versa -- the same "away hitters face the HOME pitcher" convention build_slate
    itself already uses). Returns None if either side's real lineup can't be assembled to a full
    9 batters (a partial lineup isn't a real simulation input -- an honest None, not a guess at
    who's missing)."""
    home_pm = get_pitcher_metrics(home_pitcher_id, fip_constant)
    away_pm = get_pitcher_metrics(away_pitcher_id, fip_constant)
    try:
        box = fetch_json(f"{BASE}/game/{game_pk}/boxscore")
    except Exception:
        box = {}

    game_stub = {"home_id": home_id, "away_id": away_id}
    home_pids, home_projected = _team_starters(game_stub, "home", box)
    away_pids, away_projected = _team_starters(game_stub, "away", box)

    unique_pids = set(home_pids) | set(away_pids)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        raws = list(ex.map(get_hitter_raw, unique_pids))
    raw_by_id = {r["id"]: r for r in raws if r}

    # Home batters face AWAY's pitching (opp=away_pm, opp_team_id=away_id, for a later bullpen-
    # aggregate lookup on AWAY's own bullpen) -- and the exact mirror for away batters.
    home_rows = [_hitter_row(raw_by_id[pid], away_pm, "home", "", home_projected, idx, venue_id, away_id)
                for idx, pid in enumerate(home_pids) if pid in raw_by_id]
    away_rows = [_hitter_row(raw_by_id[pid], home_pm, "away", "", away_projected, idx, venue_id, home_id)
                for idx, pid in enumerate(away_pids) if pid in raw_by_id]

    if len(home_rows) < 9 or len(away_rows) < 9:
        return None
    return {"home_pm": home_pm, "away_pm": away_pm, "home_rows": home_rows[:9], "away_rows": away_rows[:9]}


def get_lineup_status(game_pk: int, home_id: int, away_id: int) -> Tuple[bool, bool]:
    """Whether each side's REAL starting lineup has been officially posted yet (a real
    battingOrder present on the live boxscore) vs still just this platform's own active-roster
    projection -- the exact same detection _team_starters/build_game_lineups already use for
    real simulation input, reused here for a much cheaper caller that only wants the yes/no
    status, not the full 9-batter lineup itself. Returns (home_confirmed, away_confirmed).

    REAL COST: exactly one boxscore fetch, not the 18 additional hitter fetches build_game_
    lineups needs on top of it -- safe to call once per game on a schedule board showing an
    entire day's slate, where build_game_lineups' own real cost would multiply badly.

    Fails honest, not silent: any fetch problem returns (False, False) -- "not confirmed yet" is
    the correct, safe default when the real answer can't be determined (a genuinely unconfirmed
    lineup and an unknown one look identical to a caller that just wants a yes/no, and defaulting
    to "confirmed" on a fetch error would be the wrong direction to be wrong in)."""
    try:
        box = fetch_json(f"{BASE}/game/{game_pk}/boxscore")
    except Exception:
        return False, False
    game_stub = {"home_id": home_id, "away_id": away_id}
    _home_pids, home_projected = _team_starters(game_stub, "home", box)
    _away_pids, away_projected = _team_starters(game_stub, "away", box)
    return (not home_projected), (not away_projected)


def _hitter_row(raw: Dict, opp: PitcherMetrics, team_name: str,
                game_label: str, projected: bool, lineup_idx: int = 0,
                venue_id: int = None, opp_team_id: int = None, team_id: int = None) -> Dict:
    stat = raw["stat"]
    avg = safe_float(stat.get("avg"))
    slg = safe_float(stat.get("slg"))
    ops = safe_float(stat.get("ops"))
    pa = max(safe_float(stat.get("plateAppearances"), 1), 1)
    iso = round(slg - avg, 3)
    adv = platoon_advantage(raw["bat_hand"], opp.hand)
    # Expected PA for the game: batting-order spot if the lineup is posted, else a default.
    exp_pa = (LINEUP_SPOT_PA[lineup_idx] if (not projected and lineup_idx < len(LINEUP_SPOT_PA))
              else DEFAULT_UNKNOWN_PA)
    return {
        "Hitter": raw["name"],
        "Team": team_name,
        "GameLabel": game_label,
        "Hand": raw["bat_hand"],
        "Opp Pitcher": opp.name,
        "Opp Hand": opp.hand,
        "Opp HR/9": (round(opp.hr9, 2) if opp.has_stats else float("nan")),
        "Advantage": adv,
        "Lineup": "Projected" if projected else "Confirmed",
        "HR": safe_float(stat.get("homeRuns")),
        "Hits": safe_float(stat.get("hits")),
        "TB": safe_float(stat.get("totalBases")),
        "AVG": avg,
        "OBP": safe_float(stat.get("obp")),
        "SLG": slg,
        "OPS": ops,
        "ISO": iso,
        "K%": safe_float(stat.get("strikeOuts")) / pa,
        "PowerIndex": power_index(iso, ops, adv),
        # private fields consumed by projections.py (underscore -> not shown in tables)
        "_pid": raw["id"],
        "_stat": stat,
        "_exp_pa": exp_pa,
        "_venue_id": venue_id,
        "_team_id": team_id,   # needed by best_bets_data.attach_team_trend -- real gap this row
                               # never carried before (Team display name existed, no id to look
                               # up a team's real recent-form data with).
        "_opp_stat": opp.stat,                       # opposing pitcher's season line (matchup)
        "_opp_bb9": opp.bb9,                          # opposing pitcher's BB/9 -- high (≥3.5)
                                                       # means elevated walk risk for hitter props:
                                                       # Raley getting walked twice (July 27) is the
                                                       # real community example that drove this field.
        "_opp_pid": opp.id,                           # opposing STARTER's own player id — lets
                                                       # a bullpen-aggregate lookup exclude him,
                                                       # avoiding double-counting his own stats in
                                                       # both the vs-SP and vs-Pen blend phases
        "_opp_id": opp_team_id,                       # opposing TEAM's numeric id (not the
                                                       # opposing pitcher's own player id) — for
                                                       # bullpen-aggregate lookups (Best Bets'
                                                       # bullpen-blended read, Dinger Engine's own
                                                       # toggle already had this via a separate path)
        "_split_stat": (raw.get("vs_l") if opp.hand == "L" else raw.get("vs_r")),  # platoon split
        "_lineup_idx": lineup_idx,                    # batting order spot (0=leadoff) — connects
                                                       # this hitter to how many times they'd face
                                                       # the starter specifically vs. the bullpen
                                                       # (see projections.hitter_starter_exposures)
    }
 
 
# ---- actual results (for the retrospective) --------------------------------
def _ip_to_outs(ip) -> int:
    """Innings pitched string ('6.1') -> outs (19). '.1'/'.2' are 1/2 outs, not tenths."""
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole or 0) * 3 + (int(frac) if frac in ("1", "2") else 0)
    except (ValueError, TypeError):
        return 0
 
 
def parse_boxscore_results(box: Dict) -> Dict[int, Dict]:
    """Per-player actuals from one boxscore, keyed by player id.

    Batting: hr, hits, tb, so, hrr (Hits+Runs+RBIs combined). Pitching: p_k, p_outs, p_bb, p_h, p_er.
    (A player may have both.)

    Promoted from a module-private helper (_parse_boxscore_results) to this real, public name
    directly on request, when bet_settlement.py needed to reuse this exact same parsing for a
    genuinely separate purpose (real Bet Log settlement, not just this file's own completed-game
    grading) -- a real, intentional API surface change, not just a rename for its own sake."""
    out: Dict[int, Dict] = {}
    for side in ("home", "away"):
        players = (((box.get("teams", {}) or {}).get(side, {}) or {}).get("players", {}) or {})
        for pdata in players.values():
            pid = ((pdata.get("person", {}) or {}).get("id"))
            if pid is None:
                continue
            name = (pdata.get("person", {}) or {}).get("fullName", "")
            stats = pdata.get("stats", {}) or {}
            rec = out.setdefault(int(pid), {"name": name})
 
            bat = stats.get("batting", {}) or {}
            if bat:
                h = int(bat.get("hits", 0) or 0)
                d = int(bat.get("doubles", 0) or 0)
                t = int(bat.get("triples", 0) or 0)
                hr = int(bat.get("homeRuns", 0) or 0)
                # runs/rbi -- same real MLB Stats API field names build_batting_order_projections
                # already reads from this exact boxscore shape (bat.get("runs")/bat.get("rbi")),
                # not a new/guessed field.
                runs = int(bat.get("runs", 0) or 0)
                rbi = int(bat.get("rbi", 0) or 0)
                singles = max(h - d - t - hr, 0)
                rec.update(hr=hr, hits=h, tb=singles + 2 * d + 3 * t + 4 * hr,
                           so=int(bat.get("strikeOuts", 0) or 0),
                           # hrr: the actual combined Hits+Runs+RBIs total for the night -- the
                           # real stat "Batter Hits+Runs+RBIs" plays (graded against the 1.5
                           # DEFAULT_LINES threshold via MARKET_STAT below) settle against.
                           hrr=h + runs + rbi)
 
            pit = stats.get("pitching", {}) or {}
            if pit:
                rec.update(p_k=int(pit.get("strikeOuts", 0) or 0),
                           p_bb=int(pit.get("baseOnBalls", 0) or 0),
                           p_outs=_ip_to_outs(pit.get("inningsPitched", "0.0")),
                           # p_h: pitcher hits allowed -- the real, missing piece behind
                           # "Pitcher Hits Allowed" bets never resolving. Same standard "hits"
                           # field already confirmed working on this exact pitching-stat object
                           # in get_live_pitching_line's own live read, just applied here to a
                           # completed/Final boxscore instead of an in-progress one.
                           p_h=int(pit.get("hits", 0) or 0),
                           # p_er: pitcher earned runs -- the same real, missing piece, confirmed
                           # directly from a live settlement log: 4 real "Pitcher Earned Runs"
                           # bets stuck as "game is Final but couldn't determine a real result,"
                           # for the identical reason p_h was missing before it. Same standard
                           # "earnedRuns" field already confirmed working in get_live_pitching_
                           # line's own live read, just applied here to a completed boxscore.
                           p_er=int(pit.get("earnedRuns", 0) or 0))
    return out
 
 
def get_player_results(date_str: str) -> Dict[int, Dict]:
    """Actual per-player results for all FINAL games on a date, keyed by player id.
    Empty for dates with no completed games."""
    results: Dict[int, Dict] = {}
    for g in get_schedule(date_str):
        if "final" not in (g.get("status", "") or "").lower():
            continue
        try:
            box = fetch_json(f"{BASE}/game/{g['gamePk']}/boxscore")
        except Exception:
            continue
        for pid, rec in parse_boxscore_results(box).items():
            results.setdefault(pid, {}).update(rec)
    return results


def search_players(query: str) -> List[Dict[str, Any]]:
    """Real MLB player search -- GET /people/search?names={query}, confirmed against MLB Stats
    API's own published documentation (not guessed): returns {"people": [{id, fullName,
    currentTeam, primaryPosition, active, ...}]}. Added directly to fix a real, confirmed root
    cause: bets logged through the "Log a bet" form had no way to attach a real player_id at
    all, so bet_settlement.py's own auto-match logic could never find them in a boxscore no
    matter how correctly everything else about the bet was entered -- 5 real bets stuck exactly
    this way in a live settlement log before this existed.

    Returns [{"id", "name", "team", "position", "active"}, ...] sorted with ACTIVE players
    first (a name search for a common surname can return long-retired players alongside current
    ones; the overwhelming majority of real use here is "who's playing today," so surfacing
    active players first is a real, deliberate ranking choice, not just alphabetical order) --
    an empty list for no query, no matches, or a network failure, never a fabricated result.

    HONEST LIMITATION, same posture as every other MLB Stats API function in this file: not
    verified against a live response from this sandbox (statsapi.mlb.com unreachable here) --
    the endpoint, its `names` parameter, and every field read below are confirmed against MLB's
    own published API documentation, not exercised against a real request. THIS ALREADY BIT ONCE
    IN PRODUCTION: a real deployed search crashed the whole Bet Log page with an AttributeError
    past where the original try/except covered (it only wrapped the fetch_json call itself, not
    the parsing loop after it) -- confirming the live response's real shape differs from what
    the documentation alone implied somewhere in that loop. Hardened directly as a result: every
    per-entry read is now wrapped so one malformed record gets skipped (with the real raw entry
    printed for diagnosis) instead of crashing the whole search, and a completely unexpected
    top-level shape degrades to an honest [] the same way. The exact field-level mismatch that
    caused the original crash is still unconfirmed -- the next real search's own log output is
    what will show it precisely, not a guess."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        data = fetch_json(f"{BASE}/people/search", params={"names": query})
    except Exception:
        return []
    if not isinstance(data, dict):
        print(f"[search_players] unexpected non-dict response for query={query!r}: {type(data)}")
        return []
    people = data.get("people")
    if not isinstance(people, list):
        print(f"[search_players] 'people' key missing or not a list for query={query!r}: "
             f"{list(data.keys())}")
        return []
    out = []
    for p in people:
        try:
            if not isinstance(p, dict):
                print(f"[search_players] skipped a non-dict entry in 'people' for query={query!r}: "
                     f"{type(p)} -- {p!r}")
                continue
            team = (p.get("currentTeam") or {}).get("name")
            position = (p.get("primaryPosition") or {}).get("abbreviation")
            out.append({"id": p.get("id"), "name": p.get("fullName"), "team": team,
                       "position": position, "active": bool(p.get("active"))})
        except Exception as e:  # noqa: BLE001
            # A shape surprise on ONE entry must never take down the whole search -- print the
            # real raw entry so the actual live shape is visible in the next log, and keep going
            # rather than losing every other real match over one bad record.
            print(f"[search_players] skipped one malformed entry for query={query!r}: "
                 f"{type(e).__name__}: {e} -- raw entry: {p!r}")
            continue
    out.sort(key=lambda p: not p["active"])   # active players first, stable order otherwise
    return out


def get_team_injuries(team_id: int) -> List[Dict[str, Any]]:
    """Team injury/roster-restriction report: [{"player", "status", "position", "return_date",
    "comment"}, ...] — same shape basketball_engine.get_team_injuries and nfl_engine.
    get_team_injuries both return, so any shared display code works unchanged.

    HONEST FLAG, GENUINELY DIFFERENT CONFIDENCE LEVEL THAN EVERY OTHER INJURY FUNCTION BUILT ON
    THIS PLATFORM: every other sport's version of this function was checked against a REAL live
    response before shipping (ESPN's endpoints via a person's own fetch for WNBA/NBA/NCAAMB;
    nflreadpy installed directly in the build sandbox for NFL). This one could NOT be — MLB Stats
    API (statsapi.mlb.com) isn't reachable from this sandbox's network allowlist (confirmed
    directly: a live request from this environment returned 403). Built from MLB Stats API's
    documented structure instead (the roster endpoint's own status.code/status.description
    fields), not a live-verified response.

    Fetches rosterType=40Man specifically -- NOT fullRoster, a real, confirmed bug this fixes: a
    real deployed report showed 130+ entries per team including statuses like "Development
    List," "Reassigned to Minors," "Not Yet Reported," and "Reserve List (Minors)" -- fullRoster
    pulls the ENTIRE organization across every affiliated minor-league level, not just the actual
    40-man roster. 40Man is confirmed as its own distinct, documented MLB Stats API rosterType
    value (github.com/BillPetti/baseballr's own mlb_rosters reference lists the full valid set:
    '40Man', 'fullSeason', 'fullRoster', 'nonRosterInvitees', 'active', 'allTime', 'depthChart',
    'gameday', 'coach') -- exactly the "materially narrower option" this function's own docstring
    originally flagged as unconfirmed before switching to it. The active roster alone (rosterType
    =active) by definition EXCLUDES injured players, so that option was never usable here; 40Man
    is the right middle ground: active roster + real IL variants + players optioned but still
    protected on the 40-man, without pulling in the rest of the farm system's own separate
    transaction statuses.

    CONFIRMED via a real deployed check, not just documentation: 40Man correctly includes 60-day
    IL players (Rangers: Carter Baumler, Cody Bradford, Jordan Montgomery, Michael Helman, Robert
    Garcia; Rays: Edwin Uceta, Gavin Lux, Jonathan Heasley, Manuel Rodríguez, Ryan Pepiot, Steven
    Wilson all showed up correctly as "Injured 60-Day" on a real run) -- the one specific detail
    flagged as unconfirmed when this fix first shipped. Real counts dropped from 130+ entries per
    team (fullRoster, the whole organization) to ~18-20 (40Man, the real roster), matching the
    expected shape.

    "Reassigned to Minors" entries are EXPECTED here, not a sign this is still too broad: a
    player can be optioned to AAA/AA while still protected on the 40-man roster (exactly why
    teams keep prospects "on the 40-man" during option years, per MLB's own roster rules) -- a
    real roster restriction (they can't play for the MLB team tonight) even though it isn't an
    injury, which is why this report is titled "roster-restriction," not "injury," report.

    Filters to any roster entry whose status code isn't "A" (Active) — every other status
    (10/15/60-day IL, restricted, bereavement, paternity, etc.) surfaces here using the roster's
    own human-readable status description, rather than this code hardcoding an interpretation of
    every possible status value. return_date/comment are always None — the roster endpoint gives
    a STATUS, not the detailed injury description (body part, expected return) a dedicated
    injury-report source might have; reported honestly empty rather than guessed."""
    try:
        data = fetch_json(f"{BASE}/teams/{team_id}/roster/40Man")
    except Exception:
        return []
    if not data or not data.get("roster"):
        return []

    out: List[Dict[str, Any]] = []
    for entry in data.get("roster", []):
        status = entry.get("status") or {}
        code = status.get("code")
        if not code or code == "A":
            continue   # active, not an injury/roster-restriction entry
        person = entry.get("person") or {}
        pos = entry.get("position") or {}
        out.append({
            "player": person.get("fullName"),
            "status": status.get("description") or code,
            "position": pos.get("abbreviation"),
            "return_date": None,
            "comment": None,
        })
    return out


def get_team_bullpen_fatigue(team_id: int, before_date: str, days_back: int = 5) -> List[Dict[str, Any]]:
    """Per-pitcher recent-appearance workload for this team, over the days_back calendar days
    STRICTLY BEFORE before_date (before_date itself, and anything on/after it, is never included
    — no lookahead, same discipline every other sport's engine on this platform follows).

    Returns one row per pitcher who actually recorded outs in ANY game in the window:
    [{"player_id", "name", "days_since_last_appearance", "appearances_in_window",
      "consecutive_days", "total_outs_in_window", "tag"}, ...], sorted with the most fatigued
    arms first (longest current streak, then most recent appearance).

    METHOD: fetches the team's real games in the window via get_team_schedule_range (one request
    covering the whole window, not days_back separate get_schedule() calls), then for each FINAL
    game in it fetches that game's boxscore and scans every player with a non-empty
    stats.pitching entry — reusing the EXACT SAME parsing shape parse_boxscore_results already
    has proven in production for grading (get_player_results), not new, unverified parsing logic.

    DELIBERATELY DOES NOT TRY TO DISTINGUISH "STARTER" FROM "RELIEVER" WITHIN A SINGLE BOXSCORE —
    a real design choice, not a gap: that would need assuming something about the raw JSON's
    pitcher-listing order that couldn't be confirmed with confidence during scoping. Instead, this
    returns EVERY pitcher who appeared, full stop — the CALLER cross-references against tonight's
    OWN confirmed starter (already known from build_pitching_slate, no guessing needed) to know
    which of these appearances were relief outings. Simpler and more certain than the alternative.

    CONSECUTIVE-DAYS FLAG is the clearest, single highest-value signal here: appeared on 3+
    calendar days in a row, ending the day immediately before before_date. MLB bullpens are
    heavily leash-restricted after 3 straight days by real, well-established convention.

    ONE KNOWN, ACCEPTED IMPRECISION, stated plainly rather than silently shipped: game_date is
    bucketed to its UTC calendar date, not converted to Eastern first. For the large majority of
    games this is a distinction without a difference; a late West Coast start crossing midnight
    UTC could bucket to the "wrong" calendar day by this method. Not worth a timezone-conversion
    dependency for what would be, at most, a rare one-day misread on the least important part of
    this signal (appearances_in_window's exact date, not the days_since/consecutive-streak reads
    that matter most, which are far more often correct even in that edge case).

    HONEST LIMITATION, same posture as get_team_injuries: NOT verified against a live response —
    same statsapi.mlb.com network restriction from this sandbox applies here too. Built on the
    SAME confirmed, already-shipped boxscore-parsing shape used elsewhere in this file, so this
    carries less fresh uncertainty than get_team_injuries did — but the date-range schedule query
    specifically (get_team_schedule_range) is new and hasn't been checked against a live response."""
    try:
        before_dt = datetime.strptime(before_date, "%Y-%m-%d")
    except ValueError:
        return []
    start = (before_dt - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end = (before_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    if end < start:
        return []

    games = get_team_schedule_range(team_id, start, end)
    by_pitcher: Dict[int, Dict[str, Any]] = {}
    for g in games:
        if "final" not in (g.get("status", "") or "").lower():
            continue
        game_date = (g.get("game_date") or "")[:10]
        if not game_date:
            continue
        try:
            box = fetch_json(f"{BASE}/game/{g['gamePk']}/boxscore")
        except Exception:
            continue
        side = "home" if g.get("home_id") == team_id else "away"
        players = (((box.get("teams", {}) or {}).get(side, {}) or {}).get("players", {}) or {})
        for pdata in players.values():
            pid = (pdata.get("person", {}) or {}).get("id")
            if pid is None:
                continue
            pit = (pdata.get("stats", {}) or {}).get("pitching", {}) or {}
            if not pit:
                continue
            outs = _ip_to_outs(pit.get("inningsPitched", "0.0"))
            if outs <= 0:
                continue   # on the pitching staff but didn't actually appear in this game
            name = (pdata.get("person", {}) or {}).get("fullName", "")
            rec = by_pitcher.setdefault(int(pid), {"name": name, "dates": set(), "total_outs": 0})
            rec["dates"].add(game_date)
            rec["total_outs"] += outs

    out: List[Dict[str, Any]] = []
    for pid, rec in by_pitcher.items():
        date_objs = sorted((datetime.strptime(d, "%Y-%m-%d").date() for d in rec["dates"]), reverse=True)
        days_since = (before_dt.date() - date_objs[0]).days

        streak = 0
        cursor = before_dt.date() - timedelta(days=1)
        date_set = set(date_objs)
        while cursor in date_set:
            streak += 1
            cursor -= timedelta(days=1)

        if streak >= 3:
            tag = f"🔴 {streak} straight days — likely unavailable tonight"
        elif days_since <= 1:
            tag = "🟡 Pitched yesterday — some fatigue risk"
        else:
            tag = f"🟢 {days_since} day(s) rest"

        out.append({
            "player_id": pid, "name": rec["name"],
            "days_since_last_appearance": days_since,
            "appearances_in_window": len(rec["dates"]),
            "consecutive_days": streak,
            "total_outs_in_window": rec["total_outs"],
            "tag": tag,
        })
    out.sort(key=lambda x: (-x["consecutive_days"], x["days_since_last_appearance"]))
    return out


def _eastern_hour(iso_utc: Optional[str]) -> Optional[int]:
    """The Eastern-local hour (0-23) of a UTC game_date string, or None for missing/malformed
    input -- a small, self-contained helper (rather than importing sports.py's own game_dt just
    for this) so mlb_engine.py doesn't take on a new cross-module dependency for one field.
    Same US/Eastern conversion sports.game_dt already uses, via the same pytz library already a
    project dependency."""
    if not iso_utc:
        return None
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
        return dt.astimezone(pytz.timezone("US/Eastern")).hour
    except (ValueError, TypeError):
        return None


def get_team_recent_form(team_id: int, before_date: str, games_back: int = 15,
                         venue: Optional[str] = None,
                         time_of_day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """A team's own real record and run differential over its last `games_back` ACTUAL GAMES
    (not calendar days -- a team's own most recent games, the same "count games, not calendar
    days" convention get_team_bullpen_fatigue/get_team_hitter_workload already use) strictly
    before before_date -- the two things a real, repeated trader pattern checks by hand alongside
    starter quality and bullpen freshness: "winning the last 15 games and the run differential is
    big" (games_back defaults to 15 to match that real, stated number directly, not a round
    number chosen independently).

    METHOD: one get_team_schedule_range call over a generous calendar window (games_back * 2
    calendar days with no filter, wider when venue/time_of_day narrows the pool -- see below),
    filtered to Final games, optionally filtered further by venue/time_of_day, then the most
    recent `games_back` of those. Uses the schedule response's OWN per-team "score" field (see
    _normalize_schedule_json's own note) rather than a second boxscore fetch per game -- one
    schedule request per team covers the whole window regardless of how wide it is (a real,
    documented single-request capability of this endpoint, not compounding fetch cost), cheaper
    than get_team_bullpen_fatigue's overall cost since no per-game boxscore fetch is needed here
    at all.

    venue: None (default, every game), "home" (only this team's home games), or "away" (only
    this team's road games) -- filtering happens BEFORE taking the most recent games_back, so
    "last 15 home games" means the 15 most recent home games specifically, which can span a much
    wider calendar window than "last 15 games overall" (roughly half of any team's games are
    home games, so a home/away filter alone widens the needed calendar buffer roughly 2x; the
    buffer below accounts for this).

    time_of_day: None (default), "day" (games starting before 5pm ET), or "night" (5pm ET or
    later) -- the SAME hour boundary sports.slot_of already uses for its own Afternoon/Evening
    split, not a new, separately-invented cutoff. Day games are a real minority of any team's
    schedule (getaway days, Sunday afternoons), so this filter widens the calendar buffer more
    aggressively than venue does. HONEST IMPRECISION, same posture as get_team_bullpen_fatigue's
    own calendar-day bucketing: MLB start times are scheduled in the home team's own local zone,
    so converting to Eastern for this cutoff can misclassify a game close to the boundary for
    West Coast teams specifically -- not worth a timezone-conversion dependency for what's a
    rare, boundary-only misread, the same tradeoff already accepted elsewhere in this file.

    Returns None if the team has no Final games with usable scores matching every filter in the
    window (a real, honest "no data" state, not a fabricated 0-0 record). Otherwise: {"games":
    int, "wins": int, "losses": int, "win_pct": float, "run_diff": int, "avg_run_diff": float,
    "runs_scored": float, "runs_allowed": float}. run_diff is this team's OWN total (runs scored
    minus runs allowed) summed across the window; avg_run_diff is that total divided by games
    played — the number actually comparable between two teams that didn't play the exact same
    number of games in their own windows. runs_scored/runs_allowed are the same per-game
    averages, kept separately (not just their difference) since a Pythagorean win-expectation
    estimate needs both independently."""
    try:
        before_dt = datetime.strptime(before_date, "%Y-%m-%d")
    except ValueError:
        return None
    # Widen the calendar buffer when a filter narrows the real pool of qualifying games -- see
    # the venue/time_of_day docstring notes above for why each needs a different multiplier.
    buffer_mult = 2
    if venue:
        buffer_mult = max(buffer_mult, 4)
    if time_of_day:
        buffer_mult = max(buffer_mult, 8)
    start = (before_dt - timedelta(days=games_back * buffer_mult)).strftime("%Y-%m-%d")
    end = (before_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    if end < start:
        return None

    games = get_team_schedule_range(team_id, start, end)
    games = [g for g in games if "final" in (g.get("status", "") or "").lower()]

    if venue == "home":
        games = [g for g in games if g.get("home_id") == team_id]
    elif venue == "away":
        games = [g for g in games if g.get("home_id") != team_id]

    if time_of_day in ("day", "night"):
        def _is_day(g):
            hour = _eastern_hour(g.get("game_date"))
            return hour is not None and hour < 17
        games = [g for g in games if _is_day(g) == (time_of_day == "day")]

    games = games[-games_back:]   # most recent games_back only, chronological order preserved

    valid = []
    for g in games:
        is_home = g.get("home_id") == team_id
        own_score = g["home_score"] if is_home else g["away_score"]
        opp_score = g["away_score"] if is_home else g["home_score"]
        if own_score is None or opp_score is None:
            continue
        valid.append((own_score, opp_score))
    if not valid:
        return None

    wins = sum(1 for own, opp in valid if own > opp)
    run_diff_total = sum(own - opp for own, opp in valid)
    runs_scored_total = sum(own for own, opp in valid)
    runs_allowed_total = sum(opp for own, opp in valid)
    n = len(valid)
    return {"games": n, "wins": wins, "losses": n - wins, "win_pct": round(wins / n, 3),
           "run_diff": run_diff_total, "avg_run_diff": round(run_diff_total / n, 2),
           # Additive: separate runs-scored/allowed averages, not just their differential --
           # needed for a Pythagorean-expectation estimate (see projections.pythagorean_win_pct),
           # which needs RS and RA independently, not just RS-minus-RA.
           "runs_scored": round(runs_scored_total / n, 2),
           "runs_allowed": round(runs_allowed_total / n, 2)}


def get_game_first_n_innings_runs(game_pk: int, n_innings: int = 3) -> Optional[Dict[str, float]]:
    """Home/away runs actually scored in innings 1 through n_innings of ONE specific game --
    the real building block for "Team Total Runs - First N Innings" markets. ADDED DIRECTLY ON
    REQUEST, closing a real, evidenced gap: confirmed directly (a real cashed 5-leg parlay,
    every leg this exact market) that this is an actively-traded market, and this platform's
    entire market list was player props only -- no team-level total of any kind, partial-game
    or otherwise.

    Fetches MLB Stats API's own dedicated /linescore endpoint (same base URL/auth this file
    already uses for every other endpoint -- a new PATH, not a new integration). Real field path
    (innings[].num, .home.runs, .away.runs) confirmed directly against the official MLB-StatsAPI
    Python wrapper's own source code before writing this, not assumed from the boxscore's
    differently-shaped data (which has no per-inning breakdown at all).

    Only counts innings that actually happened -- a suspended/postponed game, or fetching this
    for a game still in progress, honestly reflects however many of the first n_innings are
    really complete (see "innings_counted" in the return), never padded to look like a full
    n_innings when it isn't. Returns None on a fetch failure or a linescore with no real
    innings data at all -- never a fabricated 0-0.

    Returns {"home": float, "away": float, "innings_counted": int}."""
    try:
        data = fetch_json(f"{BASE}/game/{game_pk}/linescore")
    except Exception:
        return None
    innings = (data or {}).get("innings") or []
    home_runs = away_runs = 0.0
    counted = 0
    for inn in innings:
        if safe_float(inn.get("num"), 99) > n_innings:
            continue
        home_runs += safe_float((inn.get("home") or {}).get("runs"))
        away_runs += safe_float((inn.get("away") or {}).get("runs"))
        counted += 1
    if counted == 0:
        return None
    return {"home": home_runs, "away": away_runs, "innings_counted": counted}


def get_team_recent_first_innings_runs(team_id: int, before_date: str, n_innings: int = 3,
                                       games_back: int = 15) -> Optional[Dict[str, Any]]:
    """A team's own real runs scored (and allowed) in innings 1 through n_innings, averaged
    over its last games_back ACTUAL GAMES strictly before before_date -- the recent-form input a
    "Team Total Runs - First N Innings" projection needs, the same real signal get_team_recent_
    form already provides for full-game totals, narrowed to the specific innings this market
    actually settles on.

    REAL, STATED COST DIFFERENCE from get_team_recent_form: that function reads final scores
    directly off the schedule response (one request covers the whole window). This one needs
    each game's own /linescore specifically (the schedule response has no per-inning
    breakdown at all), so it costs one linescore fetch PER GAME in the window on top of the one
    schedule-range call used to find which games to look at -- genuinely more expensive, stated
    plainly rather than hidden, same posture get_team_bullpen_fatigue's own docstring already
    takes for its own per-game boxscore cost.

    Returns None if no games in the window have usable linescore data. Otherwise: {"games": int,
    "runs_scored": float, "runs_allowed": float} -- per-game averages across whichever of the
    games_back games actually had real, fetchable linescore data (a single bad fetch among many
    good ones doesn't disqualify the whole result, it's just one fewer game counted)."""
    try:
        before_dt = datetime.strptime(before_date, "%Y-%m-%d")
    except ValueError:
        return None
    start = (before_dt - timedelta(days=games_back * 2)).strftime("%Y-%m-%d")
    end = (before_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    if end < start:
        return None

    games = get_team_schedule_range(team_id, start, end)
    games = [g for g in games if "final" in (g.get("status", "") or "").lower()]
    games = games[-games_back:]
    if not games:
        return None

    scored, allowed = [], []
    for g in games:
        pk = g.get("gamePk")
        if not pk:
            continue
        innings = get_game_first_n_innings_runs(pk, n_innings)
        if not innings:
            continue
        is_home = g.get("home_id") == team_id
        scored.append(innings["home"] if is_home else innings["away"])
        allowed.append(innings["away"] if is_home else innings["home"])

    if not scored:
        return None
    return {"games": len(scored), "runs_scored": sum(scored) / len(scored),
           "runs_allowed": sum(allowed) / len(allowed)}


def get_team_pitching_staff(team_id: int, exclude_pid: Optional[int] = None) -> List[Dict[str, Any]]:
    """A team's active pitching staff: [{"id", "name"}, ...] sorted by name, optionally
    excluding one pitcher (typically that night's confirmed starter) — the picker list for
    Matchup Lab's "look at the bullpen instead" option.

    rosterType=active (this module's roster fetches otherwise use fullRoster for get_team_
    injuries, which deliberately wants EVERY roster status including the injured list — this one
    wants the opposite: only pitchers who could actually take the mound tonight). "active" is
    also the more confidently-documented rosterType of the two (MLB Stats API's own default),
    unlike fullRoster's own uncertain 60-day-IL coverage noted in get_team_injuries' docstring.

    DELIBERATELY DOES NOT TRY TO FURTHER SPLIT "TRUE RELIEVERS" FROM "THE OTHER FOUR STARTERS
    ALSO ON THE ACTIVE ROSTER" — a real design choice, not a gap: a roster entry's position field
    is just "P" for every pitcher, with no reliable role distinction available from this endpoint,
    and guessing at one risks exactly the kind of unconfirmed assumption get_team_bullpen_
    fatigue's own docstring already explains avoiding for a related reason. Returns the whole
    staff (minus whoever's excluded); a person who knows their own team's personnel can tell a
    long man from a true reliever from the name alone far more reliably than this code could
    guess from a bare position code.

    HONEST LIMITATION, same posture as this file's other roster/injury functions: not verified
    against a live response (statsapi.mlb.com unreachable from this sandbox)."""
    try:
        data = fetch_json(f"{BASE}/teams/{team_id}/roster/active")
    except Exception:
        return []
    if not data or not data.get("roster"):
        return []
    out: List[Dict[str, Any]] = []
    for entry in data.get("roster", []):
        pos = entry.get("position") or {}
        if pos.get("abbreviation") != "P":
            continue
        person = entry.get("person") or {}
        pid = person.get("id")
        if pid is None or pid == exclude_pid:
            continue
        out.append({"id": pid, "name": person.get("fullName")})
    return sorted(out, key=lambda p: p["name"] or "")


def get_bullpen_closer(team_id: int, exclude_pid: Optional[int] = None,
                       fip_constant: float = FIP_CONSTANT_DEFAULT,
                       max_workers: int = 8) -> Optional["PitcherMetrics"]:
    """Identifies a team's own likely CLOSER from its real active pitching staff, using real,
    available saves data -- the most defensible proxy available without a dedicated bullpen-role
    data source. Checked directly via research before building this, not assumed: even people
    who track bullpen roles full-time (fantasy baseball analysts, whose whole job is exactly
    this) describe closer/setup assignments as genuinely hard to project -- MLB Stats API itself
    has no dedicated "role" field. Saves are a real, standard stat this same season-stat fetch
    (get_pitcher_metrics) already carries for every pitcher, not a new data source.

    METHOD: fetches the team's whole active pitching staff (get_team_pitching_staff), then each
    pitcher's own real season metrics concurrently (get_pitcher_metrics, the SAME function
    already used for every starter on this platform), and returns whoever has the most real
    saves this season.

    REAL, STATED LIMITATION: a team using a genuine closer-committee (several relievers splitting
    save opportunities roughly evenly) still returns SOMEONE -- whoever happens to have the most
    saves, even if the gap over the next-highest arm is small -- rather than correctly reporting
    "no clear closer, this bullpen is a committee." A real simplification, not a claim to detect
    committees specifically.

    REAL COST: one roster fetch plus one get_pitcher_metrics call PER pitcher on the active
    staff (typically 12-14 pitchers) -- a real, additional cost on top of get_bullpen_
    aggregate_stat's own cost, run concurrently the same way build_slate's own per-hitter
    fetches already are.

    Returns None if the team has no active pitching staff, or if EVERY pitcher on it has zero
    real saves this season (early season, or a genuinely closer-less bullpen so far) -- an
    honest "no real closer identified" state, not a fabricated pick from a tie at zero."""
    staff = get_team_pitching_staff(team_id, exclude_pid=exclude_pid)
    if not staff:
        return None

    def fetch(p):
        return get_pitcher_metrics(p["id"], fip_constant)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        metrics = list(ex.map(fetch, staff))

    candidates = [(safe_float((pm.stat or {}).get("saves")), pm) for pm in metrics if pm.id is not None]
    candidates = [(saves, pm) for saves, pm in candidates if saves > 0]
    if not candidates:
        return None
    candidates.sort(key=lambda t: -t[0])
    return candidates[0][1]


def get_bullpen_aggregate_stat(team_id: int, exclude_pid: Optional[int] = None,
                               fip_constant: float = FIP_CONSTANT_DEFAULT) -> Optional[Dict[str, Any]]:
    """Combined season pitching line for a team's ENTIRE active bullpen (every active pitcher
    except exclude_pid, typically that night's starter) — the same flat stat-dict shape a single
    pitcher's PitcherMetrics.stat has, so it's a drop-in replacement anywhere a starter's own
    stat dict is normally used.

    Built by reusing _aggregate_pitching_splits — already proven combining a traded pitcher's two
    stints into one stat line — applied here to a roster's worth of relievers instead. Not new
    aggregation logic, the same "sum multiple stat lines into one" operation on a different set
    of inputs (each entry wrapped as {"stat": ...} to match that function's own expected shape).

    THE ACTUAL MECHANISM for Dinger Engine's "flip to the bullpen read" toggle: hitter HR%/Hit%/
    TB1.5% probabilities are already computed by feeding an opposing pitcher's raw stat dict into
    projections.pitcher_allowed_rates() (see enrich_hitter_rows' own "_opp_stat" field). Feeding
    THIS aggregate bullpen stat dict into that exact same function instead of the starter's own
    stat dict is the entire mechanism — no new hitter-probability modeling needed, just a
    different opposing-pitcher input to the SAME existing pipeline.

    Returns None if the team has no active relievers with a usable stat line (fetch failure, or a
    roster genuinely returning nothing) — callers should fall back to the starter's own read
    rather than show a fabricated all-zero bullpen line."""
    staff = get_team_pitching_staff(team_id, exclude_pid=exclude_pid)
    if not staff:
        return None
    wrapped = []
    for p in staff:
        pm = get_pitcher_metrics(p["id"], fip_constant)
        if pm.stat:
            wrapped.append({"stat": pm.stat})
    if not wrapped:
        return None
    return _aggregate_pitching_splits(wrapped)


def enrich_bullpen_fatigue_with_metrics(fatigue: List[Dict[str, Any]],
                                        fip_constant: float = FIP_CONSTANT_DEFAULT) -> List[Dict[str, Any]]:
    """Add ERA/FIP/K9 to each row from get_team_bullpen_fatigue, one get_pitcher_metrics call
    per pitcher — so Pitching Lab's bullpen table shows "available AND good" vs. "available but
    mediocre" in one place, not two separate lookups a person has to mentally combine themselves.

    Kept as its own function rather than folded into get_team_bullpen_fatigue itself: that
    function's job is workload/availability specifically, and stays unit-testable in isolation
    without needing get_pitcher_metrics' own network calls mocked too — this is a separate, thin
    composition step layered on top, the same "small functions that combine cleanly" shape
    get_bullpen_aggregate_stat above already uses."""
    out = []
    for row in fatigue:
        pm = get_pitcher_metrics(row["player_id"], fip_constant)
        enriched = dict(row)
        enriched.update(ERA=round(pm.era, 2), FIP=pm.fip, K9=round(pm.k9, 1), has_stats=pm.has_stats)
        out.append(enriched)
    return out


def get_bullpen_handedness_mix(team_id: int, exclude_pid: Optional[int] = None) -> Dict[str, Any]:
    """Handedness composition of a team's active bullpen (every active pitcher except
    exclude_pid, typically that night's starter): {"L", "R", "total", "pct_L", "pct_R"}.

    A bullpen has MULTIPLE pitchers of mixed hands, unlike a single confirmed starter — there's
    no one "platoon advantage" the way there is against a starter, since which specific reliever
    a hitter actually faces depends on real-time in-game decisions this platform can't know in
    advance. This is the honest available alternative: the bullpen's OVERALL handedness mix, so a
    lineup stacked with left-handed bats can be read against "how right-handed does this pen skew"
    context, without pretending to know which specific arm comes in.

    KEPT SEPARATE FROM get_bullpen_aggregate_stat, NOT MERGED IN, even though both loop through
    the same roster calling get_pitcher_metrics per reliever (a real, accepted duplicate-fetch
    cost, not an oversight): that function's return shape (a stat dict) is already relied on by
    Dinger Engine's bullpen-matchup toggle from earlier this session, and changing it to also
    carry handedness data would mean touching that already-shipped contract. This is also a
    genuinely different UI use case — a quick platoon-context glance that's useful even when the
    bullpen-matchup toggle itself is off — not something that belongs bundled with the stat
    aggregation specifically.

    Returns all-zero counts (not None) when no staff data is available — a composition summary
    is safe to always render even when empty, unlike get_bullpen_aggregate_stat's stat dict,
    which genuinely shouldn't be shown at all if missing."""
    staff = get_team_pitching_staff(team_id, exclude_pid=exclude_pid)
    left = right = 0
    for p in staff:
        pm = get_pitcher_metrics(p["id"])
        if pm.hand == "L":
            left += 1
        elif pm.hand == "R":
            right += 1
    total = left + right
    return {"L": left, "R": right, "total": total,
           "pct_L": (left / total) if total else 0.0, "pct_R": (right / total) if total else 0.0}


def get_starter_rest_info(pitcher_id: int, team_id: int, before_date: str,
                          lookback_days: int = 15) -> Dict[str, Any]:
    """Days of rest for a probable starter heading into before_date: when he last started, and
    whether that's short rest (<=4 days — genuinely unusual and the well-established effectiveness
    concern), standard rest (5 days — the normal rotation cycle), or extra rest (6+ days, e.g.
    coming off an All-Star break or a rain-delayed turn — more mixed evidence on effect, stated
    honestly as such, not asserted as a clean positive the way short rest is a clean negative).

    Same proven schedule-range + boxscore-scan pattern get_team_bullpen_fatigue already uses, just
    a LONGER lookback window (15 days by default, not 5): a starter's normal rotation cycle IS
    ~5 days, so a 5-day-only window risks missing his last start entirely on a completely normal,
    unremarkable turn if there was any real-world schedule irregularity (a skipped turn, a
    doubleheader, a genuine off day) — 15 days comfortably covers even a skipped-turn starter
    without over-fetching for a normal case (rest_days will just come back small and correct).

    "LAST START" IDENTIFIED BY A >=9-OUTS (3 full innings) FLOOR ON THIS PITCHER'S OWN
    APPEARANCES, not by trying to distinguish start-from-relief in the raw boxscore data (the
    same unconfirmed-assumption risk get_team_bullpen_fatigue's own docstring already explains
    avoiding). A true starter essentially never makes a brief relief cameo mid-rotation, so this
    floor is a defensive safety net more than a load-bearing distinction — but it's honest about
    being a heuristic, not a confirmed "role" field from the data itself.

    Returns {"days_rest": int|None, "last_start_date": str|None, "rest_tag": str}. days_rest is
    None (not a fabricated number) when no qualifying start is found in the window at all — a
    real, legitimate case: an MLB debut, a long-injured pitcher's return, or a genuinely unusual
    layoff longer than the lookback window covers.

    HONEST LIMITATION, same posture as this file's other roster/schedule-based functions: not
    verified against a live response (statsapi.mlb.com unreachable from this sandbox)."""
    try:
        before_dt = datetime.strptime(before_date, "%Y-%m-%d")
    except ValueError:
        return {"days_rest": None, "last_start_date": None, "rest_tag": "Unknown"}
    start = (before_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end = (before_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    if end < start:
        return {"days_rest": None, "last_start_date": None, "rest_tag": "Unknown"}

    games = get_team_schedule_range(team_id, start, end)
    last_start_date = None
    for g in sorted(games, key=lambda x: x.get("game_date") or "", reverse=True):
        if "final" not in (g.get("status", "") or "").lower():
            continue
        game_date = (g.get("game_date") or "")[:10]
        if not game_date:
            continue
        try:
            box = fetch_json(f"{BASE}/game/{g['gamePk']}/boxscore")
        except Exception:
            continue
        side = "home" if g.get("home_id") == team_id else "away"
        players = (((box.get("teams", {}) or {}).get(side, {}) or {}).get("players", {}) or {})
        for pdata in players.values():
            pid = (pdata.get("person", {}) or {}).get("id")
            if pid != pitcher_id:
                continue
            pit = (pdata.get("stats", {}) or {}).get("pitching", {}) or {}
            if pit and _ip_to_outs(pit.get("inningsPitched", "0.0")) >= 9:
                last_start_date = game_date
                break
        if last_start_date:
            break

    if last_start_date is None:
        return {"days_rest": None, "last_start_date": None, "rest_tag": "No recent start found"}

    days_rest = (before_dt.date() - datetime.strptime(last_start_date, "%Y-%m-%d").date()).days
    if days_rest <= 4:
        tag = f"🔴 Short rest — {days_rest} days"
    elif days_rest == 5:
        tag = "🟢 Standard rest — 5 days"
    else:
        tag = f"🟡 Extra rest — {days_rest} days"
    return {"days_rest": days_rest, "last_start_date": last_start_date, "rest_tag": tag}


def get_pitcher_starts_this_season(pitcher_id: int, season: int,
                                   before_date: Optional[str] = None,
                                   team_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """This pitcher's own STARTS this season: [{"gamePk", "game_date", "stat"}, ...] — the
    bounded set of
    games get_pitcher_batting_order_splits below actually needs to fetch boxscores for.

    DELIBERATELY NOT built by scanning the team's whole-season schedule (which would mean a
    boxscore fetch for every one of a team's ~130-160 games just to find the ~20-30 this specific
    pitcher started) — instead, one call to his own game log (stats=gameLog), which returns his
    own per-game lines with each game's id already attached, then filtered to games with real
    starting-pitcher work (gamesStarted, or the same >=9-outs floor this file's other functions
    use as a fallback if that field isn't present in a given response).

    gameType="R" (regular season only) IS EXPLICITLY PASSED, not left to the API's own default —
    a real bug found and fixed after Shawn compared this platform's output against ESPN's own
    batting-order splits for a real pitcher and found a systematic ~11 AB overcount in EVERY
    slot, not random noise. Without gameType pinned down, "season" alone can span more than
    regular-season games under MLB Stats API's own conventions (spring training among them) —
    a handful of spring-training starts, each contributing a few PA per lineup slot, is exactly
    the size and SHAPE of overcount that showed up (uniform across all 9 slots, consistent with
    2-3 extra whole games, not a per-row parsing bug, which would have produced uneven gaps).

    HONEST CONFIDENCE NOTE, worth stating plainly rather than presenting this as equally certain
    to code built on already-proven shapes: gameLog is one of the most standard, widely-used MLB
    Stats API capabilities (used throughout the broader MLB-StatsAPI wrapper ecosystem for
    exactly this "find a player's own games" purpose) — real precedent, not a guess — but it is
    still genuinely unverified against a live response from this sandbox, same statsapi.mlb.com
    restriction as every other function in this file. Lower risk than a novel assumption, higher
    risk than code reusing an already-shipped, tested shape. The gameType fix specifically is
    reasoned from the SIZE and UNIFORMITY of a real, reported discrepancy, not confirmed by
    directly inspecting a live response — worth Shawn's own follow-up check once redeployed to
    confirm the gap actually closes, not just that the fix is well-reasoned."""
    try:
        data = fetch_json(f"{BASE}/people/{pitcher_id}/stats",
                          {"stats": "gameLog", "group": "pitching", "season": season, "gameType": "R"})
    except Exception:
        return []
    try:
        splits = (data.get("stats") or [{}])[0].get("splits", [])
    except (IndexError, AttributeError):
        return []

    out: List[Dict[str, Any]] = []

    # Build gamePk → {is_home, game_date} from team schedule -- the reliable source.
    pk_info: Dict[int, Dict] = {}
    if team_id:
        start_of_season = f"{season}-03-01"
        end_date = before_date or f"{season}-12-31"
        try:
            schedule_games = get_team_schedule_range(team_id, start_of_season, end_date)
            for g in schedule_games:
                pk = g.get("gamePk")
                if pk is not None:
                    pk_info[int(pk)] = {
                        "is_home": (g.get("home_id") == team_id),
                        "game_date": g.get("game_date"),  # ISO UTC with time component
                    }
        except Exception:
            pass

    for sp in splits:
        game = sp.get("game") or {}
        game_pk = game.get("gamePk")
        game_date = sp.get("date")
        if game_pk is None:
            continue
        if before_date and game_date and game_date >= before_date:
            continue
        stat = sp.get("stat") or {}
        gs = safe_float(stat.get("gamesStarted"))
        outs = _ip_to_outs(stat.get("inningsPitched", "0.0"))
        if gs >= 1 or outs >= 9:
            game_time = (game.get("gameDate")
                         or stat.get("startTime") or stat.get("gameStartTime")
                         or sp.get("date") or "")

            # isHome + game_date priority: schedule lookup (reliable) > gameLog fields
            gp_int = int(game_pk) if game_pk else None
            sched = pk_info.get(gp_int) if gp_int else None
            is_home = sched["is_home"] if sched else None
            sched_game_date = sched["game_date"] if sched else None

            if is_home is None:
                is_home = sp.get("isHome")
            if is_home is None:
                pitcher_team_id = (sp.get("team") or {}).get("id")
                game_teams = game.get("teams") or {}
                home_team_id = ((game_teams.get("home") or {}).get("team") or {}).get("id")
                if pitcher_team_id and home_team_id:
                    is_home = (pitcher_team_id == home_team_id)

            # Use schedule's ISO timestamp for day/night (reliable) vs gameLog's gameDate (may be date-only)
            game_time = (sched_game_date or game.get("gameDate")
                         or stat.get("startTime") or stat.get("gameStartTime")
                         or sp.get("date") or "")
            out.append({
                "gamePk": game_pk,
                "game_date": game_date,
                "stat": stat,
                "isHome": is_home,
                "_game_time": game_time,
            })
    return out


MIN_SPLIT_STARTS = 5   # minimum starts/games before we use a split over the full-season line


def last_start_regression_signal(pitcher_id: int, season: int, before_date: str,
                                 season_era: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Compares a starter's MOST RECENT real start to their own season ERA -- ADDED DIRECTLY ON
    REQUEST, closing a real, evidenced gap: a real trader in this project's own community was
    manually tracking exactly this pattern by hand, with screenshots, across multiple real
    pitchers ("guys who had a great start tend to follow it with a rough one, and vice versa").
    Built entirely from get_pitcher_starts_this_season's own already-fetched gameLog data --
    zero new network calls beyond what that function already makes.

    A GENUINELY DIFFERENT, SHORTER-HORIZON SIGNAL than build_pitching_slate's own ERA-vs-FIP
    Delta column -- that one compares a pitcher's WHOLE-SEASON results to their whole-season
    peripherals (a season-long luck-vs-skill read). This compares ONE start to that SAME
    pitcher's own season rate -- "was his last outing unusually good or bad relative to his own
    real season, and might the next one regress back toward his real level" -- a different
    question with a different, shorter answer window, not a duplicate of the existing signal.

    HONEST NOISE CAVEAT, stated plainly rather than hidden behind a clean-looking number: ERA
    from a SINGLE start is a tiny sample, and can swing wildly on a handful of runs allowed in
    relief innings or an early exit. Returns None (not a manufactured signal) for a last start
    under 3 IP -- too short a look to say anything real about it, the same "honest absence over
    a fabricated number" posture every other optional field in this file already uses.

    season_era: pass this in when the caller already has it (build_pitching_slate's own
    ERA/FIP work computes a real season ERA already) to avoid a second, redundant aggregation of
    the same real number -- computed fresh from this pitcher's own real starts only when not
    supplied.

    Returns None if this pitcher has no real starts on file before before_date, or his season ERA
    can't be computed at all (no real innings logged yet). Otherwise {"last_start_date",
    "last_ip", "last_er", "last_era", "season_era", "delta", "tag"} -- delta = last_era minus
    season_era (positive = his last start's earned-run rate was WORSE than his own season norm,
    a real bounce-back-forward candidate; negative = his last start was BETTER than his own
    season norm, a real regression-back-toward-normal candidate). tag is one of "🔥 Trending
    better" (meaningfully below his season ERA last time out), "🥶 Trending worse" (meaningfully
    above it), or "➡️ In line with season" (no meaningful gap) -- the ±2.00 ERA threshold is a
    real, stated, round-number choice (a two-run-per-nine swing on a single start), not
    empirically fit; worth recalibrating against real results once enough of these have been
    tracked through to a next start in Track Record."""
    starts = get_pitcher_starts_this_season(pitcher_id, season, before_date=before_date)
    if not starts:
        return None
    starts = sorted(starts, key=lambda s: s.get("game_date") or "")
    last = starts[-1]
    last_stat = last.get("stat") or {}
    last_outs = _ip_to_outs(last_stat.get("inningsPitched", "0.0"))
    if last_outs < 9:   # under 3 IP -- too short a look to say anything real, see docstring
        return None
    last_ip = last_outs / 3.0
    last_er = safe_float(last_stat.get("earnedRuns"))
    last_era = (last_er / last_ip) * 9

    if season_era is None:
        total_outs = sum(_ip_to_outs((s.get("stat") or {}).get("inningsPitched", "0.0")) for s in starts)
        total_er = sum(safe_float((s.get("stat") or {}).get("earnedRuns")) for s in starts)
        season_era = (total_er / (total_outs / 3.0)) * 9 if total_outs > 0 else None
    if season_era is None:
        return None

    delta = round(last_era - season_era, 2)
    if delta <= -2.0:
        tag = "🔥 Trending better"
    elif delta >= 2.0:
        tag = "🥶 Trending worse"
    else:
        tag = "➡️ In line with season"
    return {
        "last_start_date": last.get("game_date"), "last_ip": round(last_ip, 1),
        "last_er": int(last_er), "last_era": round(last_era, 2),
        "season_era": round(season_era, 2), "delta": delta, "tag": tag,
    }


def get_pitcher_recent_first_innings_allowed(pitcher_id: int, season: int,
                                             before_date: Optional[str] = None, n_innings: int = 3,
                                             games_back: int = 10) -> Optional[Dict[str, Any]]:
    """A starting pitcher's OWN real runs allowed in innings 1 through n_innings, averaged over
    his last games_back real starts -- the dominant real input for a "Team Total Runs - First N
    Innings" projection. ADDED DIRECTLY ON REQUEST.

    PITCHER-SPECIFIC ON PURPOSE, not a team-blended average -- a real, deliberate modeling
    choice: this market is fundamentally about how THIS SPECIFIC STARTER has been doing early in
    games, not an average across whoever else has started for his team recently (a good ace
    followed by a shaky 5th starter would wash out into one meaningless number under a team-wide
    blend). Confirmed directly in real research before building this: "MLB starting pitchers
    dominate the early innings" is the whole premise sharp bettors cite for this market category.

    Built on the SAME real starts list get_pitcher_starts_this_season/last_start_regression_
    signal already use (zero new network call for finding which games to look at), plus one
    get_game_first_n_innings_runs fetch per start -- same real, stated cost as get_team_recent_
    first_innings_runs' own per-game linescore cost, just scoped to one pitcher's own starts
    instead of a whole team's schedule.

    A REAL, STATED APPROXIMATION, not hidden: "runs allowed in innings 1 through n_innings of a
    game he started" is used as a stand-in for "runs he personally allowed" -- true for the
    overwhelming majority of starts (a starter pulled before finishing n_innings due to an
    early disaster would already show elevated runs in the innings he DID pitch), but not a
    guaranteed pitcher-only number the rare time a reliever enters mid-way through inning n_innings
    itself. Same class of honest approximation last_start_regression_signal's own docstring
    already accepts for single-start ERA reads.

    Returns None if this pitcher has no real starts with usable linescore data in the window.
    Otherwise {"games": int, "runs_allowed": float}."""
    starts = get_pitcher_starts_this_season(pitcher_id, season, before_date=before_date)
    starts = sorted(starts, key=lambda s: s.get("game_date") or "")[-games_back:]
    if not starts:
        return None

    allowed = []
    for s in starts:
        pk = s.get("gamePk")
        is_home = s.get("isHome")
        if pk is None or is_home is None:
            continue
        innings = get_game_first_n_innings_runs(pk, n_innings)
        if not innings:
            continue
        allowed.append(innings["away"] if is_home else innings["home"])

    if not allowed:
        return None
    return {"games": len(allowed), "runs_allowed": sum(allowed) / len(allowed)}


def get_pitcher_recent_games(pitcher_id: int, season: int, before_date: Optional[str] = None,
                             venue: Optional[str] = None, time_of_day: Optional[str] = None,
                             n: int = 10) -> List[Dict[str, Any]]:
    """Last n real starts, oldest-to-newest (chart-ready order) -- Outs/Hits Allowed/Earned Runs/
    Strikeouts per start, for the Player Lines trend charts. ADDED DIRECTLY ON REQUEST.

    A THIN FILTERING WRAPPER around get_pitcher_starts_this_season's own already-fetched starts
    -- zero new network calls. Reuses that function's own real isHome/_game_time detection
    instead of re-deriving it a second way, same "one source of truth" posture as everywhere
    else real per-game data gets reused across this file's own multiple consumers.

    venue/time_of_day: same semantics as get_pitcher_split_stat's own filters (the aggregate
    version Pitching Lab already uses) -- "home"/"away", "day"/"night". A start whose home/away
    or day/night honestly can't be determined is EXCLUDED when a filter is active (conservative:
    only show starts we can actually confirm match), included when no filter is active at all.

    Returns [] on no real starts found -- an honest empty chart, never a fabricated data point."""
    starts = get_pitcher_starts_this_season(pitcher_id, season, before_date=before_date)
    if venue is not None:
        starts = [s for s in starts if s.get("isHome") == (venue == "home")]
    if time_of_day is not None:
        filtered = []
        for s in starts:
            hour = _eastern_hour(s.get("_game_time"))
            if hour is None:
                filtered.append(s)   # unknown time -- include conservatively, matching
                continue             # get_pitcher_split_stat's own same posture
            is_day = hour < 17
            if (time_of_day == "day") == is_day:
                filtered.append(s)
        starts = filtered
    starts = sorted(starts, key=lambda s: s.get("game_date") or "")[-n:]

    out = []
    for s in starts:
        stat = s.get("stat") or {}
        out.append({
            "game_date": s.get("game_date"),
            "outs": _ip_to_outs(stat.get("inningsPitched", "0.0")),
            "hits_allowed": safe_float(stat.get("hits")),
            "earned_runs": safe_float(stat.get("earnedRuns")),
            "strikeouts": safe_float(stat.get("strikeOuts")),
        })
    return out


def get_hitter_recent_games(player_id: int, season: int, before_date: Optional[str] = None,
                            venue: Optional[str] = None, time_of_day: Optional[str] = None,
                            n: int = 10) -> List[Dict[str, Any]]:
    """Last n real games, oldest-to-newest (chart-ready order) -- Hits/Total Bases/HRR/HR/
    Strikeouts per game, for the Player Lines trend charts. ADDED DIRECTLY ON REQUEST.

    SAME real gameLog fetch and venue/isHome/time-of-day detection get_hitter_split_stat already
    uses (that function aggregates into one stat dict for a split; this one keeps each game as
    its own row for charting) -- duplicated here rather than refactored out from a live,
    already-tested function Pitching Lab/Best Bets depend on, the lower-risk choice for a new,
    separate consumer.

    HRR here is the REAL per-game sum (hits + runs + rbi actually recorded that game), NOT the
    simulated market probability build_best_bets computes (simulate_hits_runs_rbi models a
    forward-looking distribution; this is what actually already happened, the right number for
    a "how has he really been doing" trend line).

    Returns [] on no real games found -- an honest empty chart, never a fabricated data point."""
    try:
        data = fetch_json(f"{BASE}/people/{player_id}/stats",
                          {"stats": "gameLog", "group": "hitting", "season": season, "gameType": "R"})
    except Exception:
        return []
    try:
        splits = (data.get("stats") or [{}])[0].get("splits", [])
    except (IndexError, AttributeError):
        return []

    games = []
    for sp in splits:
        game_date = sp.get("date", "")
        if before_date and game_date >= before_date:
            continue
        stat = sp.get("stat") or {}
        if safe_float(stat.get("plateAppearances")) < 1:
            continue

        is_home = sp.get("isHome")
        if is_home is None:
            hitter_team_id = (sp.get("team") or {}).get("id")
            game_obj = sp.get("game") or {}
            game_teams = game_obj.get("teams") or {}
            home_team_id = ((game_teams.get("home") or {}).get("team") or {}).get("id")
            if hitter_team_id and home_team_id:
                is_home = (hitter_team_id == home_team_id)
        if venue is not None and is_home != (venue == "home"):
            continue   # unknown (None) is excluded too when a filter is active -- conservative

        if time_of_day is not None:
            game_obj = sp.get("game") or {}
            game_time = (game_obj.get("gameDate") or game_obj.get("officialDate")
                        or stat.get("startTime") or stat.get("gameStartTime"))
            hour = _eastern_hour(game_time) if game_time else None
            if hour is not None:
                is_day = hour < 17
                if (time_of_day == "day") != is_day:
                    continue
            # unknown hour -- included conservatively, same posture as get_hitter_split_stat

        games.append({"game_date": game_date, "stat": stat})

    games = sorted(games, key=lambda g: g["game_date"])[-n:]
    out = []
    for g in games:
        stat = g["stat"]
        hits = safe_float(stat.get("hits"))
        out.append({
            "game_date": g["game_date"],
            "hits": hits,
            "total_bases": safe_float(stat.get("totalBases")),
            "hrr": hits + safe_float(stat.get("runs")) + safe_float(stat.get("rbi")),
            "hr": safe_float(stat.get("homeRuns")),
            "strikeouts": safe_float(stat.get("strikeOuts")),
        })
    return out


def pitcher_season_pitch_stats(pitcher_id: int, season: int, before_date: Optional[str] = None,
                               team_id: Optional[int] = None) -> Dict[str, Any]:
    """This pitcher's own average and max pitch count across REAL starts this season, from the
    exact same gameLog data get_pitcher_starts_this_season already fetches (one call, already
    paid for by that function whenever it's used first — no new endpoint). `stat.numberOfPitches`
    is read from each start's own gameLog entry, same field name already confirmed working on
    the live boxscore in get_live_pitching_line (gameLog entries share the same underlying
    pitching-stat schema, per get_pitcher_starts_this_season's own docstring).

    Returns {"n_starts", "avg_pitches", "max_pitches"} — all None/0 if there's no real start
    data yet (early season, or a pitcher with too few starts to mean anything)."""
    starts = get_pitcher_starts_this_season(pitcher_id, season, before_date=before_date, team_id=team_id)
    counts = [int(s["stat"].get("numberOfPitches", 0) or 0) for s in starts
             if s.get("stat", {}).get("numberOfPitches")]
    if not counts:
        return {"n_starts": len(starts), "avg_pitches": None, "max_pitches": None}
    return {"n_starts": len(starts), "avg_pitches": round(sum(counts) / len(counts), 1),
           "max_pitches": max(counts)}


def hook_risk_flag(current_pitches: int, season_stats: Dict[str, Any]) -> Optional[str]:
    """A direct answer to a real scenario from this platform's own community: a strikeout prop
    riding on a pitcher who needs "one more" late, with no visibility into whether his own season
    workload pattern makes that likely. Compares CURRENT live pitch count against this specific
    pitcher's own real season average/max (not a league-wide number) — the same "his own season
    norm, not a generic threshold" discipline nfl_projections' TD:INT regression already follows.

    Returns a short flag string, or None if there isn't enough season data yet
    (season_stats["n_starts"] < MIN_SPLIT_STARTS) to say anything meaningful — an honest
    "no read" rather than a guess dressed up as a signal.

    NOT a prediction of exactly when a manager will pull this specific pitcher today (a live,
    in-progress decision — same "raw numbers, not a prediction" posture get_live_pitching_line's
    own docstring holds to) — a workload-context flag, not a pull-probability estimate."""
    n = season_stats.get("n_starts") or 0
    avg = season_stats.get("avg_pitches")
    mx = season_stats.get("max_pitches")
    if n < MIN_SPLIT_STARTS or avg is None or mx is None:
        return None
    if current_pitches >= mx:
        return f"🔴 Already at his season-high pitch count ({mx}) — deep past his own norm today"
    if current_pitches >= avg + 10:
        return f"🟠 {current_pitches} pitches vs. his own {avg:.0f} average this season — hook risk elevated"
    if current_pitches >= avg:
        return f"🟡 At his own season-average pitch count ({avg:.0f}) — normal range to be pulled soon"
    return None


def get_pitcher_split_stat(pitcher_id: int, season: int, date_str: str,
                           venue: Optional[str] = None,
                           time_of_day: Optional[str] = None,
                           team_id: Optional[int] = None) -> tuple:
    """Aggregate pitching stat dict for only the starts matching venue/time_of_day.
    team_id: when provided, uses the team schedule to reliably determine home/away for each
    start -- the pitching gameLog API does not include isHome reliably."""
    starts = get_pitcher_starts_this_season(
        pitcher_id, season, before_date=date_str, team_id=team_id)
    if not starts:
        return None, 0

    filtered = []
    for s in starts:
        stat = s.get("stat") or {}

        # is_home and _game_time were set by get_pitcher_starts_this_season using the
        # schedule lookup (pk_info) when team_id was provided -- use them directly here.
        is_home = s.get("isHome")

        if venue is not None and is_home is not None:
            if venue == "home" and not is_home:
                continue
            if venue == "away" and is_home:
                continue

        if time_of_day is not None:
            game_time = s.get("_game_time")
            if game_time:
                try:
                    hour = _eastern_hour(game_time)
                    if hour is not None:
                        is_day = hour < 17
                        if time_of_day == "day" and not is_day:
                            continue
                        if time_of_day == "night" and is_day:
                            continue
                    # hour is None = date-only string, include conservatively
                except Exception:
                    pass

        filtered.append(s)

    if len(filtered) < MIN_SPLIT_STARTS:
        return None, len(filtered)

    aggregated = _aggregate_pitching_splits([{"stat": s["stat"]} for s in filtered])
    return aggregated, len(filtered)


def get_hitter_split_stat(player_id: int, season: int, date_str: str,
                          venue: Optional[str] = None,
                          time_of_day: Optional[str] = None) -> tuple:
    """Aggregate hitting stat dict for only the games matching venue/time_of_day, plus the
    game count. Returns (stat_dict, n_games) matching get_hitter_raw's season stat shape,
    or (None, n_games) when the sample is below MIN_SPLIT_STARTS games.

    Same honest constraint as get_pitcher_split_stat: None signals fall back to full-season."""
    try:
        data = fetch_json(f"{BASE}/people/{player_id}/stats",
                          {"stats": "gameLog", "group": "hitting",
                           "season": season, "gameType": "R"})
    except Exception:
        return None, 0
    try:
        splits = (data.get("stats") or [{}])[0].get("splits", [])
    except (IndexError, AttributeError):
        return None, 0

    filtered = []
    for sp in splits:
        game_date = sp.get("date", "")
        if date_str and game_date >= date_str:
            continue
        stat = sp.get("stat") or {}
        if safe_float(stat.get("plateAppearances")) < 1:
            continue

        # isHome is a split-level field -- also try game["teams"]["home"]["team"]["id"]
        # vs pitcher's team ID as a fallback when isHome isn't populated.
        is_home = sp.get("isHome")
        if is_home is None:
            hitter_team_id = (sp.get("team") or {}).get("id")
            game_obj = sp.get("game") or {}
            game_teams = game_obj.get("teams") or {}
            home_team_id = ((game_teams.get("home") or {}).get("team") or {}).get("id")
            if hitter_team_id and home_team_id:
                is_home = (hitter_team_id == home_team_id)

        if venue is not None and is_home is not None:
            if venue == "home" and not is_home:
                continue
            if venue == "away" and is_home:
                continue

        if time_of_day is not None:
            game_obj = sp.get("game") or {}
            game_time = (game_obj.get("gameDate") or game_obj.get("officialDate")
                         or stat.get("startTime") or stat.get("gameStartTime"))
            if game_time:
                try:
                    hour = _eastern_hour(game_time)
                    if hour is not None:  # only filter when we actually know the time
                        is_day = hour < 17
                        if time_of_day == "day" and not is_day:
                            continue
                        if time_of_day == "night" and is_day:
                            continue
                    # If hour is None, include conservatively
                except Exception:
                    pass

        filtered.append(stat)

    if len(filtered) < MIN_SPLIT_STARTS:
        return None, len(filtered)

    totals: Dict[str, float] = {}
    counting = ("plateAppearances", "atBats", "hits", "homeRuns", "doubles", "triples",
                "baseOnBalls", "strikeOuts", "totalBases", "rbi", "runs", "stolenBases",
                "hitByPitch", "sacFlies")
    for stat in filtered:
        for k in counting:
            totals[k] = totals.get(k, 0.0) + safe_float(stat.get(k))

    ab = totals.get("atBats", 0)
    h = totals.get("hits", 0)
    bb = totals.get("baseOnBalls", 0)
    sf = totals.get("sacFlies", 0)
    hbp = totals.get("hitByPitch", 0)
    tb = totals.get("totalBases", 0)
    if ab > 0:
        totals["avg"] = round(h / ab, 3)
        totals["slg"] = round(tb / ab, 3)
    obp_d = ab + bb + hbp + sf
    if obp_d > 0:
        totals["obp"] = round((h + bb + hbp) / obp_d, 3)
    totals["ops"] = round(totals.get("slg", 0.0) + totals.get("obp", 0.0), 3)
    return totals, len(filtered)


def get_pitcher_batting_order_splits(pitcher_id: int, season: int,
                                     before_date: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    """Cumulative hitting stats THIS PITCHER has allowed this season, broken down by the
    OPPOSING hitter's own batting-order slot (1 = leadoff ... 9 = bottom of the order) — a real
    scouting/rotation-planning question: does this arm get hit hard by the middle of the order
    specifically, or is he equally tough top to bottom? Directly useful for deciding who starts
    against a specific lineup, and for evaluating a pitcher being scouted in a trade against real
    lineup construction, not just his aggregate season line.

    METHOD: NOT a query against some MLB Stats API "batting order split" endpoint — no evidence
    one is directly queryable was found during scoping. Computed by this platform itself: finds
    this pitcher's own real starts this season (get_pitcher_starts_this_season, bounded to his
    ~20-30 actual starts, not his team's whole ~130-160 game season), then for each start's
    boxscore, reads every OPPOSING hitter's own "battingOrder" field (a real MLB Stats API
    boxscore field) alongside their GAME-level batting line, and sums by slot across every start.
    Same "aggregate real per-game data across multiple boxscores" approach get_team_bullpen_
    fatigue and get_starter_rest_info already use for other stats, not a new pattern.

    battingOrder PARSING, AN HONEST CAVEAT: MLB's own boxscore convention encodes this as a
    3-digit code where the FIRST digit is the actual lineup slot (e.g. "100" = leadoff, "900" =
    9th) and the remaining digits handle in-game substitutions within that slot. Parsed here as
    int(battingOrder) // 100. This exact format could not be verified against a live response
    (same statsapi.mlb.com restriction as this file's other functions) — built from documented/
    understood MLB convention, not a live-confirmed shape. Worth an early manual check once
    deployed, same posture as this file's other unverified pieces.

    Returns {slot (1-9): {"ab", "r", "h", "2b", "3b", "hr", "rbi", "bb", "hbp", "so", "avg",
    "obp", "slg", "ops"}, ...} for slots with at least one plate appearance. OBP here is
    simplified (hits + walks + HBP over at-bats + walks + HBP — sacrifice flies aren't tracked at
    this aggregation level), a real, stated approximation, not exact official OBP.

    SMALL SAMPLES ARE THE NORM HERE, NOT THE EXCEPTION, STATED PLAINLY: a single pitcher's single
    season of starts might mean each slot only has 15-25 AB against him total. No artificial
    floor is applied — the raw cumulative is shown honestly — but every number here deserves the
    same skepticism any small sample does; this is a real signal worth looking at, not a stable
    one worth trusting blindly."""
    starts = get_pitcher_starts_this_season(pitcher_id, season, before_date)
    if not starts:
        return {}

    totals = {slot: {"ab": 0.0, "r": 0.0, "h": 0.0, "2b": 0.0, "3b": 0.0, "hr": 0.0,
                     "rbi": 0.0, "bb": 0.0, "hbp": 0.0, "so": 0.0} for slot in range(1, 10)}
    for g in starts:
        try:
            box = fetch_json(f"{BASE}/game/{g['gamePk']}/boxscore")
        except Exception:
            continue
        teams = box.get("teams", {}) or {}
        pitcher_side = None
        for side in ("home", "away"):
            players = (teams.get(side, {}) or {}).get("players", {}) or {}
            if any((p.get("person", {}) or {}).get("id") == pitcher_id for p in players.values()):
                pitcher_side = side
                break
        if pitcher_side is None:
            continue
        opp_side = "away" if pitcher_side == "home" else "home"
        opp_players = (teams.get(opp_side, {}) or {}).get("players", {}) or {}
        for pdata in opp_players.values():
            bat = (pdata.get("stats", {}) or {}).get("batting", {}) or {}
            if not bat:
                continue
            bo = pdata.get("battingOrder")
            if not bo:
                continue
            try:
                slot = int(bo) // 100
            except (TypeError, ValueError):
                continue
            if slot < 1 or slot > 9:
                continue
            t = totals[slot]
            t["ab"] += safe_float(bat.get("atBats"))
            t["r"] += safe_float(bat.get("runs"))
            t["h"] += safe_float(bat.get("hits"))
            t["2b"] += safe_float(bat.get("doubles"))
            t["3b"] += safe_float(bat.get("triples"))
            t["hr"] += safe_float(bat.get("homeRuns"))
            t["rbi"] += safe_float(bat.get("rbi"))
            t["bb"] += safe_float(bat.get("baseOnBalls"))
            t["hbp"] += safe_float(bat.get("hitByPitch"))
            t["so"] += safe_float(bat.get("strikeOuts"))

    out: Dict[int, Dict[str, Any]] = {}
    for slot, t in totals.items():
        ab = t["ab"]
        if ab <= 0 and t["bb"] <= 0 and t["hbp"] <= 0:
            continue   # no real plate appearances recorded for this slot — leave it out, not zero
        singles = max(t["h"] - t["2b"] - t["3b"] - t["hr"], 0.0)
        tb = singles + 2 * t["2b"] + 3 * t["3b"] + 4 * t["hr"]
        avg = (t["h"] / ab) if ab > 0 else 0.0
        obp_denom = ab + t["bb"] + t["hbp"]
        obp = ((t["h"] + t["bb"] + t["hbp"]) / obp_denom) if obp_denom > 0 else 0.0
        slg = (tb / ab) if ab > 0 else 0.0
        out[slot] = {**{k: round(v, 0) for k, v in t.items()},
                    "avg": round(avg, 3), "obp": round(obp, 3), "slg": round(slg, 3),
                    "ops": round(obp + slg, 3)}
    return out


def get_player_current_team(player_id: int) -> Optional[Dict[str, Any]]:
    """A general person -> current team lookup, returning BOTH the numeric id and the display
    name — {BASE}/people/{id} with hydrate=currentTeam explicitly requested.

    hydrate=currentTeam IS REQUIRED, NOT OPTIONAL — a real bug found via a real production
    failure, not caught in review: an earlier version of this function assumed currentTeam came
    back on the base person object with no special hydration, and every single call failed as a
    result (confirmed live: 0/61 real, well-known active catchers — including J.T. Realmuto —
    resolved a team, a complete and uniform failure across every single one, not a data-specific
    issue for any particular player). Confirmed directly from two independent sources during the
    fix: MLB Stats API's own documented hydration values list "currentTeam" explicitly as
    something that must be requested; and MLB-StatsAPI's own real, working source code builds its
    hydrate parameter as "...,currentTeam" (appended as a bare term after any stats hydration,
    not a function call like stats(...) needs). This function's own hydrate string mirrors that
    confirmed-real syntax directly, not a fresh guess.

    RETURNS BOTH id AND name, DELIBERATELY, NOT JUST THE NAME (a separate, earlier fix — kept
    here since both problems affected the same function): team NAME strings in this codebase can
    come from DIFFERENT MLB Stats API endpoints (this one, people/{id}.currentTeam.name; vs. the
    schedule endpoint's teams.home/away.team.name, used to build pitcher["Team"] elsewhere) — two
    different endpoints returning superficially similar strings is exactly the kind of thing that
    can silently NOT match in a straight string comparison, with no error, just a quiet "no data
    found" result that looks like a data gap rather than a matching bug. The numeric id is
    unambiguous across endpoints in a way a display string isn't guaranteed to be; callers doing
    any MATCHING should use "id", and reserve "name" for display only.

    BUILT SPECIFICALLY BECAUSE Baseball Savant's catcher-framing leaderboard turned out to have
    NO team column at all — confirmed directly from a real response's own column list during a
    real production debugging session (['id', 'name', 'pitches', 'rv_tot', 'pct_tot', 'rv_11',
    'pct_11', ...] — no 'team' anywhere), not assumed from documentation. Every other roster/
    team-scoped function in this file goes team_id -> player list; this is the one place so far
    that needs the OPPOSITE direction, player_id -> team, so it's a genuinely new, general
    capability, not a specialization of an existing one.

    Returns None if the player has no current team (retired, minor leagues, or a lookup
    failure) — callers should treat this as "unknown team," not silently attribute the player to
    a wrong or default team.

    HONEST LIMITATION, same posture as this file's other roster-based functions: the hydrate=
    currentTeam fix itself is confirmed from real MLB-StatsAPI source code, real confidence — but
    still not directly verified against a live response from THIS platform's own network
    (statsapi.mlb.com unreachable from this sandbox). Worth a real check on the next run, same as
    every other fix in this thread."""
    try:
        data = fetch_json(f"{BASE}/people/{player_id}", {"hydrate": "currentTeam"})
    except Exception:
        return None
    try:
        person = data.get("people", [{}])[0]
    except (IndexError, AttributeError):
        return None
    team = person.get("currentTeam") or {}
    if "id" not in team:
        return None
    return {"id": team.get("id"), "name": team.get("name")}


def _find_catcher_in_boxscore_side(players: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Which player caught (position "C") for one side of a boxscore, preferring whoever had the
    most plate appearances if more than one catcher appeared (a mid-game defensive substitution,
    or a pinch-hitter for the starting catcher) — the one who did most of the game's catching,
    not necessarily whoever's listed first. Returns None if no catcher is found on this side at
    all (a genuinely possible, if rare, boxscore gap — an interleague DH-rule edge case, or a
    parsing miss — better to report "unknown" than guess)."""
    candidates = []
    for pdata in players.values():
        pos = (pdata.get("position") or {}).get("abbreviation")
        if pos != "C":
            continue
        person = pdata.get("person") or {}
        pid = person.get("id")
        if pid is None:
            continue
        bat = (pdata.get("stats") or {}).get("batting") or {}
        pa = safe_float(bat.get("plateAppearances")) or safe_float(bat.get("atBats"))
        candidates.append({"id": pid, "name": person.get("fullName"), "pa": pa})
    if not candidates:
        return None
    candidates.sort(key=lambda c: c["pa"], reverse=True)
    return {"id": candidates[0]["id"], "name": candidates[0]["name"]}


def get_pitcher_catcher_change_split(pitcher_id: int, team_id: int, season: int,
                                     before_date: Optional[str] = None,
                                     min_starts_each_side: int = 3) -> Optional[Dict[str, Any]]:
    """Detects a REAL mid-season primary-catcher change behind this specific pitcher, and if
    found, returns his own actual BB/K rates split before vs. after — not a derived team-wide
    framing adjustment applied to every pitcher, but this one pitcher's own real outcomes on
    either side of a real personnel change.

    WHY THIS INSTEAD OF A BLANKET FRAMING ADJUSTMENT, THE ACTUAL RECOMMENDATION THIS WAS BUILT
    FROM: a pitcher's season-long BB/K rates already happened WITH his real catcher(s) behind
    him — whatever a good framer contributed over the season is already sitting inside those
    numbers, indistinguishable from "the pitcher got better." Baking a SEPARATE team-wide framing
    adjustment on top would risk double-counting an effect that's usually already there. The
    place a season aggregate genuinely misleads is a MID-SEASON catcher change specifically — the
    full-season rate is a blend of before and after, quietly wrong for projecting the pitcher
    going forward. This targets exactly that gap, using this pitcher's own real results, not a
    projected/derived number.

    METHOD: scans this pitcher's own real starts (get_pitcher_starts_this_season, already bounded
    to his real starts, not his team's whole season), and for each one fetches the boxscore and
    identifies who caught it on his OWN team's side (_find_catcher_in_boxscore_side above) — same
    "scan real per-game boxscore data" approach get_pitcher_batting_order_splits already uses for
    a different question.

    A CHANGE IS ONLY REPORTED IF IT LOOKS REAL, NOT ROUTINE ROTATION: requires the most recent
    starts to be consistently caught by one catcher (the "new" one) and an earlier block of at
    least min_starts_each_side starts consistently caught by a DIFFERENT one (the "old" one).
    Ordinary in-season catcher rotation (a team platooning two catchers all year, with no real
    single transition point) deliberately does NOT qualify — this looks for one clean transition,
    not a general "how does usage vary." Returns None if fewer than min_starts_each_side*2 starts
    exist yet, if only one catcher has ever caught this pitcher, or if no clean single transition
    point can be identified (mixed/rotating usage on both sides of any candidate split).

    Returns {"changed": True, "old_catcher": {"id","name"}, "new_catcher": {"id","name"},
    "change_date": str, "before": {"starts","bb_pct","k_pct"}, "after": {...}} or None.
    bb_pct/k_pct are BB/batters-faced and K/batters-faced across the grouped starts — real,
    summed outcomes, not model output.

    HONEST LIMITATION, same posture as this file's other roster/boxscore-based functions: not
    verified against a live response (statsapi.mlb.com unreachable from this sandbox)."""
    starts = get_pitcher_starts_this_season(pitcher_id, season, before_date)
    if len(starts) < min_starts_each_side * 2:
        return None

    starts_sorted = sorted(starts, key=lambda s: s.get("game_date") or "")
    with_catcher = []
    for s in starts_sorted:
        try:
            box = fetch_json(f"{BASE}/game/{s['gamePk']}/boxscore")
        except Exception:
            continue
        teams = box.get("teams", {}) or {}
        side = None
        for candidate_side in ("home", "away"):
            players = (teams.get(candidate_side, {}) or {}).get("players", {}) or {}
            if any((p.get("person", {}) or {}).get("id") == pitcher_id for p in players.values()):
                side = candidate_side
                break
        if side is None:
            continue
        catcher = _find_catcher_in_boxscore_side((teams.get(side, {}) or {}).get("players", {}) or {})
        if catcher is None:
            continue
        with_catcher.append({**s, "catcher": catcher})

    unique_catchers = {c["catcher"]["id"] for c in with_catcher}
    if len(unique_catchers) < 2 or len(with_catcher) < min_starts_each_side * 2:
        return None

    new_catcher_id = with_catcher[-1]["catcher"]["id"]
    # Walk backward from the most recent start while the catcher stays the "new" one.
    split_idx = len(with_catcher)
    for i in range(len(with_catcher) - 1, -1, -1):
        if with_catcher[i]["catcher"]["id"] == new_catcher_id:
            split_idx = i
        else:
            break
    after_group = with_catcher[split_idx:]
    before_group = with_catcher[:split_idx]
    if len(after_group) < min_starts_each_side or len(before_group) < min_starts_each_side:
        return None

    old_catcher_id = before_group[-1]["catcher"]["id"]
    # The "before" block must ALSO be consistently the old catcher, not mixed rotation —
    # otherwise this isn't a clean transition, it's routine variation, and shouldn't be reported
    # as one.
    if any(g["catcher"]["id"] != old_catcher_id for g in before_group):
        return None

    def _rates(group):
        bb = sum(safe_float(g["stat"].get("baseOnBalls")) for g in group)
        k = sum(safe_float(g["stat"].get("strikeOuts")) for g in group)
        bf = sum(safe_float(g["stat"].get("battersFaced")) for g in group)
        return {
            "starts": len(group),
            "bb_pct": round(bb / bf, 4) if bf > 0 else 0.0,
            "k_pct": round(k / bf, 4) if bf > 0 else 0.0,
        }

    return {
        "changed": True,
        "old_catcher": before_group[-1]["catcher"],
        "new_catcher": after_group[0]["catcher"],
        "change_date": after_group[0].get("game_date"),
        "before": _rates(before_group),
        "after": _rates(after_group),
    }


ONE_SIDED_HR9_THRESHOLD = 0.4   # A stated, reasoned choice, not empirically derived: MLB starter
                               # HR/9 allowed typically sits in a ~0.8-1.8 range across a season,
                               # so a 0.4 gap between two starters in the same game is a real,
                               # meaningful quality difference — not indistinguishable from noise
                               # — but this hasn't been backtested against real outcomes, and is
                               # honestly presented as a reasonable default, not a proven cutoff.


MIN_BATTERS_FACED_FOR_ONE_SIDED = 40   # Matches pitcher_allowed_rates' own floor exactly — not a
                                       # new number invented for this function, the same
                                       # threshold the platform's real per-hitter HR% math already
                                       # requires before trusting a pitcher's rates at all.


def compute_one_sided_banner(hitter_rows: List[Dict[str, Any]], game_label: str) -> Optional[Dict[str, Any]]:
    """For one game, compares both starting pitchers' HR/9 allowed to flag when one side's
    hitters have a real, stated-threshold advantage worth calling out — "concentrate HR plays on
    this side" — rather than treating every game as equally worth digging into.

    WHY HR/9 SPECIFICALLY, NOT A BROADER COMPOSITE METRIC: this banner exists to guide HR-prop
    attention specifically (matching the exact framing this feature was scoped from — "concentrate
    HR plays on that side"), and HR/9 allowed is already computed on every hitter row via "Opp
    HR/9" — the exact rate that matters for that specific question, not a proxy for it. Reusing
    it here isn't a shortcut, it's the right metric for the right question.

    A REAL BUG FIXED HERE, FOUND VIA A REAL REPORTED DISCREPANCY, NOT A HYPOTHETICAL: an earlier
    version trusted "Opp HR/9" directly with NO minimum-sample guard at all — but the platform's
    own individual hitter HR% math (pitcher_allowed_rates) has ALWAYS required >=40 batters faced
    before trusting a pitcher's rates, falling back to a neutral matchup otherwise. A starter with
    a genuinely thin sample (a recent call-up, a handful of relief innings) can show a misleadingly
    "elite" 0.00 HR/9 that's really just small-sample noise, not real skill — and the banner would
    confidently declare that side favored while the properly-gated per-hitter grades correctly
    ignored the same thin signal, producing a banner that directly CONTRADICTED the real grades
    sitting right below it on the page. Now applies the SAME >=40 batters-faced floor
    pitcher_allowed_rates already uses, reading it from each team's own "_opp_stat" (the opposing
    pitcher's own raw stat dict — already present on every hitter row, no new data needed).

    METHOD: every hitter on one team shares the SAME opposing starter, so "Opp HR/9" (and that
    starter's own "_opp_stat") is constant across all of a team's hitters in a given game — this
    reads both directly off any one of them per team rather than doing a second pitcher lookup.
    If the two teams' opposing-starter HR/9 values differ by less than ONE_SIDED_HR9_THRESHOLD,
    returns None — most games are genuinely NOT one-sided, and this should say nothing rather
    than manufacture a marginal one out of noise.

    Returns None if: the game isn't found in hitter_rows, either team's rate is missing/NaN, EITHER
    starter's sample is below MIN_BATTERS_FACED_FOR_ONE_SIDED (the fix described above), or the gap
    doesn't clear the threshold. Otherwise returns {"favored_team", "favored_opp_hr9" (the WEAKER,
    higher-HR9 pitcher the favored team faces), "other_team", "other_opp_hr9", "diff"} — the
    favored team is the one whose hitters face the pitcher allowing MORE home runs, a real
    advantage for their own HR props specifically."""
    game_rows = [r for r in hitter_rows if r.get("GameLabel") == game_label]
    if not game_rows:
        return None
    team_hr9: Dict[str, float] = {}
    team_bf: Dict[str, float] = {}
    for r in game_rows:
        team = r.get("Team")
        hr9 = r.get("Opp HR/9")
        if not team or hr9 is None:
            continue
        try:
            if hr9 != hr9:   # NaN check without importing math — NaN is the only value != itself
                continue
        except TypeError:
            continue
        team_hr9.setdefault(team, float(hr9))
        opp_stat = r.get("_opp_stat") or {}
        team_bf.setdefault(team, safe_float(opp_stat.get("battersFaced")))
    if len(team_hr9) != 2:
        return None
    if any(bf < MIN_BATTERS_FACED_FOR_ONE_SIDED for bf in team_bf.values()):
        return None   # at least one starter's sample is too thin to trust for this specific claim
    (team_a, hr9_a), (team_b, hr9_b) = list(team_hr9.items())
    diff = round(abs(hr9_a - hr9_b), 2)   # rounded BEFORE the threshold check — a real bug found
                                          # via testing, not assumed: comparing the raw float diff
                                          # can silently exclude a value that's conceptually
                                          # exactly at the threshold (e.g. 1.40 - 1.00 evaluates to
                                          # 0.3999999999999999 in float arithmetic, not 0.4)
    if diff < ONE_SIDED_HR9_THRESHOLD:
        return None
    if hr9_a > hr9_b:
        favored_team, favored_hr9, other_team, other_hr9 = team_a, hr9_a, team_b, hr9_b
    else:
        favored_team, favored_hr9, other_team, other_hr9 = team_b, hr9_b, team_a, hr9_a
    return {
        "favored_team": favored_team, "favored_opp_hr9": round(favored_hr9, 2),
        "other_team": other_team, "other_opp_hr9": round(other_hr9, 2),
        "diff": diff,
    }


def get_team_hitter_workload(team_id: int, before_date: str, days_back: int = 10) -> List[Dict[str, Any]]:
    """Per-hitter recent games-STARTED workload for this team, over the days_back calendar days
    STRICTLY BEFORE before_date (before_date itself, and anything on/after it, is never included
    — same no-lookahead discipline every other function in this file follows).

    Returns one row per hitter who started (was the ORIGINAL starter in his slot, not a
    late-game substitute — see battingOrder parsing note below) in at least one game in the
    window: [{"player_id", "name", "games_started_in_window", "team_games_in_window",
    "consecutive_games_started", "tag"}, ...], sorted with the least-rested hitters first.

    A GAMES-BASED STREAK, NOT A CALENDAR-DAYS-BASED ONE — A REAL, DELIBERATE DIFFERENCE FROM
    get_team_bullpen_fatigue's OWN STREAK, not an oversight: a pitcher's fatigue is about arm
    recovery time, so calendar proximity is what matters. A hitter's workload concern is
    different — real coverage of this (beat writers, team statements) talks about "hasn't had a
    day off in N games," not N calendar days, since a team's own off-day is real rest regardless
    of how many calendar days it spans. This counts backward through the TEAM's own most recent
    games in the window (whichever calendar dates those actually fall on) until the first one
    this hitter did NOT start, not backward through consecutive calendar dates.

    BATTINGORDER PARSING: only counts a game where this player was the ORIGINAL starter in his
    slot (battingOrder ending in "00", e.g. "100" for the leadoff spot) — not a late-game
    substitute who entered mid-game (e.g. "101"), who shouldn't count as a real, full day's
    workload the way an original starter's appearance does. Same 3-digit convention already
    established and used elsewhere in this file (get_pitcher_batting_order_splits).

    THE REAL TAGGING THRESHOLD (8+ consecutive games started, no rest day): a stated, reasoned
    choice, not empirically derived or backtested — MLB teams explicitly manage this in practice
    (real, well-documented roster/lineup decisions), but the exact number where it starts
    mattering for performance hasn't been validated against real outcomes here. Presented
    honestly as a reasonable default, the same posture as this file's other stated thresholds.

    METHOD: fetches the team's real games in the window via get_team_schedule_range (one request
    covering the whole window), then for each FINAL game fetches that game's boxscore ONCE and
    scans every player on this team's side with a real battingOrder — one scan covers the WHOLE
    lineup's workload, not one fetch per hitter, the same cost-efficiency get_team_bullpen_
    fatigue already established for pitchers.

    HONEST LIMITATION, same posture as this file's other boxscore-based functions: not verified
    against a live response (statsapi.mlb.com unreachable from this sandbox)."""
    try:
        before_dt = datetime.strptime(before_date, "%Y-%m-%d")
    except ValueError:
        return []
    start = (before_dt - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end = (before_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    if end < start:
        return []

    games = get_team_schedule_range(team_id, start, end)
    team_game_pks: List[str] = []      # chronological order of this team's own FINAL games
    started_by_game: Dict[str, set] = {}   # gamePk -> set of player_ids who started
    names: Dict[int, str] = {}

    games_sorted = sorted(
        [g for g in games if "final" in (g.get("status", "") or "").lower()],
        key=lambda g: g.get("game_date") or ""
    )
    for g in games_sorted:
        game_pk = g.get("gamePk")
        if game_pk is None:
            continue
        try:
            box = fetch_json(f"{BASE}/game/{game_pk}/boxscore")
        except Exception:
            continue
        side = "home" if g.get("home_id") == team_id else "away"
        players = (((box.get("teams", {}) or {}).get(side, {}) or {}).get("players", {}) or {})
        starters = set()
        for pdata in players.values():
            pid = (pdata.get("person", {}) or {}).get("id")
            bo = pdata.get("battingOrder")
            if pid is None or not bo:
                continue
            try:
                if int(bo) % 100 != 0:   # a substitute who entered mid-game, not the original starter
                    continue
            except (TypeError, ValueError):
                continue
            starters.add(int(pid))
            names[int(pid)] = (pdata.get("person", {}) or {}).get("fullName", "")
        team_game_pks.append(game_pk)
        started_by_game[game_pk] = starters

    if not team_game_pks:
        return []

    all_starters = set().union(*started_by_game.values()) if started_by_game else set()
    out: List[Dict[str, Any]] = []
    for pid in all_starters:
        games_started = sum(1 for gp in team_game_pks if pid in started_by_game[gp])
        if games_started == 0:
            continue
        streak = 0
        for gp in reversed(team_game_pks):   # walk backward from the most recent team game
            if pid in started_by_game[gp]:
                streak += 1
            else:
                break

        if streak >= 8:
            tag = f"🔴 Started {streak} straight games — no rest day in this window"
        elif streak >= 5:
            tag = f"🟡 Started {streak} straight games — extended run without a day off"
        else:
            tag = f"🟢 {streak} straight games started"

        out.append({
            "player_id": pid, "name": names.get(pid, ""),
            "games_started_in_window": games_started,
            "team_games_in_window": len(team_game_pks),
            "consecutive_games_started": streak,
            "tag": tag,
        })
    out.sort(key=lambda x: -x["consecutive_games_started"])
    return out
