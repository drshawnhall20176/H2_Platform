"""
soccer_props.py — soccer player props for the Soccer Lab (Nov 13): anytime goalscorer, shots on target, shots.

UNTESTED -- shown for reference and tracked, never tagged. There's no free history of soccer prop prices to backtest
against, so the record has to be built live.

Model: a player's per-start rate over his team's last LOOKBACK matches (ESPN match summaries; a sub appearance counts
SUB_WEIGHT of a start), shrunk toward zero with PRIOR_STARTS empty starts, then scaled by how many goals the goals
model expects his team to score in THIS match versus against an average side at the same venue:
    anytime goal  P = 1 - exp(-goals_rate x factor)
    shots / SOT   Poisson(rate x factor) over the line
Assumes he starts; the books void most props for players who don't play, but a late sub appearance stands.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence

import soccer_data as D

LOOKBACK = 10
SUB_WEIGHT = 0.35
PRIOR_STARTS = 2.0
MARKETS = {"player_goal_scorer_anytime": "Anytime Goal", "player_shots_on_target": "Shots on Target",
           "player_shots": "Shots"}
STAT = {"Anytime Goal": "goals", "Shots on Target": "sot", "Shots": "shots"}
CACHE = "SOCCERP_{league}"          # results_archive key for parsed match summaries


def summaries(league: str, event_ids: Sequence[str], fetch: Callable = D._http, db_path: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Parsed player rows per match, from the archive cache when we have them (one ESPN request per new match)."""
    import model_store as MS
    key = CACHE.format(league=league)
    have = {str(r["id"]): r.get("rows") or [] for r in MS.load_results(key, db_path=db_path)}
    new = []
    for e in event_ids:
        if str(e) in have:
            continue
        rows = D.player_stats(league, str(e), fetch)
        if rows:
            have[str(e)] = rows
            new.append({"id": str(e), "date": "", "rows": rows})
    if new:
        MS.save_results(key, new, db_path=db_path)
    return {str(e): have.get(str(e), []) for e in event_ids}


def team_matches(results: Sequence[Dict], team: str, n: int = LOOKBACK) -> List[str]:
    """ESPN ids of the team's last n finished matches."""
    import soccer_picks as SP
    mine = [g for g in results if SP.team([g["home_team"], g["away_team"]], team)]
    mine.sort(key=lambda g: str(g.get("kickoff") or g.get("date")))
    return [str(g["id"]) for g in mine[-n:]]


def rates(rows_by_match: Dict[str, List[Dict]], team: str) -> Dict[str, Dict]:
    """Per player on `team`: weighted starts and per-start goals / shots / sot."""
    import soccer_picks as SP
    acc: Dict[str, Dict] = {}
    for rows in rows_by_match.values():
        for r in rows:
            if not SP.team([r["team"]], team):
                continue
            a = acc.setdefault(r["player"], {"w": 0.0, "goals": 0.0, "shots": 0.0, "sot": 0.0, "starts": 0,
                                             "position": r.get("position", "")})
            w = 1.0 if r.get("started") else SUB_WEIGHT
            a["w"] += w
            a["starts"] += bool(r.get("started"))
            for k in ("goals", "shots", "sot"):
                a[k] += r.get(k, 0.0)
    out = {}
    for name, a in acc.items():
        d = a["w"] + PRIOR_STARTS
        out[name] = {"starts": a["starts"], "apps_w": round(a["w"], 2), "position": a["position"],
                     **{k: a[k] / d for k in ("goals", "shots", "sot")}}
    return out


def _pois_over(mean: float, line: float) -> float:
    k = int(math.floor(line))                          # over 0.5 = at least 1, over 1.5 = at least 2
    return 1 - sum(math.exp(-mean) * mean ** i / math.factorial(i) for i in range(k + 1))


def chance(rate: Dict, market: str, line: Optional[float], factor: float) -> Optional[float]:
    m = rate.get(STAT[market], 0.0) * factor
    if market == "Anytime Goal":
        return 1 - math.exp(-m)
    if line is None:
        return None
    return _pois_over(m, float(line))


def factor(r: Dict, team_name: str, opp: str, home: bool) -> float:
    """Expected goals for the team in this match / against an average side at the same venue."""
    import soccer_model as M
    if team_name not in r["attack"] or opp not in r["attack"]:
        return 1.0
    return r["defense"][opp]                            # base, home edge and attack cancel out


