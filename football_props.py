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
    "Targets":          {"stats": ("tgt",), "opp": "tgt", "dist": "count", "odds": None, "slots": RECEIVERS,
                       "sports": ("NFL",)},           # no Odds API market: type the line (Pick6 / app boards)
    "Interceptions":    {"stats": ("pass_int",), "opp": "pass_att", "dist": "count", "odds": "player_pass_interceptions",
                       "slots": ("QB",)},
    # Oct 30: kicking + defensive props (football_special prices them; NFL only -- the college feed has no IDP/kicking)
    "FG Made":          {"stats": ("fg_made",), "opp": "none", "dist": "count", "odds": "player_field_goals",
                       "slots": ("K",), "group": "kicker", "sports": ("NFL",)},
    "Kicking Points":   {"stats": ("kick_pts",), "opp": "none", "dist": "normal", "odds": "player_kicking_points",
                       "slots": ("K",), "group": "kicker", "sports": ("NFL",), "floor": (0.40, 3.0)},
    "PATs Made":        {"stats": ("pat_made",), "opp": "none", "dist": "count", "odds": "player_pats",
                       "slots": ("K",), "group": "kicker", "sports": ("NFL",)},
    "Sacks":            {"stats": ("sacks",), "opp": "none", "dist": "count", "odds": "player_sacks",
                       "slots": ("DL", "LB", "DB"), "group": "defense", "sports": ("NFL",)},
    "Tackles + Assists": {"stats": ("tkl",), "opp": "none", "dist": "normal", "odds": "player_tackles_assists",
                       "slots": ("DL", "LB", "DB"), "group": "defense", "sports": ("NFL",), "floor": (0.32, 1.6)},
    "Solo Tackles":     {"stats": ("tkl_solo",), "opp": "none", "dist": "count", "odds": "player_solo_tackles",
                       "slots": ("DL", "LB", "DB"), "group": "defense", "sports": ("NFL",)},
    "Rush Attempts":       {"stats": ("rush_att",), "opp": "rush_att", "dist": "count", "odds": "player_rush_attempts",
                       "slots": ("RB1", "RB2", "QB")},
    "Anytime TD":     {"stats": ("rush_td", "rec_td"), "opp": "touch", "dist": "count", "odds": "player_anytime_td",
                       "slots": ("RB1", "RB2", "WR1", "WR2", "WR3", "TE1", "QB")},
}
DEFAULT_MARKET = "Receiving Yards"
MARKET_HELP = {"Anytime TD": "1+ rushing or receiving TD (line 0.5)", "Rush + Rec Yards": "rushing + receiving yards"}


def is_special(market: str) -> bool:
    return (MARKETS.get(market) or {}).get("group") in ("kicker", "defense")


def roster_for(props: Dict, team, market: str) -> List[Dict]:
    """The players a market is offered for on one team: the offensive depth, or the kicker / defenders."""
    if is_special(market):
        return (props.get("special_roster") or {}).get(team) or []
    return (props.get("roster") or {}).get(team) or []


def markets_for(sport: str) -> Dict[str, Dict]:
    """The markets this sport's data can price (completions are NFL-only)."""
    return {k: v for k, v in MARKETS.items() if sport in v.get("sports", (sport,))}
# How strongly each market moves with the game's implied scoring.
ENV_WEIGHT = {"Receptions": 0.4, "Receiving Yards": 0.7, "Rush Yards": 0.6, "Rush + Rec Yards": 0.7, "Pass Yards": 0.7,
              "Passing TDs": 1.0, "Rush Attempts": 0.3, "Anytime TD": 1.0,
              "Pass Attempts": 0.2, "Pass Completions": 0.3, "Targets": 0.3, "Interceptions": 0.2}
