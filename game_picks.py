"""
game_picks.py — College football spreads, ratings model v2 (Nov 2). TRACKING ONLY until it proves itself live.

Why: Game Lab's spread / total / moneyline (team scoring averages, no home field, no opponent adjustment) lost to
the closing line in a backtest (research/backtest_ncaaf_game_lab.py: 859 FBS games 2025-26, 47-48% against the
spread). Opponent-adjusted ratings did better on SPREADS only -- 55% when the model was 4+ points off the line
(n=384, half model / half market) and 55% at 7+ (n=443, model alone) -- and still lost on totals, so this is
spreads only. The NFL version of the same model showed no edge (50-52%), so it's college only.

The model: every FBS team gets an offense and a defense rating -- points scored and allowed after adjusting for
who it played -- plus a home-field edge, fitted by ridge least squares on this season's completed games (data/
ncaaf_schedule.csv, refreshed daily). Projected margin = (home offense - away defense) - (away offense - home
defense) + home field. A pick is the side the model favors when it's PICK_EDGE+ points off the books' consensus
spread.

Each capture (capture-game-picks workflow) saves every upcoming game's projection and line (model_store.game_picks):
the first capture is the "open", later ones before kickoff overwrite the "close". Grading uses ESPN's final scores
against the CLOSE line (the strictest test), and tracks closing-line value (did the line move toward the pick).
"""
from __future__ import annotations

import os
import statistics
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

SPORT = "NCAAF"
RIDGE_LAM = 2.0
PICK_EDGE = 4.0
MIN_GAMES = 50                  # completed games in the season before ratings are trusted
LOOKAHEAD_DAYS = 7
ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
SCHEDULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ncaaf_schedule.csv")
EDGE_BUCKETS = ((4, 7), (7, 10), (10, 99))
STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ncaaf_player_game_stats.csv")
# Nov 2 news guard: the model knows results, not news. A pick is HELD (shown with ⚠️, kept out of the official
# record) when the market has clearly heard something -- the line moved LINE_MOVE_HOLD+ points against the pick since
# it opened -- or when a team's quarterback situation changed (its last game's passer isn't its usual starter, or
# the usual starter sat out the last game).
LINE_MOVE_HOLD = 3.0


def _http(url: str, params: Optional[Dict] = None):
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=20, headers={"User-Agent": "H2Sports/1.0"})
        return r.json() if r.ok else None
    except Exception:                                           # noqa: BLE001
        return None


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- ratings
def ratings(games: Sequence[Dict], lam: float = RIDGE_LAM) -> Optional[Dict]:
    """games: completed {"home_team","away_team","home_points","away_points","neutral_site"} ->
    {"mu", "off": {team}, "def": {team}, "hfa"} (hfa = the full home-field edge in points of margin)."""
    games = [g for g in games if _num(g.get("home_points")) is not None and _num(g.get("away_points")) is not None]
    if len(games) < 2:
        return None
    teams = sorted({g["home_team"] for g in games} | {g["away_team"] for g in games})
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    X, y = [], []
    for g in games:
        home = 0.0 if str(g.get("neutral_site")).lower() in ("true", "1") else 1.0
        for t, o, pts, h in ((g["home_team"], g["away_team"], g["home_points"], home),
                             (g["away_team"], g["home_team"], g["away_points"], -home)):
            x = np.zeros(2 * n + 1)
            x[ix[t]], x[n + ix[o]], x[2 * n] = 1.0, -1.0, 0.5 * h
            X.append(x)
            y.append(float(pts))
    X, y = np.array(X), np.array(y)
    mu = float(y.mean())
    reg = np.eye(2 * n + 1) * lam
    reg[2 * n, 2 * n] = 0.0
    beta = np.linalg.solve(X.T @ X + reg, X.T @ (y - mu))
    return {"mu": mu, "off": {t: float(beta[ix[t]]) for t in teams}, "def": {t: float(beta[n + ix[t]]) for t in teams},
            "hfa": float(beta[2 * n])}


def project(r: Dict, home: str, away: str, neutral: bool) -> Optional[Tuple[float, float]]:
    """(home margin, total) or None when a team has no rating."""
    if not r or home not in r["off"] or away not in r["off"]:
        return None
    h = 0.0 if neutral else 0.5 * r["hfa"]
    hp = r["mu"] + r["off"][home] - r["def"][away] + h
    ap = r["mu"] + r["off"][away] - r["def"][home] - h
    return hp - ap, hp + ap


