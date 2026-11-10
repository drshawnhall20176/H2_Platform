"""
postgame.py — the Postgame Review: grade what the model said at kickoff against the box score, say WHY each miss
missed, and suggest adjustments from the patterns (Oct 30, after the Packers-Panthers review).

    snapshots (model_store)  +  ESPN box scores  ->  graded props
    graded props             ->  Use-tag record, model-side record, misses by cause
    many graded days         ->  suggestions: a market (or slot) projecting consistently high / low -> an approvable
                                 multiplier (model_tuning); Use-tag, market-gap and cause patterns -> advice

Causes (a miss only):
  Didn't play        no box-score line (void -- not graded)
  Usage absorbed     an Under on a player a fresh absence moved (usage bump / top option), volume 10%+ above the call
  Role change        volume off 25%+ on a player the model flagged (back from injury, filling in, promoted)
  Volume             volume (targets / carries / attempts / minutes) off 25%+ with no role flag -- a model gap
  Blowout            a game decided by 17+ -- script, partly the model
  Player             volume within 25% of the projection: he got the chances and didn't convert -- variance
Kicking / defensive props have no volume to check: Blowout or Player.

PURE apart from the fetchers, which take an injectable `fetch(url, params)` for tests.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import props_engine as PE

ESPN = {"NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl",
        "NCAAF": "https://site.api.espn.com/apis/site/v2/sports/football/college-football",
        "NBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba",
        # Oct 31: NHL and college basketball join the review (and the Bet Log's auto-settle).
        "NCAAMB": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball",
        "NHL": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"}
FAMILY = {"NFL": "football", "NCAAF": "football", "NBA": "basketball", "NCAAMB": "basketball", "NHL": "hockey"}
SCOREBOARD_GROUPS = {"NCAAF": 80, "NCAAMB": 50}     # FBS / Division I -- without it ESPN lists only featured games
NFLVERSE_TO_ESPN = {"LA": "LAR", "WAS": "WSH"}
VOLUME_MISS = 0.25
BLOWOUT = 17
CAUSE_ROLE, CAUSE_VOLUME, CAUSE_BLOWOUT, CAUSE_PLAYER = "Role change", "Volume", "Blowout", "Player"
CAUSE_USAGE = "Usage absorbed"
MODEL_CAUSES = (CAUSE_ROLE, CAUSE_VOLUME, CAUSE_USAGE)
# Oct 31: Bane's minutes went 33 -> 39 (+18%) with Suggs out and his Under missed by 8 -- under the 25% volume bar,
# so it was blamed on "Player". An Under on a player a fresh absence moved, whose volume came in USAGE_MISS+ above
# the call, is the model under-sizing the bump.
USAGE_MISS = 0.10
STAR_OUT_WORDS = ("usage bump", "freshly out")
ROLE_WORDS = ("back", "↑", "fills", "promot", "next man", "missed", "last season blended")
# suggestions
MIN_MARKET_N = 15
MIN_SLOT_N = 12
MARKET_BIAS = 0.08
SLOT_BIAS = 0.12
STEP = 0.5                       # move halfway toward what the results say
SUGGEST_RANGE = (0.90, 1.10)     # one approval moves a market at most 10%


def _http(url: str, params: Optional[Dict] = None) -> Optional[Dict]:
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=15, headers={"User-Agent": "H2Sports/1.0"})
        return r.json() if r.ok else None
    except Exception:                                           # noqa: BLE001
        return None


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _pair(text) -> Tuple[float, float]:
    """'23/41' or '6-33' -> (23, 41)."""
    parts = re.split(r"[/-]", str(text or ""))
    return (_num(parts[0]), _num(parts[1]) if len(parts) > 1 else 0.0)


def _norm(s) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).split())


# --------------------------------------------------------------------------- box scores
_FOOTBALL = {  # group name -> {label: our stat (or a callable(text) -> {stat: value})}
    "passing": {"C/ATT": lambda t: dict(zip(("pass_cmp", "pass_att"), _pair(t))), "YDS": "pass_yds", "TD": "pass_td",
                "INT": "pass_int", "SACKS": lambda t: {"sacked": _pair(t)[0]}},
    "rushing": {"CAR": "rush_att", "YDS": "rush_yds", "TD": "rush_td"},
    "receiving": {"REC": "rec", "YDS": "rec_yds", "TD": "rec_td", "TGTS": "tgt"},
    "defensive": {"TOT": "tkl", "SOLO": "tkl_solo", "SACKS": "sacks"},
    "interceptions": {"INT": "def_int"},
    "kicking": {"FG": lambda t: dict(zip(("fg_made", "fg_att"), _pair(t))),
                "XP": lambda t: dict(zip(("pat_made", "pat_att"), _pair(t))), "PTS": "kick_pts"},
}


def football_box(summary: Optional[Dict]) -> Dict:
    """ESPN football summary -> {"teams": {team abbreviation: {normalized name: stats}}, "ids": {abbr: team id},
    "score": {abbr: points}, "final": bool}. Every player who shows up anywhere in the box gets every stat (0 when
    his group is missing -- a receiver with no catch still played)."""
    out = {"teams": {}, "ids": {}, "score": {}, "final": False, "aliases": {}}
    if not summary:
        return out
    box = summary.get("boxscore") or {}
    for team in box.get("players") or []:
        t = team.get("team") or {}
        abbr = t.get("abbreviation")
        if not abbr:
            continue
        out["ids"][abbr] = t.get("id")
        for a in _aliases(t):                    # "baylor", "baylor bears", "bay", ... -> "BAY"
            out["aliases"].setdefault(a, abbr)
        players: Dict[str, Dict] = out["teams"].setdefault(abbr, {})
        for grp in team.get("statistics") or []:
            spec = _FOOTBALL.get(grp.get("name"))
            labels = grp.get("labels") or []
            for a in grp.get("athletes") or []:
                name = _norm(PE.norm_name((a.get("athlete") or {}).get("displayName")))
                if not name:
                    continue
                st = players.setdefault(name, {"_name": (a.get("athlete") or {}).get("displayName")})
                if not spec:
                    continue
                for lab, val in zip(labels, a.get("stats") or []):
                    how = spec.get(lab)
                    if how is None:
                        continue
                    if callable(how):
                        st.update(how(val))
                    else:
                        st[how] = _num(val)
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    for c in comp.get("competitors") or []:
        abbr = (c.get("team") or {}).get("abbreviation")
        if abbr:
            out["score"][abbr] = _num(c.get("score"))
    out["final"] = bool((((comp.get("status") or {}).get("type") or {}).get("completed")))
    return out


_BASKETBALL = {"MIN": "min", "PTS": "pts", "REB": "reb", "AST": "ast", "STL": "stl", "BLK": "blk", "TO": "tov",
               "3PT": lambda t: {"fg3m": _pair(t)[0]}}


def basketball_box(summary: Optional[Dict]) -> Dict:
    """ESPN basketball summary -> the same shape as football_box, keyed by team id (as text). DNPs are left out."""
    out = {"teams": {}, "ids": {}, "score": {}, "final": False}
    if not summary:
        return out
    for team in (summary.get("boxscore") or {}).get("players") or []:
        t = team.get("team") or {}
        tid = str(t.get("id") or "")
        if not tid:
            continue
        out["ids"][t.get("abbreviation") or tid] = tid
        players = out["teams"].setdefault(tid, {})
        for grp in team.get("statistics") or []:
            labels = grp.get("labels") or []
            for a in grp.get("athletes") or []:
                if a.get("didNotPlay") or not a.get("stats"):
                    continue
                name = _norm(PE.norm_name((a.get("athlete") or {}).get("displayName")))
                st = players.setdefault(name, {"_name": (a.get("athlete") or {}).get("displayName")})
                for lab, val in zip(labels, a.get("stats") or []):
                    how = _BASKETBALL.get(lab)
                    if how is None:
                        continue
                    if callable(how):
                        st.update(how(val))
                    else:
                        st[how] = _num(val)
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    for c in comp.get("competitors") or []:
        tid = str((c.get("team") or {}).get("id") or "")
        if tid:
            out["score"][tid] = _num(c.get("score"))
    out["final"] = bool((((comp.get("status") or {}).get("type") or {}).get("completed")))
    return out


# ESPN's NHL box: read by `keys`, never labels -- the column LABELLED "SOG" is shootout goals; shots on goal is
# "S" (key shotsTotal). Same trap nhl_engine.parse_summary documents.
_HOCKEY_SKATER = {"goals": "g", "assists": "a", "shotsTotal": "sog", "blockedShots": "blk", "timeOnIce": "toi"}
_HOCKEY_GOALIE = {"saves": "saves", "shotsAgainst": "sa", "goalsAgainst": "ga", "timeOnIce": "toi"}


def _minutes(text) -> float:
    """'18:42' -> 18.7 (ice time)."""
    parts = str(text or "").split(":")
    try:
        return float(parts[0]) + (float(parts[1]) / 60 if len(parts) > 1 else 0.0)
    except ValueError:
        return 0.0


def hockey_box(summary: Optional[Dict]) -> Dict:
    """ESPN NHL summary -> the same shape as basketball_box (keyed by team id as text). Skaters get g, a, pts, sog,
    blk, toi; goalies get saves, sa, ga, toi. Players with no ice time are left out (scratches)."""
    out = {"teams": {}, "ids": {}, "score": {}, "final": False}
    if not summary:
        return out
    for team in (summary.get("boxscore") or {}).get("players") or []:
        t = team.get("team") or {}
        tid = str(t.get("id") or "")
        if not tid:
            continue
        out["ids"][t.get("abbreviation") or tid] = tid
        players = out["teams"].setdefault(tid, {})
        for grp in team.get("statistics") or []:
            goalie = grp.get("name") == "goalies"
            spec = _HOCKEY_GOALIE if goalie else _HOCKEY_SKATER
            keys = grp.get("keys") or []
            for a in grp.get("athletes") or []:
                vals = dict(zip(keys, a.get("stats") or []))
                toi = _minutes(vals.get("timeOnIce"))
                if toi <= 0:
                    continue
                name = _norm(PE.norm_name((a.get("athlete") or {}).get("displayName")))
                st = players.setdefault(name, {"_name": (a.get("athlete") or {}).get("displayName")})
                for k, ours in spec.items():
                    if k in vals:
                        st[ours] = toi if k == "timeOnIce" else _num(vals[k])
                if not goalie:
                    st["pts"] = st.get("g", 0.0) + st.get("a", 0.0)
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    for c in comp.get("competitors") or []:
        tid = str((c.get("team") or {}).get("id") or "")
        if tid:
            out["score"][tid] = _num(c.get("score"))
    out["final"] = bool((((comp.get("status") or {}).get("type") or {}).get("completed")))
    return out


def _aliases(team: Dict) -> set:
    vals = {team.get("abbreviation"), team.get("displayName"), team.get("shortDisplayName"), team.get("location"),
            team.get("name"), str(team.get("id") or "")}
    return {_norm(v) for v in vals if v}


def _team_alias(sport: str, team) -> str:
    t = str(team or "")
    if sport == "NFL":
        t = NFLVERSE_TO_ESPN.get(t, t)
    return _norm(t)


def fetch_results(sport: str, slate_date: str, games: Sequence[Tuple[str, str]],
                  fetch: Callable = _http) -> Dict[Tuple[str, str], Dict]:
    """{(team, opp) as snapshots store them: box} for the games of one date. `games` = [(team, opp)]."""
    base = ESPN.get(sport)
    if not base:
        return {}
    params = {"dates": slate_date.replace("-", ""), "limit": 400}
    if sport in SCOREBOARD_GROUPS:
        params["groups"] = SCOREBOARD_GROUPS[sport]
    board = fetch(f"{base}/scoreboard", params) or {}
    events = []
    for ev in board.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        teams = [c.get("team") or {} for c in comp.get("competitors") or []]
        events.append((ev.get("id"), [_aliases(t) for t in teams]))
    parse = {"basketball": basketball_box, "hockey": hockey_box}.get(FAMILY.get(sport), football_box)
    out: Dict[Tuple[str, str], Dict] = {}
    cache: Dict[str, Dict] = {}
    for team, opp in dict.fromkeys(games):
        a, b = _team_alias(sport, team), _team_alias(sport, opp)
        for eid, al in events:
            if len(al) == 2 and ((a in al[0] and b in al[1]) or (a in al[1] and b in al[0])):
                if eid not in cache:
                    cache[eid] = parse(fetch(f"{base}/summary", {"event": eid}))
                out[(team, opp)] = cache[eid]
                break
    return out


def _team_key(sport: str, box: Dict, team) -> Optional[str]:
    """The box's key for a snapshot's team (abbreviation for football, id for basketball)."""
    t = str(team or "")
    if FAMILY.get(sport) in ("basketball", "hockey"):
        return t if t in box["teams"] else None
    t = NFLVERSE_TO_ESPN.get(t, t) if sport == "NFL" else t
    if t in box["teams"]:
        return t
    nt = _norm(t)
    for abbr in box["teams"]:
        if _norm(abbr) == nt:
            return abbr
    # College snapshots carry the school name ("Baylor", "Kent State"), the box keys ESPN's abbreviation ("BAY",
    # "KENT"). Before Oct 31 only schools whose name IS the abbreviation (UCF, LSU, SMU...) matched, so ~80% of
    # college props were voided. Match on ESPN's own names for the team as well.
    abbr = (box.get("aliases") or {}).get(nt)
    return abbr if abbr in box["teams"] else None


# --------------------------------------------------------------------------- grading
def stat_value(sport: str, market: str, stats: Dict) -> Optional[float]:
    if FAMILY.get(sport) == "hockey":
        import hockey_props as HP
        m = HP.MARKETS.get(market)
        return None if not m or m["stat"] not in stats else _num(stats[m["stat"]])
    if FAMILY.get(sport) == "basketball":
        import player_props as PPR
        return PPR.market_value(stats, market) if market in PPR.MARKETS else None
    import football_props as FP
    return FP.market_value(stats, market) if market in FP.MARKETS else None


def actual_volume(sport: str, market: str, stats: Dict) -> Optional[float]:
    if FAMILY.get(sport) == "hockey":                     # ice time for skaters, shots faced for a goalie's saves
        key = "sa" if market == "Saves" else "toi"
        return _num(stats.get(key)) if key in stats else None
    if FAMILY.get(sport) == "basketball":
        return _num(stats.get("min")) if "min" in stats else None
    import football_props as FP
    m = FP.MARKETS.get(market) or {}
    kind = m.get("opp")
    if kind in (None, "none"):
        return None
    return FP.opportunity(stats, kind, True)


def cause(rec: Dict, margin: Optional[float]) -> Optional[str]:
    """Why a graded miss missed (None for a hit / push / void)."""
    if rec.get("result") != "miss":
        return None
    flags = " ".join(json.loads(rec.get("flags") or "[]")).lower() if isinstance(rec.get("flags"), str) else \
        " ".join(rec.get("flags") or []).lower()
    pv, av = rec.get("proj_opp"), rec.get("actual_opp")
    if ((rec.get("side") or "Over") == "Under" and any(w in flags for w in STAR_OUT_WORDS)
            and (not pv or av is None or av / pv >= 1 + USAGE_MISS)):
        return CAUSE_USAGE
    if pv and av is not None and pv > 0:
        r = av / pv
        helped = (r > 1) == ((rec.get("side") or "Over") == "Over")     # the volume swing favored the bet anyway
        if abs(r - 1) >= VOLUME_MISS and not helped:
            if any(w in flags for w in ROLE_WORDS):
                return CAUSE_ROLE
            if margin is not None and abs(margin) >= BLOWOUT:
                return CAUSE_BLOWOUT
            return CAUSE_VOLUME
        return CAUSE_PLAYER
    if margin is not None and abs(margin) >= BLOWOUT:
        return CAUSE_BLOWOUT
    return CAUSE_PLAYER


def grade(snapshots: Sequence[Dict], results: Dict[Tuple[str, str], Dict]) -> List[Dict]:
    """Each snapshot + "actual", "result" (hit / miss / push / void / pending), "model_hit" (the projection's side),
    "actual_opp", "volume_ratio", "cause", "margin"."""
    out = []
    for s in snapshots:
        rec = dict(s)
        box = results.get((s.get("team"), s.get("opp")))
        rec.update(actual=None, result="pending", model_hit=None, actual_opp=None, volume_ratio=None, cause=None,
                   margin=None)
        if not box or not box.get("teams"):
            out.append(rec)
            continue
        if not box.get("final"):
            out.append(rec)
            continue
        tk = _team_key(s["sport"], box, s.get("team"))
        ok = None
        if tk is not None:
            ok = next((k for k in box["score"] if k != tk), None)
            if box["score"].get(tk) is not None and ok is not None:
                rec["margin"] = box["score"][tk] - box["score"][ok]
        stats = ((box["teams"].get(tk) or {}) if tk is not None else {}).get(_norm(PE.norm_name(s.get("player"))))
        if stats is None:
            rec["result"] = "void"
            out.append(rec)
            continue
        val = stat_value(s["sport"], s["market"], stats)
        if val is None:
            rec["result"] = "void"
            out.append(rec)
            continue
        line, side = float(s["line"]), s.get("side") or "Over"
        thr = PE.threshold(line)
        rec["actual"] = val
        if val == thr:
            rec["result"] = "push"
        else:
            rec["result"] = "hit" if ((val > thr) == (side == "Over")) else "miss"
        if s.get("projection") is not None and val != thr:
            rec["model_hit"] = (val > thr) == (float(s["projection"]) > thr)
        av = actual_volume(s["sport"], s["market"], stats)
        rec["actual_opp"] = av
        if av is not None and s.get("proj_opp"):
            rec["volume_ratio"] = av / float(s["proj_opp"])
        rec["cause"] = cause(rec, rec["margin"])
        out.append(rec)
    return out


# --------------------------------------------------------------------------- summaries
def use_record(graded: Sequence[Dict]) -> List[Dict]:
    """Per Use tag: graded, hits, hit rate, the average chance the model gave."""
    out = []
    for tag in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE, PE.USE_PASS):
        g = [r for r in graded if r.get("use_tag") == tag and r["result"] in ("hit", "miss")]
        if not g:
            continue
        hits = sum(r["result"] == "hit" for r in g)
        ch = [r["chance"] for r in g if r.get("chance") is not None]
        out.append({"Use": tag, "Graded": len(g), "Hits": hits, "Hit rate": hits / len(g),
                    "Model said": (sum(ch) / len(ch)) if ch else None})
    return out


def lock_record(graded: Sequence[Dict]) -> Optional[Dict]:
    """The 🔒 Most probable picks (Best Bets' lock: 60%+ chance, 15%+ cushion, books not far off) as one row in
    use_record's shape, plus profit per $1 at the posted price where one was saved. None when none were graded."""
    g = [r for r in graded if r.get("result") in ("hit", "miss")
         and PE.most_probable(r.get("chance"), r.get("cushion"), r.get("gap"))]
    if not g:
        return None
    hits = sum(r["result"] == "hit" for r in g)
    ch = [r["chance"] for r in g if r.get("chance") is not None]
    priced = [r for r in g if PE.decimal(r.get("price")) is not None]
    prof = (sum((PE.decimal(r["price"]) - 1) if r["result"] == "hit" else -1 for r in priced) / len(priced)
            if priced else None)
    return {"Use": PE.MOST_PROBABLE, "Graded": len(g), "Hits": hits, "Hit rate": hits / len(g),
            "Model said": (sum(ch) / len(ch)) if ch else None, "Profit per $1": prof, "Priced": len(priced)}


def model_record(graded: Sequence[Dict]) -> Tuple[int, int]:
    g = [r for r in graded if r.get("model_hit") is not None]
    return sum(1 for r in g if r["model_hit"]), len(g)


def cause_counts(graded: Sequence[Dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in graded:
        if r.get("cause"):
            out[r["cause"]] = out.get(r["cause"], 0) + 1
    return out


# --------------------------------------------------------------------------- suggestions
def _ratio(rows: Sequence[Dict]) -> Optional[float]:
    p = sum(float(r["projection"]) for r in rows)
    a = sum(float(r["actual"]) for r in rows)
    return a / p if p > 0 else None


# Nov 6: the two advice cards below used to judge by hit rate alone, and on Nov 6 both pointed the wrong way
# (research/advice_study.py, every graded read): 🎯 singles at +3-5% value were the BEST bucket in NBA, NFL and NCAAF
# (bigger "value" meant the model fighting the market, and losing), so raising the bar would have cut the winners;
# and the model's 62-72% "right" on big gaps was mostly short Unders -- following it at the posted prices lost money
# in every sport. They now judge by profit at the posted price before advising a change.
def _profit(rows) -> Optional[float]:
    priced = [r for r in rows if PE.decimal(r.get("price")) is not None]
    if not priced:
        return None
    return sum((PE.decimal(r["price"]) - 1) if r.get("result") == "hit" or r.get("y") else -1
               for r in priced) / len(priced)


def _value(r) -> Optional[float]:
    if r.get("ev") is not None:
        return r["ev"]
    d = PE.decimal(r.get("price"))
    return None if d is None or r.get("chance") is None else r["chance"] * d - 1


def _single_advice(graded, row) -> Dict:
    s = [r for r in graded if r.get("use_tag") == PE.USE_SINGLE and r.get("result") in ("hit", "miss")]
    lo = [r for r in s if (_value(r) or 0) < 0.05]
    hi = [r for r in s if (_value(r) or 0) >= 0.05]
    p_lo, p_hi = _profit(lo), _profit(hi)
    head = f"{row['Use']} plays hit {row['Hit rate']:.0%} over {row['Graded']}."
    if len(hi) >= 15 and len(lo) >= 15 and p_lo is not None and p_hi is not None and p_hi > p_lo + 0.03:
        return {"kind": "advice", "n": row["Graded"],
                "text": f"{head} Value +5%+ earned {p_hi:+.0%} per $1 vs {p_lo:+.0%} below it -- raise the edge a "
                        "single needs (+3% -> +5%)."}
    sides = {sd: [r for r in s if r.get("side") == sd] for sd in ("Over", "Under")}
    po, pu = _profit(sides["Over"]), _profit(sides["Under"])
    tail = ("" if p_lo is None or p_hi is None else
            f" Raising the edge wouldn't help: +5%+ earned {p_hi:+.0%} per $1, +3-5% earned {p_lo:+.0%}.")
    if len(sides["Over"]) >= 15 and po is not None and pu is not None and po < pu - 0.10:
        return {"kind": "advice", "n": row["Graded"],
                "text": f"{head} Over singles are the drain ({po:+.0%} per $1 over {len(sides['Over'])}; Unders "
                        f"{pu:+.0%}).{tail} Approve the Overs correction under ⚖️ Overs vs Unders."}
    return {"kind": "info", "n": row["Graded"], "text": f"{head}{tail} No rule change suggested yet."}


def _gap_advice(gaps, right) -> Dict:
    on_model = [dict(r, y=1 if r["model_hit"] else 0) for r in gaps
                if r.get("price") is not None and r.get("projection") is not None and r.get("line") is not None
                and ((r["projection"] > r["line"]) == (r.get("side") == "Over"))]
    prof = _profit(on_model)
    if prof is not None and len(on_model) >= 12 and prof > 0:
        return {"kind": "advice", "n": len(gaps),
                "text": f"When the line sat far from the projection the MODEL was right {right:.0%} of the time "
                        f"({len(gaps)} props), and following it earned {prof:+.0%} per $1 at the posted prices: "
                        "the news check may be too cautious -- give the model more vote."}
    money = "" if prof is None else f", but following it at the posted prices returned {prof:+.0%} per $1"
    return {"kind": "info", "n": len(gaps),
            "text": f"When the line sat far from the projection the model was right {right:.0%} of the time "
                    f"({len(gaps)} props){money} -- mostly short-priced Unders. Keep the news check as it is."}


# Nov 6: 23 NFL adjustments were suggested (and approved, twice) off one Sunday's games -- 85% of the graded NFL
# props came from Nov 1. Re-fitted leaving each slate out, most made the held-out slate WORSE, and their approved
# factors compounded each morning (x1.10 became x1.21 on the next suggestion). An adjustment is now suggested only
# when (1) at least HOLD_SLATES slates with HOLD_MIN_N+ props each ran the same way as the move, and (2) fitted
# without each slate in turn, it lowered the error on that held-out slate overall.
HOLD_SLATES = 2
HOLD_MIN_N = 5


def holds_up(rows: Sequence[Dict], step: float) -> bool:
    by: Dict[str, List[Dict]] = {}
    for r in rows:
        by.setdefault(str(r.get("slate_date") or ""), []).append(r)
    if "" in by and len(by) == 1:                                # undated rows (older callers): no slate check
        return True
    agree = 0
    for g in by.values():
        if len(g) >= HOLD_MIN_N:
            gr = _ratio(g)
            agree += 1 if gr is not None and (gr - 1) * (step - 1) > 0 else 0
    if agree < HOLD_SLATES:
        return False
    lo, hi = SUGGEST_RANGE
    before = after = 0.0
    for d, te in by.items():
        tr = [r for k, g in by.items() if k != d for r in g]
        tr_ratio = _ratio(tr) if tr else None
        if tr_ratio is None:
            continue
        m = max(lo, min(hi, 1 + STEP * (tr_ratio - 1)))
        before += sum(abs(r["actual"] - r["projection"]) for r in te)
        after += sum(abs(r["actual"] - r["projection"] * m) for r in te)
    return after < before


def suggestions(graded: Sequence[Dict], active: Optional[Dict[Tuple[str, str, str], float]] = None) -> List[Dict]:
    """[{"kind": "tuning" | "advice", "sport", "market", "slot", "factor", "n", "text"}] from graded props (all dates
    in the window). Tuning suggestions are approvable multipliers; advice needs a code change."""
    active = active or {}
    g = [r for r in graded if r.get("result") in ("hit", "miss", "push") and r.get("actual") is not None
         and r.get("projection") is not None]
    out: List[Dict] = []
    by_m: Dict[Tuple[str, str], List[Dict]] = {}
    for r in g:
        by_m.setdefault((r["sport"], r["market"]), []).append(r)
    for (sport, market), rows in sorted(by_m.items()):
        ratio = _ratio(rows)
        if ratio is None or len(rows) < MIN_MARKET_N or abs(ratio - 1) < MARKET_BIAS:
            continue
        step = 1 + STEP * (ratio - 1)
        lo, hi = SUGGEST_RANGE
        if not holds_up(rows, max(lo, min(hi, step))):
            continue
        f = max(lo, min(hi, step)) * active.get((sport, market, ""), 1.0)
        out.append({"kind": "tuning", "sport": sport, "market": market, "slot": "", "factor": round(f, 3),
                    "n": len(rows), "text": f"{market}: results ran {ratio - 1:+.0%} vs the projections over "
                                            f"{len(rows)} graded props -- move {market} projections "
                                            f"{step - 1:+.0%}."})
    for (sport, market), rows in sorted(by_m.items()):
        mr = _ratio(rows) or 1.0
        by_s = {}
        for r in rows:
            by_s.setdefault(str(r.get("slot") or ""), []).append(r)
        for slot, srows in sorted(by_s.items()):
            sr = _ratio(srows)
            if not slot or sr is None or len(srows) < MIN_SLOT_N or abs(sr - 1) < SLOT_BIAS or abs(sr - mr) < MARKET_BIAS:
                continue
            step = 1 + STEP * (sr / mr - 1)
            lo, hi = SUGGEST_RANGE
            if not holds_up(srows, max(lo, min(hi, step))):
                continue
            f = max(lo, min(hi, step)) * active.get((sport, market, slot), 1.0)
            out.append({"kind": "tuning", "sport": sport, "market": market, "slot": slot, "factor": round(f, 3),
                        "n": len(srows), "text": f"{market} · {slot}: results ran {sr - 1:+.0%} vs the projections "
                                                 f"({len(srows)} props; the market overall {mr - 1:+.0%}) -- move "
                                                 f"{slot} {step - 1:+.0%}."})
    # Use tags
    for row in use_record(g):
        if row["Graded"] >= 20 and row["Use"] in (PE.USE_BOTH, PE.USE_PARLAY) and row["Hit rate"] < 0.55:
            out.append({"kind": "advice", "n": row["Graded"],
                        "text": f"{row['Use']} legs hit {row['Hit rate']:.0%} over {row['Graded']} -- below what a "
                                "parlay needs. Tighten the parlay rule (chance 60% -> 65% or cushion 15% -> 20%)."})
        if row["Graded"] >= 20 and row["Use"] == PE.USE_SINGLE and row["Hit rate"] < 0.50:
            out.append(_single_advice(g, row))
    # Market gaps: who was right when the line sat far from the projection
    gaps = [r for r in g if (r.get("gap") or "").startswith("big") and r.get("model_hit") is not None]
    if len(gaps) >= 12:
        right = sum(1 for r in gaps if r["model_hit"]) / len(gaps)
        if right <= 0.40:
            out.append({"kind": "advice", "n": len(gaps),
                        "text": f"When the line sat far from the projection the market was right {1 - right:.0%} of the "
                                f"time ({len(gaps)} props): keep these as Pass and lean further on the market."})
        elif right >= 0.60:
            out.append(_gap_advice(gaps, right))
    # Cause mix
    cc = cause_counts(g)
    misses = sum(cc.values())
    if misses >= 20:
        model_share = sum(cc.get(c, 0) for c in MODEL_CAUSES) / misses
        if model_share >= 0.5:
            out.append({"kind": "advice", "n": misses,
                        "text": f"{model_share:.0%} of misses came from volume or role (the model's opportunity "
                                "call), not the player. Look at the Role change / Volume rows below for the pattern."})
    return out



# --------------------------------------------------------------------------- did players beat the model? (Nov 5)
def beat_model(graded: Sequence[Dict], min_n: int = 20) -> List[Dict]:
    """Per market: how often the player finished ABOVE the projection, the typical actual / projection, and -- for the
    reads where the model took the Under -- how often the player went over the line anyway. Answers "is the model
    taking too many Unders?": if Under calls lose more than their stated chance says, they are."""
    by: Dict[str, List[Dict]] = {}
    for r in graded:
        if r.get("result") not in ("hit", "miss") or r.get("actual") is None or r.get("projection") is None:
            continue
        by.setdefault(r.get("market") or "?", []).append(r)
    out = []
    for m, rs in by.items():
        if len(rs) < min_n:
            continue
        proj = [r for r in rs if float(r["projection"]) > 0]
        above = [r for r in proj if float(r["actual"]) != float(r["projection"])]
        unders = [r for r in rs if (r.get("side") or "Over") == "Under"]
        overs = [r for r in rs if (r.get("side") or "Over") == "Over"]
        said_u = [float(r["chance"]) for r in unders if r.get("chance") is not None]
        said_o = [float(r["chance"]) for r in overs if r.get("chance") is not None]
        ratios = sorted(float(r["actual"]) / float(r["projection"]) for r in proj)
        out.append({"market": m, "n": len(rs),
                    "beat_proj": (sum(1 for r in above if float(r["actual"]) > float(r["projection"])) / len(above)) if above else None,
                    "median_ratio": ratios[len(ratios) // 2] if ratios else None,
                    "under_share": len(unders) / len(rs), "under_n": len(unders),
                    "under_beaten": (sum(1 for r in unders if r["result"] == "miss") / len(unders)) if unders else None,
                    "under_said": (sum(said_u) / len(said_u)) if said_u else None,
                    "over_n": len(overs), "over_hit": (sum(1 for r in overs if r["result"] == "hit") / len(overs)) if overs else None,
                    "over_said": (sum(said_o) / len(said_o)) if said_o else None})
    return sorted(out, key=lambda x: -x["n"])


# --------------------------------------------------------------------------- projection tunings learn too (Nov 10)
AUTO_TUNE_MIN_N = 40           # graded props for that market (or slot) since its current tuning went live
AUTO_TUNE_MIN_SLATES = 3


def auto_tunings(graded: Sequence[Dict], tunings: Sequence[Dict], morning: str, write: bool = True,
                 approve=None) -> List[Dict]:
    """Each tuning suggestion re-checked on ONLY the props graded since that market's current multiplier went live
    (a projection already carries the active multiplier, so older days would push the same correction twice), and
    applied when it still holds up there: 40+ props over 3+ slates, the leave-one-slate-out test, one step of at most
    10% a night. Returns the decisions."""
    since = {(t["sport"], t["market"], t.get("slot") or ""): str(t.get("approved_ts") or "")[:10] for t in tunings}
    active = {(t["sport"], t["market"], t.get("slot") or ""): float(t["factor"]) for t in tunings}
    out = []
    for sg in suggestions(graded, active):
        if sg.get("kind") != "tuning":
            continue
        key = (sg["sport"], sg["market"], sg.get("slot") or "")
        start = since.get(key, "")
        rows = [r for r in graded if r.get("sport") == sg["sport"] and r.get("market") == sg["market"]
                and (not key[2] or str(r.get("slot") or "") == key[2]) and str(r.get("slate_date") or "") >= start
                and r.get("result") in ("hit", "miss", "push") and r.get("actual") is not None
                and r.get("projection") is not None]
        dec = {**sg, "since": start or None, "n_since": len(rows), "applied": False}
        ratio = _ratio(rows) if rows else None
        slates = len({r.get("slate_date") for r in rows})
        lo, hi = SUGGEST_RANGE
        step = None if ratio is None else max(lo, min(hi, 1 + STEP * (ratio - 1)))
        if len(rows) < AUTO_TUNE_MIN_N or slates < AUTO_TUNE_MIN_SLATES:
            dec["why"] = f"not enough since its last change ({len(rows)} props over {slates} slates)"
        elif abs(ratio - 1) < (SLOT_BIAS if key[2] else MARKET_BIAS):
            dec["why"] = f"since its last change results ran {ratio - 1:+.0%} — inside the noise band"
        elif not holds_up(rows, step):
            dec["why"] = "didn't hold up slate by slate"
        else:
            new = round(step * active.get(key, 1.0), 3)
            dec.update(factor=new, why=f"results ran {ratio - 1:+.0%} vs the projections over {len(rows)} props, "
                                       f"{slates} slates, held up slate by slate")
            if write:
                import model_store as MS
                fn = approve or MS.approve_tuning
                dec["applied"] = bool(fn(key[0], key[1], new, f"auto {morning}: {dec['why']}", slot=key[2]))
        out.append(dec)
    return out


def auto_tuning_notes(decisions: Sequence[Dict]) -> List[str]:
    out = []
    for d in decisions:
        if d.get("applied"):
            where = d["market"] + (f" · {d['slot']}" if d.get("slot") else "")
            out.append(f"🤖 Learned overnight: {d['sport']} {where} projections now ×{d['factor']:.3f} — {d['why']}. "
                       "Undo on Postgame Review.")
    return out