LEAGUE_TEAM_POINTS = {"NFL": 22.5, "NCAAF": 28.5}
EFF_SHRINK = {"tgt": 30.0, "rush_att": 40.0, "pass_att": 120.0, "touch": 50.0}   # opportunities of half-trust
PROMOTED_SHRINK_MULT = 2.0
PROMOTED_SHARE_MULT = 1.5
CARRY_TO_REPLACEMENT = 0.7
SCRIPT_PASS = 0.006            # per point of spread: underdogs throw more
SCRIPT_RUSH = 0.008            # favorites run more
FORM_N = 8                     # weeks of form
# Oct 30 (Packers-Panthers review):
PRIOR_FULL = 4                 # under 4 games this season, last season fills the gap (4 - n game-equivalents)
BACKUP_SHARE = 0.6             # a backup's volume from games his starter missed counts at 60% once the starter is back
RETURN_MISSED = 2              # a starter who missed 2+ of the team's recent games is "back"
QB_RUSH_SHRINK = 12.0          # a QB's yards per carry leans on his OWN history (mobile QBs skew the league rate)
PRESSURE_SHRINK = 6.0          # games before a defense's / line's sack rate is fully trusted
PRESSURE_QB = 0.10             # a +50% sack matchup trims QB yards / TDs / completions 5%
PRESSURE_RB_TGT = 0.20         # ... and adds 10% to running backs' targets (check-downs)
PRESSURE_FLAG = 0.25


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


def pressure(pgames, team, defense) -> Optional[float]:
    """How much more (or less) than normal this QB should be sacked: the defense's sacks per game and this line's
    sacks allowed per game, each against the league and shrunk for small samples, multiplied, minus 1. None when the
    feed has no sack data (college)."""
    qbs = [p for p in pgames or [] if str(p.get("pos") or "").upper() == "QB"]
    if not any(_num((p.get("stats") or {}).get("sacked")) > 0 for p in qbs):
        return None
    by_off: Dict = {}
    by_def: Dict = {}
    for p in qbs:
        k = (p.get("game"), p.get("team"))
        v = _num((p.get("stats") or {}).get("sacked"))
        by_off.setdefault(p.get("team"), {}).setdefault(k, 0.0)
        by_off[p.get("team")][k] += v
        by_def.setdefault(p.get("opp"), {}).setdefault(k, 0.0)
        by_def[p.get("opp")][k] += v
    per = [v for games in by_off.values() for v in games.values()]
    league = sum(per) / len(per) if per else 0.0
    if league <= 0:
        return None

    def factor(games):
        if not games:
            return 1.0
        n = len(games)
        raw = (sum(games.values()) / n) / league
        w = n / (n + PRESSURE_SHRINK)
        return w * raw + (1 - w)
    f = factor(by_def.get(defense)) * factor(by_off.get(team))
    return max(-0.4, min(0.6, f - 1.0))


def _slot_rank(slot: str) -> int:
    digits = "".join(c for c in str(slot) if c.isdigit())
    return int(digits) if digits else 1