def load_schedule(path: str = SCHEDULE_PATH) -> List[Dict]:
    import pandas as pd
    if not os.path.exists(path):
        return []
    return pd.read_csv(path).to_dict("records")


def _truthy(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "1.0")


# --------------------------------------------------------------------------- news guard
def qb_flags(rows: Iterable[Dict], season: int, min_att: float = 10.0) -> Dict[str, str]:
    """{team: "QB change: ..."} from this season's passing lines. The usual starter is the player who led the team in
    passing in most of its games; the flag goes up when he threw fewer than `min_att` passes (or didn't play) in the
    team's LAST game -- a backup finishing a blowout after the starter's 25 attempts doesn't count."""
    att: Dict = {}                    # (team, game_id) -> {player: attempts}
    week_of: Dict = {}
    for r in rows:
        if int(_num(r.get("season")) or 0) != int(season) or not r.get("team") or not r.get("player"):
            continue
        a = _num(r.get("passing_ATT")) or 0.0
        if a <= 0:
            continue
        key = (r["team"], str(r.get("game_id")))
        att.setdefault(key, {})
        att[key][r["player"]] = max(att[key].get(r["player"], 0.0), a)
        week_of[key] = int(_num(r.get("week")) or 0)
    by_team: Dict[str, List] = {}
    for (team, gid), players in att.items():
        by_team.setdefault(team, []).append((week_of[(team, gid)], players))
    out = {}
    for team, gs in by_team.items():
        if len(gs) < 3:
            continue
        gs.sort(key=lambda g: g[0])
        leads: Dict[str, int] = {}
        for _w, players in gs:
            top = max(players, key=players.get)
            leads[top] = leads.get(top, 0) + 1
        usual = max(leads, key=leads.get)
        last = gs[-1][1]
        who = max(last, key=last.get)
        if who != usual and last.get(usual, 0.0) < min_att:      # a low-volume game he still led isn't a change
            out[team] = (f"QB change: {usual} ({leads[usual]} starts) threw {last.get(usual, 0):.0f} passes in "
                         f"{team}'s last game; {who} threw {last[who]:.0f}")
    return out


def load_stats(path: str = STATS_PATH) -> List[Dict]:
    import pandas as pd
    if not os.path.exists(path):
        return []
    return pd.read_csv(path, usecols=lambda c: c in ("game_id", "season", "week", "team", "player", "passing_ATT")
                       ).to_dict("records")


def line_move_against(rec: Dict, open_line: Optional[float]) -> Optional[float]:
    """Points the line has moved AGAINST the pick since it opened (+ = against)."""
    if not rec.get("pick") or open_line is None or rec.get("line") is None:
        return None
    move = rec["line"] - open_line                 # + = toward the home team
    return -move if rec["pick"] == "home" else move


def guard(recs: List[Dict], existing: Dict[str, Dict], qb: Dict[str, str]) -> List[Dict]:
    """Attach news flags to each record and hold flagged picks."""
    for r in recs:
        flags = [qb[t] for t in (r["home"], r["away"]) if t in qb]
        mv = line_move_against(r, (existing.get(r["game_id"]) or {}).get("open_line"))
        if mv is not None and mv >= LINE_MOVE_HOLD:
            flags.append(f"line moved {mv:.1f} pts against the pick since it opened — the market likely heard news")
        r["flags"] = flags
        r["held"] = bool(r.get("pick") and flags)
    return recs


# --------------------------------------------------------------------------- the books' line
def line_from_event(ev: Dict, home: str) -> Tuple[Optional[float], Optional[float], int]:
    """The books' consensus (median) line as the HOME team's expected margin (+ = home favored), the total, and how
    many books. `home` is the schedule's home team (the Odds API may list a neutral-site game the other way)."""
    import position_lines as PL
    margins, totals = [], []
    for bm in ev.get("bookmakers") or []:
        for mk in bm.get("markets") or []:
            if mk.get("key") == "spreads":
                for o in mk.get("outcomes") or []:
                    pt = _num(o.get("point"))
                    if pt is not None and PL._same_team(o.get("name"), home, True):
                        margins.append(-pt)
            elif mk.get("key") == "totals":
                pts = [_num(o.get("point")) for o in mk.get("outcomes") or [] if o.get("name") == "Over"]
                totals += [p for p in pts if p is not None]
    return (statistics.median(margins) if margins else None, statistics.median(totals) if totals else None,
            len(margins))