def parse_prop_odds(data: Optional[Dict]) -> List[Dict]:
    """Event odds -> one row per (player, market, line) with the best US price and book (Over / Yes side only)."""
    best: Dict[tuple, Dict] = {}
    for b in (data or {}).get("bookmakers") or []:
        for m in b.get("markets") or []:
            mk = MARKETS.get(m.get("key"))
            if not mk:
                continue
            for o in m.get("outcomes") or []:
                nm = str(o.get("name"))
                if mk != "Anytime Goal" and nm.lower() != "over":
                    continue
                if mk == "Anytime Goal" and nm.lower() == "no":
                    continue
                player = o.get("description") or nm
                line = None if mk == "Anytime Goal" else o.get("point")
                k = (player, mk, line)
                d = D._dec(o.get("price"))
                if d and (k not in best or d > D._dec(best[k]["price"])):
                    best[k] = {"player": player, "market": mk, "line": line, "price": o.get("price"), "book": b.get("key")}
    return list(best.values())


def fetch_props(league: str, event_id: str, api_key: str, fetch: Callable = D._http) -> List[Dict]:
    data = fetch(D.EVENT_ODDS.format(key=D.LEAGUES[league]["odds"], event=event_id),
                 {"apiKey": api_key, "regions": "us", "markets": ",".join(MARKETS), "oddsFormat": "american"})
    return parse_prop_odds(data)


def read(props: Sequence[Dict], rec: Dict, r: Dict, home_rates: Dict, away_rates: Dict) -> List[Dict]:
    """Each priced prop with the model's chance and EV (players the model has no rate for are kept, unread)."""
    import soccer_picks as SP
    h, a = SP.team(r["attack"], rec["home"]), SP.team(r["attack"], rec["away"])
    fh = factor(r, h, a, True) if h and a else 1.0
    fa = factor(r, a, h, False) if h and a else 1.0
    out = []
    for p in props:
        side, rate = None, None
        for nm, rr in home_rates.items():
            if _same_player(nm, p["player"]):
                side, rate = "home", rr
                break
        if rate is None:
            for nm, rr in away_rates.items():
                if _same_player(nm, p["player"]):
                    side, rate = "away", rr
                    break
        ch = chance(rate, p["market"], p.get("line"), fh if side == "home" else fa) if rate else None
        d = D._dec(p["price"])
        out.append(dict(p, team=rec["home"] if side == "home" else (rec["away"] if side == "away" else ""),
                        starts=(rate or {}).get("starts"), chance=None if ch is None else round(ch, 4),
                        ev=None if ch is None or not d else round(ch * d - 1, 4)))
    out.sort(key=lambda x: -(x["ev"] if x["ev"] is not None else -9))
    return out


def _same_player(a: str, b: str) -> bool:
    import props_engine as PE
    na, nb = PE.norm_name(a), PE.norm_name(b)
    if na == nb:
        return True
    ta, tb = na.split(), nb.split()
    return bool(ta and tb and ta[-1] == tb[-1] and ta[0][:1] == tb[0][:1])


# --------------------------------------------------------------------------- settling logged prop bets
def prop_result(bet: Dict, rows: Sequence[Dict]) -> Optional[str]:
    """A logged soccer prop against the match summary; None when the player isn't in it (didn't play: void)."""
    me = next((r for r in rows if _same_player(r["player"], str(bet.get("player")))), None)
    if me is None:
        return None
    v = me.get(STAT.get(bet.get("market"), ""), None)
    if v is None:
        return None
    if bet.get("market") == "Anytime Goal":
        return "win" if v >= 1 else "loss"
    line = bet.get("line")
    if line is None:
        return None
    over = str(bet.get("side")).lower() in ("over", "yes")
    return "win" if (v > float(line)) == over else "loss"


def settle_props(league: str, db_path: Optional[str] = None, fetch: Callable = D._http) -> int:
    """Open SOCCER prop bets logged from this league's page (notes carry sp:<league>:<espn-less odds event id> and the
    match "away @ home"): grade from the ESPN summary once the match is final."""
    import betlog as B
    import model_store as MS
    import soccer_picks as SP
    results = MS.load_results(league, db_path=db_path)
    n = 0
    for b in [x for x in B.list_bets() if not x.get("result") and x.get("sport") == "SOCCER"
              and x.get("market") in STAT and f"sp:{league}" in str(x.get("notes") or "")]:
        away, _, home = str(b.get("game") or "").partition(" @ ")
        day = str(b.get("slate_date") or "")
        g = next((g for g in results if abs((_d(g["date"]) - _d(day)).days) <= 1
                  and SP.team([g["home_team"]], home) and SP.team([g["away_team"]], away)), None) if day else None
        if not g:
            continue
        rows = summaries(league, [g["id"]], fetch, db_path).get(str(g["id"])) or []
        r = prop_result(b, rows)
        if r:
            B.update_bet(int(b["id"]), result=r)
            n += 1
    return n


def _d(s: str):
    from datetime import date
    return date.fromisoformat(str(s)[:10])