def player_rows(roster: Sequence[Dict], team, defense, market: str, pgames, allowed: Dict,
                lines: Optional[Dict] = None, context: Optional[Dict] = None, sport: str = "NFL",
                prior_pgames: Optional[Sequence[Dict]] = None, special: Optional[Dict] = None) -> List[Dict]:
    """One row per player at a slot this market is offered for. context: spread (THIS team's, negative =
    favored), total, offers, prices {key: {"over","under"}}, slope, model_weight. Rows key on pid (or name when
    the feed has no id). `prior_pgames`: last season's lines (position_data.prior_season_pgames). Kicking and
    defensive markets are priced by football_special (`special` = the bundle's kicker / defender lines)."""
    m = MARKETS[market]
    if m.get("group") in ("kicker", "defense"):
        import football_special as FS
        return FS.player_rows(roster, team, defense, market, special or {}, lines=lines, context=context, sport=sport)
    ctx = context or {}
    lines, prices = lines or {}, ctx.get("prices") or {}
    tgt_ok = has_targets(pgames)
    kind = m["opp"]
    rates = league_rates(pgames, market, tgt_ok)
    table = defense_table(allowed, market)
    prior_pgames = list(prior_pgames or [])

    # The team's recent games (who played in each) -- for a starter who's back and the backups who filled in.
    team_games = {}
    for p in pgames or []:
        if p.get("team") == team:
            team_games[p.get("game")] = p.get("order")
    window = sorted(team_games, key=lambda g_: (team_games[g_] is None, team_games[g_]), reverse=True)[:FORM_N]
    played = {(p.get("game"), p.get("pid")) for p in pgames or [] if p.get("team") == team}

    # Each player's own volume and production.
    info = []
    for r in roster:
        g = _games(pgames, r.get("pid"), r.get("name"), team if r.get("pid") is None else None)
        vals = [market_value(x.get("stats") or {}, market) for x in g]
        opps = [opportunity(x.get("stats") or {}, kind, tgt_ok) for x in g]
        own_rate, _ = PE.rate_and_opportunity(vals, opps)
        # Volume counts every game he played, quiet ones included (a WR3's 0-target games are his role, not a DNP).
        own_opp = PE.wmean(opps) if opps else None
        n_opp = sum(opps)
        read_vals = list(vals)
        flags0: List[str] = []
        # Thin sample this season (back from injury, new starter): last season fills in, as game-equivalents.
        if len(g) < PRIOR_FULL and prior_pgames:
            pg = _games(prior_pgames, r.get("pid"), r.get("name"), None)
            if len(pg) >= 2:
                k = PRIOR_FULL - len(g)
                p_vals = [market_value(x.get("stats") or {}, market) for x in pg]
                p_opps = [opportunity(x.get("stats") or {}, kind, tgt_ok) for x in pg]
                p_rate, _ = PE.rate_and_opportunity(p_vals, p_opps)
                p_opp = PE.wmean(p_opps)
                own_opp = p_opp if own_opp is None else (len(g) * own_opp + k * p_opp) / (len(g) + k)
                scale = k / len(pg)
                p_n = sum(p_opps) * scale
                if p_rate is not None:
                    own_rate = p_rate if own_rate is None else (own_rate * n_opp + p_rate * p_n) / (n_opp + p_n)
                n_opp += p_n
                read_vals = vals + p_vals[:k]
                flags0.append(f"＋ last season blended in ({len(g)} game{'s' if len(g) != 1 else ''} this season)")
        missed = [gid for gid in window if (gid, r.get("pid")) not in played] if r.get("pid") is not None else []
        info.append({"r": r, "games": g, "vals": vals, "read_vals": read_vals, "opps": opps, "rate": own_rate,
                     "opp": own_opp or 0.0, "n_opp": n_opp, "flags0": flags0, "missed": missed,
                     "out": PPR.is_out(r.get("status")) or str(r.get("status") or "").lower() == "out"})

    # A starter who is BACK: his backups' volume from the games he missed is discounted -- the role they held
    # then belongs to him again (Oct 29: Lloyd projected for Jacobs' carries).
    for i in info:
        slot = i["r"].get("slot") or ""
        grp = "RB" if _group(slot) == "RB" else _group(slot)
        if grp == "QB" or i["out"]:
            continue
        backs = [s for s in info if s is not i and not s["out"] and len(s["missed"]) >= RETURN_MISSED
                 and ("RB" if _group(s["r"].get("slot") or "") == "RB" else _group(s["r"].get("slot") or "")) == grp
                 and _slot_rank(s["r"].get("slot")) < _slot_rank(slot)]
        if not backs:
            continue
        gone = set().union(*[set(s["missed"]) for s in backs])
        with_opps = [o for x, o in zip(i["games"], i["opps"]) if x.get("game") not in gone]
        if len(with_opps) == len(i["opps"]):
            continue
        base = i["opp"] * BACKUP_SHARE
        i["opp"] = (sum(with_opps) + base) / (len(with_opps) + 1) if with_opps else base
        i["flags0"].append("↓ " + ", ".join(s["r"].get("name") or "starter" for s in backs)
                           + " back: volume from games with him active")
    for s in info:
        if len(s["missed"]) >= RETURN_MISSED and not s["out"] and s["games"]:
            s["flags0"].append(f"↺ back after missing {len(s['missed'])} of the last {len(window)} games")

    press = pressure(pgames, team, defense) if sport == "NFL" else None

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
        flags.extend(i["flags0"])
        if not i["out"]:
            grp = "RB" if _group(slot) == "RB" else _group(slot)
            prior = rates.get(grp, rates.get("WR", 0.0))
            k = (QB_RUSH_SHRINK if (grp == "QB" and kind == "rush_att") else EFF_SHRINK.get(kind, 40.0)) * \
                (PROMOTED_SHRINK_MULT if r.get("role_change") else 1.0)
            n_opp = i["n_opp"]
            rate = prior if i["rate"] is None else (i["rate"] * n_opp + prior * k) / (n_opp + k)
            opp = i["opp"] + adds[id(i)]
            if press is not None:
                if grp == "QB" and market in ("Pass Yards", "Passing TDs", "Pass Completions"):
                    rate *= 1 - PRESSURE_QB * press
                elif grp == "RB" and kind in ("tgt", "touch"):
                    opp *= 1 + PRESSURE_RB_TGT * press * (1.0 if kind == "tgt" else 0.4)
                if abs(press) >= PRESSURE_FLAG and (grp == "QB" or (grp == "RB" and kind in ("tgt", "touch"))):
                    flags.append(("🔥 Pass rush edge" if press > 0 else "🛡️ Clean pocket") +
                                 f": sacks {press:+.0%} vs normal")
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
            proj = rate * opp * f["factor"] * env_mult * _tuning(sport, market, slot)
            if not i["games"]:
                flags.append("no games in the sample")
        rows.append(price_row(r, key, slot, proj, opp, market, i["vals"], i["read_vals"], ctx, lines, prices,
                              f["factor"], env_mult, flags, out=i["out"],
                              returning=len(i["missed"]) >= RETURN_MISSED and bool(i["games"]) and not i["out"]
                              and i["games"][0].get("game") != (window[0] if window else None)))
    return rows


