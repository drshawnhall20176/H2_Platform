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
        "NBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"}
FAMILY = {"NFL": "football", "NCAAF": "football", "NBA": "basketball"}
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
    if sport == "NCAAF":
        params["groups"] = 80
    board = fetch(f"{base}/scoreboard", params) or {}
    events = []
    for ev in board.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        teams = [c.get("team") or {} for c in comp.get("competitors") or []]
        events.append((ev.get("id"), [_aliases(t) for t in teams]))
    parse = basketball_box if FAMILY.get(sport) == "basketball" else football_box
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
    if FAMILY.get(sport) == "basketball":
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
    if FAMILY.get(sport) == "basketball":
        import player_props as PPR
        return PPR.market_value(stats, market) if market in PPR.MARKETS else None
    import football_props as FP
    return FP.market_value(stats, market) if market in FP.MARKETS else None


def actual_volume(sport: str, market: str, stats: Dict) -> Optional[float]:
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
            out.append({"kind": "advice", "n": row["Graded"],
                        "text": f"{row['Use']} plays hit {row['Hit rate']:.0%} over {row['Graded']}. Raise the edge "
                                "a single needs (+3% -> +5%)."})
    # Market gaps: who was right when the line sat far from the projection
    gaps = [r for r in g if (r.get("gap") or "").startswith("big") and r.get("model_hit") is not None]
    if len(gaps) >= 12:
        right = sum(1 for r in gaps if r["model_hit"]) / len(gaps)
        if right <= 0.40:
            out.append({"kind": "advice", "n": len(gaps),
                        "text": f"When the line sat far from the projection the market was right {1 - right:.0%} of the "
                                f"time ({len(gaps)} props): keep these as Pass and lean further on the market."})
        elif right >= 0.60:
            out.append({"kind": "advice", "n": len(gaps),
                        "text": f"When the line sat far from the projection the MODEL was right {right:.0%} of the time "
                                f"({len(gaps)} props): the news check may be too cautious -- give the model more vote."})
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
