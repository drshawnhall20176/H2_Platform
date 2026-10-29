"""
football_props.py — Position Matchups' Player props for NFL and college football. PURE LOGIC, NO NETWORK.

Same idea as basketball (player_props.py), built opportunity-first because football volume is the whole game:

    projection = OPPORTUNITY (targets / carries / pass attempts, recency weighted)
               x EFFICIENCY (yards or TDs per opportunity, shrunk toward the position's league rate)
               x MATCHUP (what this defense allows to the slot he fills, shrunk while its sample is small)
               x GAME SCRIPT (favorites run more, underdogs throw more -- from the spread)
               x GAME ENVIRONMENT (implied team total from the spread + total vs a normal team total)

NEXT MAN UP: the depth chart already promotes the backup when a starter is OUT (position_matchups.
promote_for_absences). Here the OUT player's volume moves too: his targets go to the remaining pass catchers (the
promoted player gets a larger share), his carries mostly to the back who replaced him, a QB's attempts to the QB
who replaced him. A promoted player's efficiency leans harder on the position's league rate (his own came in a
smaller role).

Distributions: receptions, TDs and attempts are counts (negative binomial / Poisson); yards are a normal curve with
a wide floor (yardage is lumpy). College football has no targets in its feed, so receptions stand in for targets.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import player_props as PPR
import props_engine as PE

# market -> (stat keys summed, opportunity kind, distribution, Odds API key, slots offered)
RECEIVERS = ("WR1", "WR2", "WR3", "TE1", "RB1", "RB2")
MARKETS: Dict[str, Dict] = {
    "Receptions":     {"stats": ("rec",), "opp": "tgt", "dist": "count", "odds": "player_receptions", "slots": RECEIVERS},
    "Receiving Yards":  {"stats": ("rec_yds",), "opp": "tgt", "dist": "normal", "odds": "player_reception_yds",
                       "slots": RECEIVERS},
    "Rush Yards":       {"stats": ("rush_yds",), "opp": "rush_att", "dist": "normal", "odds": "player_rush_yds",
                       "slots": ("RB1", "RB2", "QB")},
    "Rush + Rec Yards": {"stats": ("rush_yds", "rec_yds"), "opp": "touch", "dist": "normal",
                       "odds": "player_rush_reception_yds", "slots": ("RB1", "RB2", "WR1", "WR2", "TE1")},
    "Pass Yards":       {"stats": ("pass_yds",), "opp": "pass_att", "dist": "normal", "odds": "player_pass_yds",
                       "slots": ("QB",)},
    "Passing TDs":       {"stats": ("pass_td",), "opp": "pass_att", "dist": "count", "odds": "player_pass_tds",
                       "slots": ("QB",)},
    # Oct 29: QB volume props. Attempts move with game script (the spread) more than with scoring, and their spread is
    # wider than a plain count's, so they read on a normal curve with their own floor (sd >= 18% / 5 attempts).
    "Pass Attempts":    {"stats": ("pass_att",), "opp": "pass_att", "dist": "normal", "odds": "player_pass_attempts",
                       "slots": ("QB",), "floor": (0.18, 5.0)},
    "Pass Completions": {"stats": ("pass_cmp",), "opp": "pass_att", "dist": "normal", "odds": "player_pass_completions",
                       "slots": ("QB",), "floor": (0.20, 3.5), "sports": ("NFL",)},   # the college feed has no completions
    "Rush Attempts":       {"stats": ("rush_att",), "opp": "rush_att", "dist": "count", "odds": "player_rush_attempts",
                       "slots": ("RB1", "RB2", "QB")},
    "Anytime TD":     {"stats": ("rush_td", "rec_td"), "opp": "touch", "dist": "count", "odds": "player_anytime_td",
                       "slots": ("RB1", "RB2", "WR1", "WR2", "WR3", "TE1", "QB")},
}
DEFAULT_MARKET = "Receiving Yards"
MARKET_HELP = {"Anytime TD": "1+ rushing or receiving TD (line 0.5)", "Rush + Rec Yards": "rushing + receiving yards"}


def markets_for(sport: str) -> Dict[str, Dict]:
    """The markets this sport's data can price (completions are NFL-only)."""
    return {k: v for k, v in MARKETS.items() if sport in v.get("sports", (sport,))}
