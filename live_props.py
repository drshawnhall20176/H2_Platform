"""
live_props.py — live player props (Nov 12). For a game in progress: each player's stat so far (ESPN's live box
score), the pre-game prop projection (the props model's saved read for tonight, model_store snapshots), and the
time left -> the projected final and the chance of going over / under any line, including the books' live lines.

  remaining = pre-game projection x share of the game left x playing-time factor
    playing-time factor (basketball / hockey): how much he's actually played so far vs what was expected (foul
    trouble, an injury, a blowout benching) -- 0.3x to 1.3x, plus a cut for 5 fouls or a big late lead
  chance of the line = the stat so far + the remaining amount, spread the way the props model spreads it
    (counts: Poisson-like with a little extra spread; points / yards: normal, narrowing as the game runs down)

The live lines (Odds API in-play player props) are fetched only on request -- about one credit per market.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence

import live_model as LM

BASKETBALL = {"Points": ["PTS"], "Rebounds": ["REB"], "Assists": ["AST"], "Blocks": ["BLK"], "Steals": ["STL"],
              "Threes Made": ["3PT"], "Turnovers": ["TO"], "PRA": ["PTS", "REB", "AST"], "PR": ["PTS", "REB"],
              "PA": ["PTS", "AST"], "RA": ["REB", "AST"], "PB": ["PTS", "BLK"], "Pts+Reb+Ast": ["PTS", "REB", "AST"],
              "Pts+Reb": ["PTS", "REB"], "Pts+Ast": ["PTS", "AST"], "Reb+Ast": ["REB", "AST"]}
HOCKEY = {"Shots on Goal": ["SOG"], "Goals": ["G"], "Assists": ["A"], "Points": ["G", "A"], "Blocked Shots": ["BS"],
          "Saves": ["SV"]}
FOOTBALL = {"Pass Yards": ["passing:YDS"], "Passing TDs": ["passing:TD"], "Pass Completions": ["passing:C/ATT#0"],
            "Pass Attempts": ["passing:C/ATT#1"], "Interceptions": ["passing:INT"], "Rush Yards": ["rushing:YDS"],
            "Rush Attempts": ["rushing:CAR"], "Receptions": ["receiving:REC"], "Receiving Yards": ["receiving:YDS"],
            "Targets": ["receiving:TGTS"], "Rush + Rec Yards": ["rushing:YDS", "receiving:YDS"],
            "Tackles + Assists": ["defensive:TOT"], "Solo Tackles": ["defensive:SOLO"], "Sacks": ["defensive:SACKS"]}
NORMAL = {"Points", "PRA", "PR", "PA", "RA", "PB", "Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Pass Yards", "Rush Yards",
          "Receiving Yards", "Rush + Rec Yards", "Saves"}
EXTRA_ODDS_KEYS = {"PRA": "player_points_rebounds_assists", "PR": "player_points_rebounds",
                   "PA": "player_points_assists", "RA": "player_rebounds_assists",
                   "Rush + Rec Yards": "player_rush_reception_yds", "Targets": "player_receptions"}


def stat_map(league: str) -> Dict[str, List[str]]:
    c = LM.cfg(league)
    return FOOTBALL if c.get("football") else HOCKEY if c.get("hockey") else BASKETBALL


def _norm(name) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    for suf in (" jr.", " jr", " sr.", " iii", " ii", " iv"):
        s = s.replace(suf, "")
    return "".join(ch for ch in s if ch.isalnum() or ch == " ").strip()


def _num(v, idx: Optional[int] = None) -> Optional[float]:
    s = str(v or "").strip()
    if not s or s in ("--", "-"):
        return None
    if ":" in s:                                                 # 15:11 time on ice -> minutes
        try:
            mm, ss = s.split(":")[:2]
            return int(mm) + float(ss) / 60
        except ValueError:
            return None
    for sep in ("/", "-"):
        if sep in s[1:]:
            parts = s.split(sep)
            try:
                return float(parts[idx or 0])
            except (ValueError, IndexError):
                return None
    try:
        return float(s)
    except ValueError:
        return None


def box(summary: Dict) -> Dict[str, Dict]:
    """{normalized player name: {"name", "team", label or "block:label": raw value}} from an ESPN summary."""
    out: Dict[str, Dict] = {}
    for team in ((summary or {}).get("boxscore") or {}).get("players") or []:
        tname = (team.get("team") or {}).get("displayName")
        for blk in team.get("statistics") or []:
            bname = blk.get("name")
            labels = blk.get("labels") or []
            for a in blk.get("athletes") or []:
                nm = (a.get("athlete") or {}).get("displayName")
                if not nm:
                    continue
                rec = out.setdefault(_norm(nm), {"name": nm, "team": tname})
                rec["dnp"] = bool(a.get("didNotPlay")) or rec.get("dnp", False)
                for lab, val in zip(labels, a.get("stats") or []):
                    rec[lab] = val
                    if bname:
                        rec[f"{bname}:{lab}"] = val
    return out


def current(rec: Dict, market: str, league: str) -> Optional[float]:
    keys = stat_map(league).get(market)
    if not keys or not rec:
        return None
    total = 0.0
    for k in keys:
        idx = None
        if "#" in k:
            k, i = k.split("#")
            idx = int(i)
        v = rec.get(k)
        if v is None:
            if ":" in k:                                         # a player with no line in that block yet = 0
                continue
            return None
        n = _num(v, idx)
        if n is None:
            return None
        total += n
    return total


def minutes_played(rec: Dict, league: str) -> Optional[float]:
    c = LM.cfg(league)
    if c.get("football"):
        return None
    return _num(rec.get("TOI") if c.get("hockey") else rec.get("MIN"))


def playing_factor(rec: Dict, league: str, elapsed: float, expected_minutes: Optional[float],
                   margin: float, share_left: float) -> float:
    """How much of his normal share of the rest of the game he's likely to play."""
    c = LM.cfg(league)
    if c.get("football") or not rec:
        return 1.0
    f = 1.0
    mp = minutes_played(rec, league)
    L = LM.game_minutes(league)
    if mp is not None and elapsed >= 6 and expected_minutes and 4 <= expected_minutes <= L:
        ratio = (mp / elapsed) / (expected_minutes / L)
        f = max(0.3, min(1.3, 0.5 + 0.5 * ratio))
    if not c.get("hockey"):
        fouls = _num(rec.get("PF"))
        if fouls is not None and fouls >= 5:
            f *= 0.7
        if share_left < 0.25 and abs(margin) >= 20:             # a blowout late: regulars sit
            f *= 0.6
    return f