def price_row(r: Dict, key, slot: str, proj: Optional[float], opp: Optional[float], market: str, vals: List[float],
              read_vals: List[float], ctx: Dict, lines: Dict, prices: Dict, factor: float, env_mult: float,
              flags: List[str], out: bool = False, returning: bool = False, group: str = "offense") -> Dict:
    """One priced props row (the shape every page reads): the line typed or loaded from the books, prices, the read
    (model + market blend, side, edge, lean), hit rate. Shared by the offensive, kicking and defensive markets."""
    m = MARKETS[market]
    typed = lines.get(key)
    line = PE.maybe(typed)
    line_src = "typed" if line is not None else None
    if market == "Anytime TD" and line is None:
        line, line_src = 0.5, "fixed"
    book = None
    if ctx.get("offers") and m.get("odds"):
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
    read = PE.read_line(proj, read_vals, line, m["dist"], over_p, under_p, p_mkt, ctx.get("slope", 1.0),
                        ctx.get("model_weight", PE.MODEL_WEIGHT), *floor, news_checked=bool(ctx.get("news_checked")))
    hits = [v for v in vals if line is not None and PE.clears(v, line)]
    return {
        "pid": key, "player": r.get("name"), "slot": slot, "status": r.get("status"), "out": out,
        "opp": opp, "form": PE.wmean(vals) if vals else None, "games": len(vals),
        "filled": False, "factor": factor, "env": env_mult, "projection": proj, "line": line,
        "line_src": line_src, "over_price": over_p, "under_price": under_p, "price_src": price_src,
        "book": book, "hit": (len(hits), len(vals)) if line is not None and vals else None,
        "p_model": read["p_model"], "p_market": read["p_market"], "p_final": read["p_final"], "gap": read.get("gap"),
        "gap_pct": read.get("gap_pct"), "side": read["side"], "ev": read["ev"], "lean": read["lean"], "flags": flags,
        "dist": m["dist"], "values": list(read_vals), "sd_floor": floor, "returning": returning, "market": market,
        "group": group,
    }


def _tuning(sport: str, market: str, slot: str = "") -> float:
    """Approved Postgame Review adjustments (model_tuning); 1.0 when none or the store can't be read."""
    try:
        import model_tuning as MT
        return MT.factor(sport, market, slot)
    except Exception:                                           # noqa: BLE001
        return 1.0


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