# How strongly each market moves with the game's implied scoring.
ENV_WEIGHT = {"Receptions": 0.4, "Receiving Yards": 0.7, "Rush Yards": 0.6, "Rush + Rec Yards": 0.7, "Pass Yards": 0.7,
              "Passing TDs": 1.0, "Rush Attempts": 0.3, "Anytime TD": 1.0,
              "Pass Attempts": 0.2, "Pass Completions": 0.3}
LEAGUE_TEAM_POINTS = {"NFL": 22.5, "NCAAF": 28.5}
EFF_SHRINK = {"tgt": 30.0, "rush_att": 40.0, "pass_att": 120.0, "touch": 50.0}   # opportunities of half-trust
PROMOTED_SHRINK_MULT = 2.0
PROMOTED_SHARE_MULT = 1.5
CARRY_TO_REPLACEMENT = 0.7
SCRIPT_PASS = 0.006            # per point of spread: underdogs throw more
SCRIPT_RUSH = 0.008            # favorites run more
FORM_N = 8                     # weeks of form


def _num(x) -> float:
    return PE.num(x)


def opportunity(stats: Dict, kind: str, has_targets: bool = True) -> float:
    s = stats or {}
    tgt = _num(s.get("tgt")) if has_targets else _num(s.get("rec"))
    if kind == "tgt":
        return tgt
    if kind == "touch":
        return tgt + _num(s.get("rush_att"))
    return _num(s.get(kind))


def market_value(stats: Dict, market: str) -> float:
    return sum(_num((stats or {}).get(k)) for k in MARKETS[market]["stats"])


def has_targets(pgames) -> bool:
    return any(_num((p.get("stats") or {}).get("tgt")) > 0 for p in pgames or [])


def roster_from_depth(depth: Dict[str, List[Dict]]) -> List[Dict]:
    """{slot: [occupant, next up...]} (the depth the page shows) -> the players props are offered on: each slot's
    occupant, plus the OUT players a promotion names (they get no projection, but their volume moves)."""
    out, seen = [], set()
    for slot, lst in (depth or {}).items():
        if not lst:
            continue
        p = lst[0]
        if p.get("pid") in seen and p.get("pid") is not None:
            continue
        seen.add(p.get("pid"))
        out.append({"pid": p.get("pid"), "name": p.get("name"), "slot": slot, "status": p.get("status"),
                    "role_change": p.get("role_change")})
        rc = p.get("role_change") or {}
        if rc.get("for"):
            out.append({"pid": None, "name": rc["for"], "slot": slot, "status": "Out", "role_change": None,
                        "replaced_by": p.get("name")})
    return out


def _games(pgames, pid=None, name=None, team=None, n: int = FORM_N) -> List[Dict]:
    def match(p):
        if pid is not None and p.get("pid") == pid:
            return True
        return pid is None and name and PE.norm_name(p.get("name")) == PE.norm_name(name) and \
            (team is None or p.get("team") == team)
    mine = [p for p in pgames or [] if match(p)]
    mine.sort(key=lambda p: (p.get("order") is None, p.get("order")), reverse=True)
    return mine[:n]


def league_rates(pgames, market: str, tgt_ok: bool) -> Dict[str, float]:
    """Production per opportunity by position across the sample (the efficiency prior)."""
    kind = MARKETS[market]["opp"]
    tot: Dict[str, List[float]] = {}
    for p in pgames or []:
        grp = "RB" if str(p.get("pos") or "").upper() in ("RB", "FB", "HB") else str(p.get("pos") or "").upper()
        o = opportunity(p.get("stats") or {}, kind, tgt_ok)
        if o <= 0:
            continue
        t = tot.setdefault(grp, [0.0, 0.0])
        t[0] += market_value(p.get("stats") or {}, market)
        t[1] += o
    return {g: v / o for g, (v, o) in tot.items() if o > 0}