def pick_label(home: str, away: str, line_margin: float, side: str) -> str:
    """'Ohio State -7.5' / 'Purdue +7.5' for the picked side at the home-margin line."""
    spread_home = -line_margin
    if side == "home":
        return f"{home} {spread_home:+g}"
    return f"{away} {-spread_home:+g}"


# --------------------------------------------------------------------------- capture
def build(schedule: Sequence[Dict], events: Sequence[Dict], now: datetime) -> List[Dict]:
    """A record for every upcoming game (next LOOKAHEAD_DAYS) the books have a spread for."""
    import position_lines as PL
    upcoming = []
    for g in schedule:
        if _truthy(g.get("completed")):
            continue
        try:
            ko = datetime.fromisoformat(str(g["start_date"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if now < ko <= now + timedelta(days=LOOKAHEAD_DAYS):
            upcoming.append((g, ko))
    if not upcoming:
        return []
    season = int(upcoming[0][0]["season"])
    done = [g for g in schedule if int(g.get("season") or 0) == season and _truthy(g.get("completed"))]
    if len(done) < MIN_GAMES:
        return []
    r = ratings(done)
    out = []
    for g, ko in upcoming:
        ev = PL.match_event(events, g["home_team"], g["away_team"])
        if ev is None:
            continue
        line, total, n_books = line_from_event(ev, g["home_team"])
        proj = project(r, g["home_team"], g["away_team"], _truthy(g.get("neutral_site")))
        if line is None or proj is None:
            continue
        margin, ptotal = proj
        edge = margin - line
        side = ("home" if edge > 0 else "away") if abs(edge) >= PICK_EDGE else None
        out.append({"sport": SPORT, "game_id": str(g["id"]), "season": season, "week": int(g["week"]),
                    "kickoff": ko.isoformat(), "home": g["home_team"], "away": g["away_team"],
                    "neutral": _truthy(g.get("neutral_site")), "model_margin": round(margin, 2),
                    "model_total": round(ptotal, 2), "line": line, "line_total": total, "books": n_books,
                    "edge": round(edge, 2), "pick": side,
                    "pick_label": pick_label(g["home_team"], g["away_team"], line, side) if side else None})
    return out


def capture(api_key: str, fetch: Callable = _http, now: Optional[datetime] = None, db_path: Optional[str] = None,
            schedule: Optional[Sequence[Dict]] = None, stats: Optional[Sequence[Dict]] = None) -> Dict:
    import model_store as MS
    now = now or datetime.now(timezone.utc)
    events = fetch(ODDS_URL, {"apiKey": api_key, "regions": "us", "markets": "spreads,totals", "oddsFormat": "american"})
    recs = build(schedule if schedule is not None else load_schedule(), events or [], now)
    existing = {p["game_id"]: p for p in MS.load_game_picks(SPORT, db_path=db_path)}
    season = recs[0]["season"] if recs else None
    qb = qb_flags(stats if stats is not None else load_stats(), season) if season else {}
    recs = guard(recs, existing, qb)
    saved = MS.save_game_picks(recs, db_path=db_path)
    graded = grade_open(fetch=fetch, now=now, db_path=db_path)
    return {"games": len(recs), "picks": sum(1 for r in recs if r["pick"] and not r["held"]),
            "held": sum(1 for r in recs if r["held"]), "saved": saved, "graded": graded}


# --------------------------------------------------------------------------- grading
def scores_for(day: str, fetch: Callable = _http) -> List[Dict]:
    """[{"home","away","home_pts","away_pts"}] for FBS games final on `day` (YYYY-MM-DD) per ESPN."""
    data = fetch(ESPN_URL, {"dates": day.replace("-", ""), "groups": 80, "limit": 500}) or {}
    out = []
    for ev in data.get("events") or []:
        for c in ev.get("competitions") or []:
            if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                continue
            side = {}
            for t in c.get("competitors") or []:
                team = t.get("team") or {}
                side[t.get("homeAway")] = ([team.get("location"), team.get("displayName"), team.get("shortDisplayName")],
                                           _num(t.get("score")))
            if "home" in side and "away" in side:
                out.append({"home": side["home"][0], "away": side["away"][0], "home_pts": side["home"][1],
                            "away_pts": side["away"][1]})
    return out


def _match(names: Sequence[str], team: str) -> bool:
    import position_lines as PL
    return any(n and PL._same_team(n, team, False) for n in names) or \
        any(n and PL._same_team(n, team, True) for n in names[:1])


def result(pick: Dict, home_pts: float, away_pts: float) -> str:
    """win / loss / push for a pick against its CLOSE line."""
    margin = home_pts - away_pts
    line = pick.get("close_line") if pick.get("close_line") is not None else pick.get("line")
    diff = margin - line
    if abs(diff) < 1e-9:
        return "push"
    return "win" if (diff > 0) == (pick["pick"] == "home") else "loss"


def grade_open(fetch: Callable = _http, now: Optional[datetime] = None, db_path: Optional[str] = None) -> int:
    """Grade every saved pick whose game should be over (kickoff 5+ hours ago) and isn't graded yet."""
    import model_store as MS
    now = now or datetime.now(timezone.utc)
    open_ = [p for p in MS.load_game_picks(SPORT, ungraded=True, db_path=db_path)
             if datetime.fromisoformat(p["kickoff"]) <= now - timedelta(hours=5)]
    days: Dict[str, List[Dict]] = {}
    for p in open_:
        ko = datetime.fromisoformat(p["kickoff"])
        for d in {ko.date().isoformat(), (ko - timedelta(hours=8)).date().isoformat()}:
            days.setdefault(d, [])
    finals = []
    for d in days:
        finals += scores_for(d, fetch)
    n = 0
    for p in open_:
        f = next((x for x in finals if _match(x["home"], p["home"]) and _match(x["away"], p["away"])), None)
        flip = False
        if f is None:
            f = next((x for x in finals if _match(x["home"], p["away"]) and _match(x["away"], p["home"])), None)
            flip = f is not None
        if f is None or f["home_pts"] is None or f["away_pts"] is None:
            continue
        hp, ap = (f["away_pts"], f["home_pts"]) if flip else (f["home_pts"], f["away_pts"])
        res = result(p, hp, ap) if p.get("pick") else None
        if MS.grade_game_pick(SPORT, p["game_id"], hp, ap, res, db_path=db_path):
            n += 1
    return n


def clv(p: Dict) -> Optional[float]:
    """Points the line moved TOWARD the pick between the first and last capture (+ = the market agreed)."""
    if not p.get("pick") or p.get("open_line") is None or p.get("close_line") is None:
        return None
    move = p["close_line"] - p["open_line"]
    return move if p["pick"] == "home" else -move


def summary(picks: Iterable[Dict], held: bool = False) -> Dict:
    """The official record (held picks left out), or with held=True the record of the HELD picks alone."""
    graded = [p for p in picks if p.get("pick") and p.get("result") in ("win", "loss", "push")
              and bool(p.get("held")) == held]
    w = sum(1 for p in graded if p["result"] == "win")
    l_ = sum(1 for p in graded if p["result"] == "loss")
    by = []
    for lo, hi in EDGE_BUCKETS:
        g = [p for p in graded if lo <= abs(p.get("close_edge") or p.get("edge") or 0) < hi]
        gw = sum(1 for p in g if p["result"] == "win")
        gl = sum(1 for p in g if p["result"] == "loss")
        if gw + gl:
            by.append({"edge": f"{lo}–{hi if hi < 99 else '+'}", "record": f"{gw}-{gl}", "hit": gw / (gw + gl)})
    c = [x for x in (clv(p) for p in graded) if x is not None]
    return {"record": f"{w}-{l_}", "hit": w / (w + l_) if w + l_ else None, "graded": w + l_, "by_edge": by,
            "avg_clv": sum(c) / len(c) if c else None, "beat_close": (sum(1 for x in c if x > 0) / len(c)) if c else None}


def review(morning: str, fetch: Callable = _http, db_path: Optional[str] = None) -> Optional[Dict]:
    """For the morning report: grade what's final, then yesterday's picks and the running record."""
    import model_store as MS
    grade_open(fetch=fetch, db_path=db_path)
    allp = MS.load_game_picks(SPORT, db_path=db_path)
    if not allp:
        return None
    yday = (datetime.fromisoformat(morning) - timedelta(days=1)).date().isoformat()
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    ydp = [p for p in allp if datetime.fromisoformat(p["kickoff"]).astimezone(et).date().isoformat() == yday]
    return {"yesterday": summary(ydp), "season": summary(allp), "held_season": summary(allp, held=True),
            "yesterday_picks": [{k: p.get(k) for k in ("pick_label", "home", "away", "close_line", "edge", "result",
                                                        "final_home", "final_away", "held", "flags")}
                                for p in ydp if p.get("pick")]}