def chance_over(market: str, now: float, remaining_mean: float, share_left: float, pre_projection: float,
                line: float, league: str) -> float:
    """Chance the final stat beats `line`, given `now` so far and `remaining_mean` still to come."""
    if now > line:
        return 1.0
    if remaining_mean <= 1e-9:
        return 0.0 if now <= line else 1.0
    if market in NORMAL:
        football = LM.cfg(league).get("football")
        sd_full = max(0.45 * pre_projection, 8.0) if football else max(0.25 * pre_projection, 1.0) \
            if market == "Saves" else max(0.3 * pre_projection, 2.0)
        sd = max(sd_full * math.sqrt(max(share_left, 1e-6)), 0.5)
        return 1 - LM._phi((line - now - remaining_mean) / sd)
    import props_engine as PE
    need = int(math.floor(line - now)) + 1
    if need <= 0:
        return 1.0
    return PE.count_sf(remaining_mean, remaining_mean * 1.25, need)


def read_props(g: Dict, read: Dict, snaps: Sequence[Dict], summary: Dict) -> List[Dict]:
    """One row per saved pre-game prop read for this game's players: now, projected final, chances."""
    league = g["league"]
    bx = box(summary)
    L = LM.game_minutes(league)
    share = read["share_left"]
    elapsed = read["minutes_played"]
    margin = g["home_score"] - g["away_score"]
    out = []
    for s in snaps:
        rec = bx.get(_norm(s.get("player")))
        if not rec or rec.get("dnp"):
            continue
        mk = s.get("market")
        now = current(rec, mk, league)
        proj = s.get("projection")
        if now is None or proj is None:
            continue
        exp_min = s.get("proj_opp") if not LM.cfg(league).get("football") else None
        pf = playing_factor(rec, league, elapsed, exp_min, margin, share)
        rem = max(float(proj), 0.0) * share * pf
        line = s.get("line")
        p_over = None if line is None else chance_over(mk, now, rem, share, float(proj), float(line), league)
        out.append({"player": s.get("player"), "market": mk, "now": now, "projected": now + rem,
                    "pre_projection": float(proj), "pre_line": line, "p_over_pre": p_over,
                    "minutes": minutes_played(rec, league), "factor": pf, "remaining": rem})
    return out


