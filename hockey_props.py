"""
hockey_props.py — Position Matchups' Player props for the NHL. PURE LOGIC, NO NETWORK (position_data.load_hockey
loads the games). Hockey props are opportunity-first even more than basketball:

    skater projection = rate per minute of ice time x projected ice time (TOI) x opponent factor x game environment
    goalie saves      = save rate x shots he'll face (the opponent's shots-for vs league) x environment

  * TOI is the volume: a top-line forward plays 19-21 minutes, a fourth-liner 9-11; power-play time is inside it.
  * The opponent factor is what this opponent allows (shots, goals) -- or for saves and blocked shots, how much it
    shoots -- against the league, shrunk while the sample is small.
  * Next man up: a skater freshly ruled out has his ice time spread to his own position group (forwards / D).
  * Back-to-backs matter more than in basketball: skaters dip, and a goalie who played last night usually sits --
    the GOALIE is the biggest single swing in every scoring prop, so the starter is flagged, never assumed.
  * Every skater market is a low count (shots, points, goals, assists, blocks): negative binomial / Poisson, never a
    normal curve. Goals at 0.5 is "anytime goal".
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import props_engine as PE

MARKETS: Dict[str, Dict] = {
    "Shots on Goal": {"stat": "sog", "dist": "count", "odds": "player_shots_on_goal", "role": "skater",
                      "opp_side": "allowed", "opp_stat": "sog", "env": 0.4},
    "Points":        {"stat": "pts", "dist": "count", "odds": "player_points", "role": "skater",
                      "opp_side": "allowed", "opp_stat": "goals", "env": 0.9},
    "Goals":         {"stat": "g", "dist": "count", "odds": "player_goals", "role": "skater",
                      "opp_side": "allowed", "opp_stat": "goals", "env": 1.0},
    "Assists":       {"stat": "a", "dist": "count", "odds": "player_assists", "role": "skater",
                      "opp_side": "allowed", "opp_stat": "goals", "env": 0.9},
    "Blocked Shots": {"stat": "blk", "dist": "count", "odds": "player_blocked_shots", "role": "skater",
                      "opp_side": "for", "opp_stat": "sog", "env": 0.2},
    "Saves":         {"stat": "saves", "dist": "normal", "odds": "player_total_saves", "role": "goalie",
                      "opp_side": "for", "opp_stat": "sog", "env": 0.3},
}
DEFAULT_MARKET = "Shots on Goal"
MARKET_HELP = {"Goals": "0.5 = anytime goal", "Points": "goals + assists", "Saves": "the starting goalie only"}
MIN_TOI = 10.0
MAX_SKATERS = 14
TOI_CAP = {"F": 24.0, "D": 28.0}
FACTOR_RANGE = (0.80, 1.20)
SHRINK_K = 10.0
FORM_N = 10
PRIMER = (
    "**New to hockey props? The four things that move them most.** "
    "**1) Ice time is volume** — a top-line forward plays ~19–21 min, a 4th-liner ~10; power-play units get the "
    "points. **2) The goalie** — a backup in net lifts every scoring prop for the other side, and starters usually "
    "sit the second night of a back-to-back (the starter is only confirmed ~90 min before puck drop). "
    "**3) Everything is a small count** — 2.5 shots, 0.5 points: one bounce decides it, so price matters more than "
    "in basketball. **4) Back-to-backs and travel** hurt more than in the NBA.")


def group(pos) -> Optional[str]:
    p = str(pos or "").upper()
    if p in ("C", "LW", "RW", "F", "W"):
        return "F"
    if p in ("D", "LD", "RD"):
        return "D"
    if p == "G":
        return "G"
    return None


def team_lines(pgames: Sequence[Dict]) -> Dict:
    """{(game, team): {"goals","sog","blk","saves","sa","opp"}} summed from the player lines."""
    out: Dict = {}
    for p in pgames or []:
        k = (p.get("game"), p.get("team"))
        t = out.setdefault(k, {"goals": 0.0, "sog": 0.0, "blk": 0.0, "saves": 0.0, "sa": 0.0, "opp": p.get("opp"),
                               "order": p.get("order")})
        s = p.get("stats") or {}
        t["goals"] += PE.num(s.get("g"))
        t["sog"] += PE.num(s.get("sog"))
        t["blk"] += PE.num(s.get("blk"))
        t["saves"] += PE.num(s.get("saves"))
        t["sa"] += PE.num(s.get("sa"))
    return out


def opponent_factor(pgames, opp, side: str, stat: str) -> Optional[Dict]:
    """What `opp` allows (side "allowed": the other team's `stat` in its games) or does itself (side "for"),
    vs the sample's league average per team-game. {"factor", "games", "raw"} -- shrunk by n / (n + 10)."""
    tl = team_lines(pgames)
    vals = []
    for (g, t), rec in tl.items():
        if side == "for" and t == opp:
            vals.append(rec[stat])
        elif side == "allowed" and rec.get("opp") == opp and t != opp:
            vals.append(rec[stat])
    league = [rec[stat] for rec in tl.values()]
    if not vals or not league or not sum(league):
        return None
    lg = sum(league) / len(league)
    raw = (sum(vals) / len(vals)) / lg if lg else 1.0
    w = len(vals) / (len(vals) + SHRINK_K)
    lo, hi = FACTOR_RANGE
    return {"factor": min(hi, max(lo, 1 + (raw - 1) * w)), "games": len(vals), "raw": raw}


def team_goals(pgames, team) -> Optional[float]:
    vals = [rec["goals"] for (g, t), rec in team_lines(pgames).items() if t == team]
    return sum(vals) / len(vals) if vals else None


def _games(pgames, pid, n: int = FORM_N, role: Optional[str] = None) -> List[Dict]:
    mine = [p for p in pgames or [] if p.get("pid") == pid and PE.num((p.get("stats") or {}).get("toi")) > 0
            and (role is None or p.get("role") == role)]
    if role == "goalie":
        mine = [p for p in mine if (p.get("stats") or {}).get("gs")]
    mine.sort(key=lambda p: (p.get("order") is None, p.get("order")), reverse=True)
    return mine[:n]


def rotation(pgames, team, injuries: Optional[Dict[str, str]] = None, last_games: int = 5) -> Dict[str, List[Dict]]:
    """{"skaters": [{"pid","name","slot","avg_toi","status"}] most ice time first, "goalies": [likely starter
    first]} from the team's last `last_games` games."""
    injuries = injuries or {}
    games = []
    for p in pgames or []:
        if p.get("team") == team and p.get("game") not in [g for g, _ in games]:
            games.append((p.get("game"), p.get("order")))
    games.sort(key=lambda g: (g[1] is None, g[1]), reverse=True)
    recent = {g for g, _ in games[:last_games]}
    agg: Dict = {}
    for p in pgames or []:
        if p.get("team") != team or p.get("game") not in recent:
            continue
        a = agg.setdefault(p["pid"], {"pid": p["pid"], "name": p.get("name"), "slot": group(p.get("pos")),
                                      "role": p.get("role"), "toi": [], "starts": [], "last": None})
        a["toi"].append(PE.num((p.get("stats") or {}).get("toi")))
        if (p.get("stats") or {}).get("gs"):
            a["starts"].append(p.get("order"))
    skaters, goalies = [], []
    for a in agg.values():
        rec = {"pid": a["pid"], "name": a["name"], "slot": a["slot"], "avg_toi": sum(a["toi"]) / len(a["toi"]),
               "status": injuries.get(a["name"]), "games": len(a["toi"])}
        if a["role"] == "goalie":
            if a["starts"]:
                rec["last_start"] = max(a["starts"])
                rec["starts"] = len(a["starts"])
                goalies.append(rec)
        elif rec["avg_toi"] >= MIN_TOI and rec["slot"] in ("F", "D"):
            skaters.append(rec)
    skaters.sort(key=lambda r: -r["avg_toi"])
    # Likely starter first: the most recent start, unless he's ruled out (then the other goalie).
    goalies.sort(key=lambda r: str(r.get("last_start") or ""), reverse=True)
    goalies.sort(key=lambda r: str(r.get("status") or "").strip().lower() in ("out", "injured reserve", "ir"))
    return {"skaters": skaters[:MAX_SKATERS], "goalies": goalies}


def player_rows(rot: Dict[str, List[Dict]], team, opp, market: str, pgames, lines: Optional[Dict] = None,
                context: Optional[Dict] = None) -> List[Dict]:
    """One row per skater (or the likely starting goalie for Saves). context: rest_days, opp_rest_days, env
    (THIS team's implied-goals factor), opp_env, offers, prices, slope, model_weight, team_games (newest first)."""
    m = MARKETS[market]
    ctx = context or {}
    lines, prices = lines or {}, ctx.get("prices") or {}
    of = opponent_factor(pgames, opp, m["opp_side"], m["opp_stat"])
    factor = of["factor"] if of else 1.0
    rows: List[Dict] = []
    if m["role"] == "goalie":
        players = rot.get("goalies") or []
        players = players[:2]
    else:
        players = rot.get("skaters") or []
    team_games = ctx.get("team_games") or []
    base = []
    for r in players:
        g = _games(pgames, r["pid"], role=m["role"])
        vals = [PE.num((x.get("stats") or {}).get(m["stat"])) for x in g]
        if m["role"] == "goalie":
            opps = [PE.num((x.get("stats") or {}).get("sa")) for x in g]
        else:
            opps = [PE.num((x.get("stats") or {}).get("toi")) for x in g]
        rate, opp_avg = PE.rate_and_opportunity(vals, opps)
        out = str(r.get("status") or "").strip().lower() in ("out", "injured reserve", "ir")
        fresh = out and PE.fresh_absence([x.get("game") for x in g], team_games)
        base.append({"r": r, "vals": vals, "rate": rate, "opp": opp_avg, "out": out, "fresh": fresh, "games": g})
    shifts = {}
    if m["role"] == "skater":
        shifts = PE.redistribute([{"pid": b["r"]["pid"], "name": b["r"]["name"], "slot": b["r"]["slot"],
                                   "opp": b["opp"] or 0.0, "rate": b["rate"] or 0.0, "out": b["out"],
                                   "fresh": b["fresh"]} for b in base], cap=26.0)
    for idx, b in enumerate(base):
        r = b["r"]
        flags: List[str] = []
        proj = opp_val = None
        env_mult = 1.0
        if not b["out"] and b["rate"] is not None:
            if m["role"] == "goalie":
                shots = (b["opp"] or 0.0) * factor
                env_mult = 1 + m["env"] * ((ctx.get("opp_env") or 1.0) - 1)
                rest = PE.rest_effect(ctx.get("rest_days"), ctx.get("opp_rest_days"), 60.0, "hockey", role="goalie")
                flags += rest["flags"]
                if idx == 0:
                    flags.append("likely starter (unconfirmed)")
                else:
                    flags.append("backup — only if he starts")
                opp_val = shots
                proj = b["rate"] * shots * env_mult
            else:
                sh = shifts.get(r["pid"], {"opp_add": 0.0, "rate_mult": 1.0, "from": []})
                toi = (b["opp"] or 0.0) + sh["opp_add"]
                cap = TOI_CAP.get(r.get("slot") or "F", 24.0)
                toi = min(toi, max(cap, b["opp"] or 0.0))
                if sh["from"]:
                    flags.append("↑ more ice time (" + ", ".join(n for n in sh["from"] if n) + " out)")
                rest = PE.rest_effect(ctx.get("rest_days"), ctx.get("opp_rest_days"), toi, "hockey")
                flags += rest["flags"]
                env_mult = 1 + m["env"] * ((ctx.get("env") or 1.0) - 1)
                opp_val = toi
                proj = b["rate"] * sh["rate_mult"] * rest["rate_mult"] * toi * factor * env_mult
        key = r["pid"]
        line = PE.maybe(lines.get(key))
        line_src = "typed" if line is not None else None
        book = None
        if ctx.get("offers") and m["odds"]:
            mine = PE.offers_for(ctx["offers"], r.get("name"), m["odds"])
            book = PE.shop(mine, line, ctx.get("book")) if line is not None else PE.shop(mine, None, ctx.get("book"))
            if line is None and book:
                line, line_src = book["line"], "book"
        tp = prices.get(key) or {}
        t_over, t_under = PE.maybe(tp.get("over")), PE.maybe(tp.get("under"))
        if t_over is not None or t_under is not None:
            over_p, under_p, price_src, p_mkt = t_over, t_under, "manual", None
        elif book:
            over_p = book["best_over"][1] if book.get("best_over") else None
            under_p = book["best_under"][1] if book.get("best_under") else None
            price_src, p_mkt = "book", book.get("p_market")
        else:
            over_p = under_p = price_src = p_mkt = None
        floor = (0.12, 3.0) if m["dist"] == "normal" else (0.25, 1.0)
        read = PE.read_line(proj, b["vals"], line, m["dist"], over_p, under_p, p_mkt, ctx.get("slope", 1.0),
                            ctx.get("model_weight", PE.MODEL_WEIGHT), *floor, news_checked=bool(ctx.get("news_checked")))
        hits = [v for v in b["vals"] if line is not None and PE.clears(v, line)]
        rows.append({
            "pid": key, "player": r.get("name"), "slot": r.get("slot"), "status": r.get("status"), "out": b["out"],
            "opp": opp_val, "form": PE.wmean(b["vals"]) if b["vals"] else None, "games": len(b["vals"]),
            "filled": False, "factor": factor, "env": env_mult,
            "projection": proj, "line": line, "line_src": line_src, "over_price": over_p, "under_price": under_p,
            "price_src": price_src, "book": book,
            "hit": (len(hits), len(b["vals"])) if line is not None and b["vals"] else None,
            "p_model": read["p_model"], "p_market": read["p_market"], "p_final": read["p_final"], "gap": read.get("gap"), "gap_pct": read.get("gap_pct"),
            "side": read["side"], "ev": read["ev"], "lean": read["lean"], "flags": flags, "dist": m["dist"],
            "values": list(b["vals"]), "sd_floor": floor,
        })
    return rows


def display(rows: Sequence[Dict], market: str) -> List[Dict]:
    return PE.display(rows, "Shots faced" if MARKETS[market]["role"] == "goalie" else "TOI")


def plays_for_log(rows: Sequence[Dict], market: str, game_label: str) -> List[Dict]:
    return PE.plays_for_log(rows, market, game_label)


def pgames_from_games(games: Dict[str, Dict], names: Dict[int, Dict]) -> List[Dict]:
    """nhl_engine.get_game records ({gid: {"date", "home", "away", "rec"}}) -> player-game lines.
    names: {player id: {"name", "pos"}} from the rosters (ESPN's summary carries no names)."""
    out: List[Dict] = []
    for gid, g in (games or {}).items():
        rec = g.get("rec") or {}
        teams = [g.get("home"), g.get("away")]
        for pid, p in (rec.get("players") or {}).items():
            tid = p.get("team_id")
            if tid not in teams:
                continue
            opp = teams[1] if tid == teams[0] else teams[0]
            nm = names.get(pid) or {}
            stats = {"toi": p.get("toi"), "min": p.get("toi")}
            if p.get("role") == "goalie":
                stats.update(saves=p.get("saves"), sa=p.get("sa"), ga=p.get("ga"), gs=bool(p.get("gs")))
            else:
                stats.update(g=p.get("g"), a=p.get("a"), pts=p.get("pts"), sog=p.get("sog"), blk=p.get("blk"))
            out.append({"game": gid, "order": g.get("date"), "team": tid, "opp": opp, "pid": pid,
                        "name": nm.get("name") or f"#{pid}", "pos": nm.get("pos") or p.get("pos"),
                        "role": p.get("role"), "stats": stats})
    return out
