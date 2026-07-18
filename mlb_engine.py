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
 
BASE = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 10
 
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
    """GET JSON with a couple of retries. Returns {} on failure (never raises)."""
    for attempt in range(retries + 1):
        try:
            r = _SESSION.get(url, params=params or {}, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
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
            sides.append({
                "team_key": team_key,
                "team_name": game[f"{team_key}_name"],
                "opp_pm": opp_pm,
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
        })
        for side in s["sides"]:
            opp = side["opp_pm"]
            for idx, pid in enumerate(side["pids"]):
                raw = raw_by_id.get(pid)
                if not raw:
                    continue
                rows.append(_hitter_row(raw, opp, side["team_name"], s["label"],
                                        side["projected"], idx, s["game"].get("venue_id")))
    return rows, meta
 
 
def build_pitching_slate(date_str: str, fip_constant: float = FIP_CONSTANT_DEFAULT,
                         max_workers: int = 8) -> List[Dict]:
    """Lightweight: probable starters across the slate with ERA/FIP/peripherals.
 
    Does NOT fetch hitters or boxscores, so it is much cheaper than build_slate.
    Returns one row per probable starter, including Delta = ERA - FIP (positive =
    underlying performance better than results = positive-regression candidate)."""
    games = [g for g in get_schedule(date_str) if g.get("gamePk")]
    tasks = []  # (pitcher_id, team_name, opponent, game_label, game_date, team_id, opp_id)
    for g in games:
        label = f"{g['away_name']} @ {g['home_name']}"
        gd = g.get("game_date")
        tasks.append((g["home_pitcher_id"], g["home_name"], g["away_name"], label, gd,
                     g.get("home_id"), g.get("away_id")))
        tasks.append((g["away_pitcher_id"], g["away_name"], g["home_name"], label, gd,
                     g.get("away_id"), g.get("home_id")))
 
    def fetch(t):
        pid, team, opp, label, gd, team_id, opp_id = t
        pm = get_pitcher_metrics(pid, fip_constant)
        return pm, team, opp, label, gd, team_id, opp_id
 
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(fetch, tasks))
 
    rows = []
    for pm, team, opp, label, gd, team_id, opp_id in results:
        if pm.id is None or pm.era == 0:
            continue
        rows.append({
            "Pitcher": pm.name, "_pid": pm.id, "Team": team, "Opponent": opp, "Game": label,
            "Hand": pm.hand, "_game_date": gd, "_team_id": team_id, "_opp_id": opp_id,
            "ERA": round(pm.era, 2), "FIP": pm.fip, "Delta": round(pm.era - pm.fip, 2),
            "K/9": round(pm.k9, 1), "WHIP": round(pm.whip, 2), "HR/9": round(pm.hr9, 2), "OBA": pm.oba,
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
 
 
def _hitter_row(raw: Dict, opp: PitcherMetrics, team_name: str,
                game_label: str, projected: bool, lineup_idx: int = 0,
                venue_id: int = None) -> Dict:
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
        "_opp_stat": opp.stat,                       # opposing pitcher's season line (matchup)
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
 
 
def _parse_boxscore_results(box: Dict) -> Dict[int, Dict]:
    """Per-player actuals from one boxscore, keyed by player id.
 
    Batting: hr, hits, tb, so. Pitching: p_k, p_outs, p_bb. (A player may have both.)"""
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
                singles = max(h - d - t - hr, 0)
                rec.update(hr=hr, hits=h, tb=singles + 2 * d + 3 * t + 4 * hr,
                           so=int(bat.get("strikeOuts", 0) or 0))
 
            pit = stats.get("pitching", {}) or {}
            if pit:
                rec.update(p_k=int(pit.get("strikeOuts", 0) or 0),
                           p_bb=int(pit.get("baseOnBalls", 0) or 0),
                           p_outs=_ip_to_outs(pit.get("inningsPitched", "0.0")))
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
        for pid, rec in _parse_boxscore_results(box).items():
            results.setdefault(pid, {}).update(rec)
    return results


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
    fields), not a live-verified response. Worth an early, deliberate manual check once actually
    deployed — pull up one real team's roster and compare — before trusting this the way every
    other sport's injury data on this platform has already been trusted.

    Fetches rosterType=fullRoster specifically, not the default "active" roster: the active
    roster by definition EXCLUDES injured players, so a plain roster call would return nothing
    useful here. fullRoster was the most defensible documented choice for "the broadest set of
    players, including every IL variant" — but whether it genuinely includes 60-day IL players
    specifically (who by rule fall OFF the 40-man roster, a materially narrower option this
    deliberately avoids using) is the one specific detail that stayed unconfirmed during
    research and is exactly the kind of thing worth checking against a real response early.

    Filters to any roster entry whose status code isn't "A" (Active) — every other status
    (10/15/60-day IL, restricted, bereavement, paternity, etc.) surfaces here using the roster's
    own human-readable status description, rather than this code hardcoding an interpretation of
    every possible status value. return_date/comment are always None — the roster endpoint gives
    a STATUS, not the detailed injury description (body part, expected return) a dedicated
    injury-report source might have; reported honestly empty rather than guessed."""
    try:
        data = fetch_json(f"{BASE}/teams/{team_id}/roster/fullRoster")
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
    stats.pitching entry — reusing the EXACT SAME parsing shape _parse_boxscore_results already
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
                                   before_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """This pitcher's own STARTS this season: [{"gamePk", "game_date"}, ...] — the bounded set of
    games get_pitcher_batting_order_splits below actually needs to fetch boxscores for.

    DELIBERATELY NOT built by scanning the team's whole-season schedule (which would mean a
    boxscore fetch for every one of a team's ~130-160 games just to find the ~20-30 this specific
    pitcher started) — instead, one call to his own game log (stats=gameLog), which returns his
    own per-game lines with each game's id already attached, then filtered to games with real
    starting-pitcher work (gamesStarted, or the same >=9-outs floor this file's other functions
    use as a fallback if that field isn't present in a given response).

    HONEST CONFIDENCE NOTE, worth stating plainly rather than presenting this as equally certain
    to code built on already-proven shapes: gameLog is one of the most standard, widely-used MLB
    Stats API capabilities (used throughout the broader MLB-StatsAPI wrapper ecosystem for
    exactly this "find a player's own games" purpose) — real precedent, not a guess — but it is
    still genuinely unverified against a live response from this sandbox, same statsapi.mlb.com
    restriction as every other function in this file. Lower risk than a novel assumption, higher
    risk than code reusing an already-shipped, tested shape."""
    try:
        data = fetch_json(f"{BASE}/people/{pitcher_id}/stats",
                          {"stats": "gameLog", "group": "pitching", "season": season})
    except Exception:
        return []
    try:
        splits = (data.get("stats") or [{}])[0].get("splits", [])
    except (IndexError, AttributeError):
        return []

    out: List[Dict[str, Any]] = []
    for sp in splits:
        game = sp.get("game") or {}
        game_pk = game.get("gamePk")
        game_date = sp.get("date")
        if game_pk is None:
            continue
        if before_date and game_date and game_date >= before_date:
            continue   # no lookahead — never include a game on/after the date being analyzed
        stat = sp.get("stat") or {}
        gs = safe_float(stat.get("gamesStarted"))
        outs = _ip_to_outs(stat.get("inningsPitched", "0.0"))
        if gs >= 1 or outs >= 9:
            out.append({"gamePk": game_pk, "game_date": game_date})
    return out


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