def odds_key(league: str, market: str) -> Optional[str]:
    import sports
    try:
        mm = sports.get(league).market_map or {}
    except Exception:                                           # noqa: BLE001
        mm = {}
    return mm.get(market) or EXTRA_ODDS_KEYS.get(market)


def live_prop_lines(league: str, event_id: str, markets: Sequence[str], api_key: str,
                    fetch: Optional[Callable] = None) -> List[Dict]:
    """In-play player prop lines for one Odds API event: [{"player", "market", "line", "over", "under"}]."""
    import odds_api as O
    import sports
    keys = sorted({k for k in (odds_key(league, m) for m in markets) if k})
    if not keys or not api_key or not event_id:
        return []
    fetch = fetch or (lambda eid, ks: O.fetch_event_props(eid, api_key, ks, sport=sports.get(league).odds_sport_key)[0])
    data = fetch(event_id, keys) or {}
    back = {}
    for m in markets:
        k = odds_key(league, m)
        if k:
            back.setdefault(k, m)
    best: Dict[tuple, Dict] = {}
    for bk in data.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            name = back.get(mk.get("key"))
            if not name:
                continue
            for o in mk.get("outcomes") or []:
                if o.get("point") is None or o.get("description") is None:
                    continue
                k = (_norm(o["description"]), name, float(o["point"]))
                row = best.setdefault(k, {"player": o["description"], "market": name, "line": float(o["point"]),
                                          "over": None, "under": None, "book": bk.get("key")})
                side = str(o.get("name") or "").lower()
                if side in ("over", "under") and o.get("price") is not None:
                    if row[side] is None or float(o["price"]) > row[side]:
                        row[side] = float(o["price"])
    return list(best.values())


def check_lines(rows: Sequence[Dict], lines: Sequence[Dict], league: str, share: float) -> List[Dict]:
    """The books' live prop lines priced with the live read: chance, edge, signal."""
    by = {}
    for r in rows:
        by[(_norm(r["player"]), r["market"])] = r
    out = []
    for ln in lines:
        r = by.get((_norm(ln["player"]), ln["market"]))
        if not r:
            continue
        po = chance_over(r["market"], r["now"], r["remaining"], share, r["pre_projection"], ln["line"], league)
        for side, ch, price in (("Over", po, ln.get("over")), ("Under", 1 - po, ln.get("under"))):
            if price is None:
                continue
            e = LM.edge(ch, price)
            out.append({"player": r["player"], "bet": f"{r['player']} {r['market']} {side} {ln['line']:g}",
                        "now": r["now"], "projected": r["projected"], "chance": ch, "price": price, "edge": e,
                        "signal": "🟢 Worth a look" if e >= 0.05 else "🟡 Close" if e >= 0 else "🔴 Pass"})
    return sorted(out, key=lambda b: -b["edge"])