def _group(slot: str) -> str:
    return "".join(c for c in slot if c.isalpha())


def defense_table(allowed: Dict, market: str) -> Dict:
    return PPR.defense_allowed(allowed, market, value_fn=lambda st: market_value(st, market))


def player_rows(roster: Sequence[Dict], team, defense, market: str, pgames, allowed: Dict,
                lines: Optional[Dict] = None, context: Optional[Dict] = None, sport: str = "NFL") -> List[Dict]:
    """One row per player at a slot this market is offered for. context: spread (THIS team's, negative =
    favored), total, offers, prices {key: {"over","under"}}, slope, model_weight. Rows key on pid (or name when
    the feed has no id)."""
    m = MARKETS[market]
    ctx = context or {}
    lines, prices = lines or {}, ctx.get("prices") or {}
    tgt_ok = has_targets(pgames)
    kind = m["opp"]
    rates = league_rates(pgames, market, tgt_ok)
    table = defense_table(allowed, market)

    # Each player's own volume and production.
    info = []
    for r in roster:
        g = _games(pgames, r.get("pid"), r.get("name"), team if r.get("pid") is None else None)
        vals = [market_value(x.get("stats") or {}, market) for x in g]
        opps = [opportunity(x.get("stats") or {}, kind, tgt_ok) for x in g]
        own_rate, own_opp = PE.rate_and_opportunity(vals, opps)
        info.append({"r": r, "games": g, "vals": vals, "opps": opps, "rate": own_rate, "opp": own_opp or 0.0,
                     "out": PPR.is_out(r.get("status")) or str(r.get("status") or "").lower() == "out"})

    # Next man up: move the OUT players' volume.
    adds = {id(i): 0.0 for i in info}
    live = [i for i in info if not i["out"]]
    for o in [i for i in info if i["out"] and i["opp"] > 0]:
        vac = o["opp"]
        repl = next((i for i in live if i["r"].get("name") == o["r"].get("replaced_by")), None)
        if kind == "pass_att" or (kind == "rush_att" and repl is not None):
            share = 0.95 if kind == "pass_att" else CARRY_TO_REPLACEMENT
            if repl is not None:
                adds[id(repl)] += vac * share
                vac *= 1 - share
        pool = [i for i in live if _group(i["r"]["slot"]) != "QB" or kind == "pass_att"]
        weights = {id(i): (i["opp"] + 1.0) * (PROMOTED_SHARE_MULT if i["r"].get("role_change") else 1.0) for i in pool}
        tot = sum(weights.values())
        for i in pool:
            adds[id(i)] += vac * weights[id(i)] / tot if tot else 0.0

    spread = PE.maybe(ctx.get("spread"))
    env = None
    imp = ctx.get("implied")
    if imp:
        env = PE.env_factor(imp, LEAGUE_TEAM_POINTS.get(sport, 22.5))
    rows = []
    for i in info:
        r = i["r"]
        slot = r["slot"]
        if slot not in m["slots"]:
            continue
        key = r.get("pid") if r.get("pid") is not None else r.get("name")
        flags: List[str] = []
        proj = opp = None
        f = PPR.blended_factor(PPR.raw_factor(table, defense, slot), None, "season")
        env_mult = 1.0
        if not i["out"]:
            grp = "RB" if _group(slot) == "RB" else _group(slot)
            prior = rates.get(grp, rates.get("WR", 0.0))
            k = EFF_SHRINK.get(kind, 40.0) * (PROMOTED_SHRINK_MULT if r.get("role_change") else 1.0)
            n_opp = sum(i["opps"])
            rate = prior if i["rate"] is None else (i["rate"] * n_opp + prior * k) / (n_opp + k)
            opp = i["opp"] + adds[id(i)]
            if adds[id(i)] > 0.05:
                flags.append(f"↑ +{adds[id(i)]:.1f} {_opp_word(kind, tgt_ok)} from teammates out")
            if r.get("role_change"):
                flags.append(PPR_role_text(r["role_change"]))
            if spread is not None:
                if kind in ("pass_att", "tgt"):
                    opp *= 1 + SCRIPT_PASS * spread
                elif kind == "rush_att":
                    opp *= 1 - SCRIPT_RUSH * spread
                elif kind == "touch":
                    opp *= 1 - 0.002 * spread
                if abs(spread) >= 7:
                    flags.append(("Favored" if spread < 0 else "Underdog") + f" {spread:+.1f}: "
                                 + ("more runs" if spread < 0 else "more passes"))
            env_mult = 1.0 + ENV_WEIGHT.get(market, 0.7) * ((env or 1.0) - 1)
            proj = rate * opp * f["factor"] * env_mult
            if not i["games"]:
                flags.append("no games in the sample")
        typed = lines.get(key)
        line = PE.maybe(typed)
        line_src = "typed" if line is not None else None
        if market == "Anytime TD" and line is None:
            line, line_src = 0.5, "fixed"
        book = None
        if ctx.get("offers") and m["odds"]:
            mine = PE.offers_for(ctx["offers"], r.get("name"), m["odds"])
            bk = ctx.get("book")
            book = PE.shop(mine, line, bk) if line_src == "typed" else (PE.shop(mine, None, bk) if market != "Anytime TD"
                                                                        else PE.shop(mine, 0.5, bk))
            if line_src is None and book:
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
        floor = m.get("floor") or ((0.45, 8.0) if m["dist"] == "normal" else (0.25, 1.0))   # yardage is lumpy: one 60-yard catch
        read = PE.read_line(proj, i["vals"], line, m["dist"], over_p, under_p, p_mkt, ctx.get("slope", 1.0),
                            ctx.get("model_weight", PE.MODEL_WEIGHT), *floor, news_checked=bool(ctx.get("news_checked")))
        hits = [v for v in i["vals"] if line is not None and PE.clears(v, line)]
        rows.append({
            "pid": key, "player": r.get("name"), "slot": slot, "status": r.get("status"), "out": i["out"],
            "opp": opp, "form": PE.wmean(i["vals"]) if i["vals"] else None, "games": len(i["vals"]),
            "filled": False, "factor": f["factor"], "env": env_mult, "projection": proj, "line": line,
            "line_src": line_src, "over_price": over_p, "under_price": under_p, "price_src": price_src,
            "book": book, "hit": (len(hits), len(i["vals"])) if line is not None and i["vals"] else None,
            "p_model": read["p_model"], "p_market": read["p_market"], "p_final": read["p_final"], "gap": read.get("gap"), "gap_pct": read.get("gap_pct"),
            "side": read["side"], "ev": read["ev"], "lean": read["lean"], "flags": flags, "dist": m["dist"],
            "values": list(i["vals"]), "sd_floor": floor,
        })
    return rows


def _opp_word(kind: str, tgt_ok: bool) -> str:
    return {"tgt": "targets" if tgt_ok else "catches", "rush_att": "carries", "pass_att": "attempts",
            "touch": "touches"}.get(kind, "")


def PPR_role_text(rc: Dict) -> str:
    import position_matchups as PM
    return PM.role_change_text(rc)


def display(rows: Sequence[Dict], market: str, tgt_ok: bool = True) -> List[Dict]:
    label = {"tgt": "Tgt" if tgt_ok else "Rec", "rush_att": "Carries", "pass_att": "Att", "touch": "Touches"}
    return PE.display(rows, label.get(MARKETS[market]["opp"], "Opp"))


def plays_for_log(rows: Sequence[Dict], market: str, game_label: str) -> List[Dict]:
    plays = PE.plays_for_log(rows, market, game_label)
    for p in plays:                       # a row keyed by NAME (no id in the feed) has no player id to settle by
        if p.get("PlayerId") == p.get("Player"):
            p["PlayerId"] = None
    return plays
