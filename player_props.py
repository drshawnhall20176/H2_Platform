"""
player_props.py -- Position Matchups' Player props view for basketball: every rotation player, the prop market you
pick (PRA by default), a matchup-adjusted projection, and an over/under read against a line you type in.

PURE LOGIC, NO NETWORK (position_data.py loads; the page renders). Built to fix what the Oct 27 NBA slate exposed:

  1. Every rotation player gets his own row. The Depth table shows one starter per Guard / Forward / Center group and
     tucks everyone else into "Next up" -- Paul George, Mitchell Robinson and Michael Porter Jr. were all there, off
     the right edge, with no read of their own.
  2. The matchup is applied to the PLAYER, not graded on the group. A defense's number for a position group becomes a
     factor (allowed / league average for that market), and a player's projection is his own recent average times it.
  3. Small samples are shrunk. Three games of a defense barely moves the factor; it's blended with the end of last
     season (when loaded) and pulled toward neutral until the season sample is big enough to trust.
  4. A line you type gets a read: projection vs the line, how often he's cleared it lately, a rough probability, and
     Over / Under / no lean.
  5. Pace is flagged. Two fast, high-scoring teams inflate every counting-stat prop; that's called out per game.

UPGRADED (Oct 28): projections are now opportunity-first and market-aware -- see props_engine.py: recency-weighted
per-minute rate x projected minutes, next-man-up minutes/usage when a teammate is freshly ruled out, back-to-back /
rest and blowout adjustments, the implied team total from the spread + total, count distributions for low-count
markets, and a blend with the books' no-vig price when lines are loaded or typed.

HONEST LIMITS: overtime isn't modelled, injury news is only as fresh as ESPN's report, and every adjustment size is
a starting point the Scorecard tab checks against real results.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import form_policy as FPol
import props_engine as PE

# Display name -> the box-score stats it sums. PRA first: it's the default market.
MARKETS: Dict[str, Tuple[str, ...]] = {
    "PRA": ("pts", "reb", "ast"),
    "Points": ("pts",),
    "Rebounds": ("reb",),
    "Assists": ("ast",),
    "Blocks": ("blk",),
    "Steals": ("stl",),
    "PA": ("pts", "ast"),
    "PR": ("pts", "reb"),
    "PB": ("pts", "blk"),
    "RA": ("reb", "ast"),
    "Threes Made": ("fg3m",),
}
DEFAULT_MARKET = "PRA"
MARKET_HELP = {"PRA": "Points + Rebounds + Assists", "PA": "Points + Assists", "PR": "Points + Rebounds",
               "PB": "Points + Blocks", "RA": "Rebounds + Assists", "Threes Made": "3-pointers made"}

FORM_N = 5                 # a player's "lately" window, games
HIT_N = 10                 # the window his hit rate against a line is counted over
FILL_BELOW = 5             # = form_policy.MIN_CURRENT: fewer games this season -> topped up from last season (half weight)
SHRINK_K = 10.0            # games of a defense that count as half-trusted (n / (n + K))
FACTOR_RANGE = (0.80, 1.20)
MIN_MINUTES = 10.0         # rotation cut-off (average minutes)
MAX_PLAYERS = 10
LEAN_EDGE = 0.05           # projection must clear the line by 5% (and the probability agree) to call a lean
PACE_FLAG_PCT = 4.0
MIN_DEFENSES = 8           # a league average from fewer defenses than this isn't one (college: two teams only)

_OUT = {"out", "injured reserve", "ir", "suspended", "inactive"}

# How each market is shaped: low counts get a negative binomial, totals a normal curve.
DIST = {"Rebounds": "count", "Assists": "count", "Blocks": "count", "Steals": "count", "Threes Made": "count"}
# How strongly each stat moves with a game's scoring environment (points fully, rebounds a little).
ENV_WEIGHTS = {"pts": 1.0, "ast": 0.7, "reb": 0.4, "stl": 0.3, "blk": 0.3, "fg3m": 0.9, "_default": 0.8}
# Combos that contain points: a flagged Points line (the cleanest read on minutes / role) flags these too.
POINTS_COMBOS = ("PA", "PR", "PRA", "PB")
# The Odds API market key behind each market (Points + Blocks isn't posted there).
ODDS_MARKETS = {"Points": "player_points", "Rebounds": "player_rebounds", "Assists": "player_assists",
                "Blocks": "player_blocks", "Steals": "player_steals", "PRA": "player_points_rebounds_assists",
                "PR": "player_points_rebounds", "PA": "player_points_assists", "RA": "player_rebounds_assists",
                "Threes Made": "player_threes"}


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) or math.isinf(v) else v


def market_value(stats: Dict, market: str) -> float:
    return sum(_num((stats or {}).get(k)) for k in MARKETS[market])


# --------------------------------------------------------------------------- rotation (fix 1)
def rotation(usage: Dict[str, List[Dict]], injuries: Optional[Dict[str, str]] = None,
             min_minutes: float = MIN_MINUTES, limit: int = MAX_PLAYERS) -> List[Dict]:
    """position_matchups.usage_depth output ({G/F/C: [{"pid","name","avg_min",...}]}) -> one flat list of every
    rotation player, most minutes first: [{"pid","name","slot","avg_min","status"}]."""
    injuries = injuries or {}
    seen, out = set(), []
    for slot, players in (usage or {}).items():
        for u in players:
            if u.get("pid") in seen or _num(u.get("avg_min")) < min_minutes:
                continue
            seen.add(u.get("pid"))
            out.append({"pid": u.get("pid"), "name": u.get("name"), "slot": slot, "avg_min": _num(u.get("avg_min")),
                        "status": injuries.get(u.get("name")), "slot2": u.get("slot2"),
                        "start_rate": u.get("start_rate"), "pos": u.get("pos"),
                        "chart_starter": u.get("chart_starter")})
    out.sort(key=lambda r: -r["avg_min"])
    return out[:limit]


def is_out(status) -> bool:
    return str(status or "").strip().lower() in _OUT


# --------------------------------------------------------------------------- defense factor (fixes 2 + 3)
def defense_allowed(allowed: Dict, market: str, min_games: int = 3, value_fn=None) -> Dict[str, Dict[str, Dict]]:
    """position_matchups.allowed_by_slot output -> {defense: {slot: {"avg", "games"}}} of the MARKET allowed per game
    to each position group, plus a "_league" entry {slot: average across defenses with >= min_games}. `value_fn`
    (stats -> number) replaces the basketball market sum (football / hockey markets)."""
    value_fn = value_fn or (lambda st: market_value(st, market))
    out: Dict[str, Dict[str, Dict]] = {}
    for defense, games in (allowed or {}).items():
        per: Dict[str, Dict] = {}
        slots = {s for g in games for s in (g.get("slots") or {})}
        for slot in slots:
            vals = [value_fn((g.get("slots") or {}).get(slot) or {}) for g in games]
            per[slot] = {"avg": sum(vals) / len(vals), "games": len(vals)}
        out[defense] = per
    league: Dict[str, float] = {}
    for slot in {s for per in out.values() for s in per}:
        vals = [per[slot]["avg"] for per in out.values() if slot in per and per[slot]["games"] >= min_games]
        if vals:
            league[slot] = sum(vals) / len(vals)
    out["_league"] = {s: {"avg": v, "games": None, "defenses": len([1 for per in out.values()
                                                                   if s in per and per[s]["games"] >= min_games])}
                      for s, v in league.items()}
    return out


def raw_factor(table: Dict[str, Dict[str, Dict]], defense, slot: str) -> Optional[Tuple[float, int]]:
    """(allowed / league average, games) for one defense at one position group, or None if unknown."""
    d = (table.get(defense) or {}).get(slot)
    lg = (table.get("_league") or {}).get(slot)
    if not d or not lg or not lg["avg"] or lg.get("defenses", 0) < MIN_DEFENSES:
        return None
    return d["avg"] / lg["avg"], d["games"]


def shrink(factor: float, games: int, toward: float = 1.0, k: float = SHRINK_K) -> float:
    w = games / (games + k) if games > 0 else 0.0
    return toward + (factor - toward) * w


def blended_factor(current: Optional[Tuple[float, int]], prior: Optional[Tuple[float, int]],
                   mode: str = "blend") -> Dict:
    """The factor a player's projection is multiplied by, and how it was built.

    mode "blend" (default): last season's factor (itself shrunk by its own sample) is the starting point, and this
    season's pulls away from it as games pile up -- n / (n + 10). "season": this season only, shrunk toward neutral.
    "prior": last season only. Always clipped to FACTOR_RANGE. Returns {"factor", "season_weight", "basis"}."""
    lo, hi = FACTOR_RANGE
    if mode == "prior":
        f = shrink(*prior) if prior else 1.0
        return {"factor": min(hi, max(lo, f)), "season_weight": 0.0, "basis": "last season" if prior else "neutral"}
    target = shrink(*prior) if (prior and mode == "blend") else 1.0
    if current is None:
        return {"factor": min(hi, max(lo, target)), "season_weight": 0.0,
                "basis": "last season" if target != 1.0 else "neutral"}
    f, n = current
    w = n / (n + SHRINK_K)
    return {"factor": min(hi, max(lo, target + (f - target) * w)), "season_weight": w,
            "basis": f"{n} games this season" + (" + last season" if mode == "blend" and prior else "")}


# --------------------------------------------------------------------------- player form + the line read (fix 4)
def _games(pgames, pid, n: int) -> List[Dict]:
    """A player's games with minutes, newest first."""
    mine = [p for p in pgames or [] if p.get("pid") == pid and _num((p.get("stats") or {}).get("min")) > 0]
    mine.sort(key=lambda p: (p.get("order") is None, p.get("order")), reverse=True)
    return mine[:n]


def player_values(pgames: Iterable[Dict], pid, market: str, n: int) -> List[float]:
    return [market_value(p.get("stats") or {}, market) for p in _games(pgames, pid, n)]


def form_games(cur_pgames, prior_pgames, pid) -> Dict:
    """His form games (newest first) under the platform-wide rule (form_policy): this season's, topped up to five
    from the end of last season (those count half). {"games", "weights", "season_games", "filled"}."""
    cur = [dict(g, src="current") for g in _games(cur_pgames, pid, HIT_N)]
    prior = [dict(g, src="prior") for g in _games(prior_pgames, pid, HIT_N)]
    games = FPol.select(cur + prior, window=HIT_N)
    return {"games": games, "weights": FPol.weights(games), "season_games": len(cur),
            "filled": any(g.get("src") == "prior" for g in games)}


def form(cur_pgames, prior_pgames, pid, market: str) -> Dict:
    """His recent values for the market, newest first. {"values", "season_games", "filled"}."""
    f = form_games(cur_pgames, prior_pgames, pid)
    return {"values": [market_value(g.get("stats") or {}, market) for g in f["games"]],
            "season_games": f["season_games"], "filled": f["filled"]}


def prob_over(projection: float, values: Sequence[float], line: float) -> Optional[float]:
    """P(stat > line), normal approximation (kept for callers of the original API; the table uses
    props_engine.prob_over with each market's own distribution)."""
    return PE.prob_over(projection, values, line, "normal")


threshold = PE.threshold
clears = PE.clears
american = PE.american


def lean(projection: Optional[float], line: Optional[float], p_over: Optional[float]) -> str:
    if projection is None or line is None or p_over is None or line <= 0:
        return "—"
    edge = (projection - threshold(line)) / threshold(line) if threshold(line) > 0 else 0.0
    if edge >= LEAN_EDGE and p_over >= 0.55:
        return "Over"
    if edge <= -LEAN_EDGE and p_over <= 0.45:
        return "Under"
    return "No lean"


def team_recent_games(pgames, team, n: int = PE.FRESH_OUT_GAMES) -> List:
    """The team's most recent game ids, newest first."""
    order: Dict = {}
    for p in pgames or []:
        if p.get("team") == team and p.get("game") is not None:
            o = p.get("order")
            order[p["game"]] = max(o, order.get(p["game"], o)) if o is not None else order.get(p["game"])
    return sorted(order, key=lambda g: (order[g] is None, order[g]), reverse=True)[:n]


def _component_shares(games: Sequence[Dict], market: str) -> Dict[str, float]:
    return {k: sum(_num((g.get("stats") or {}).get(k)) for g in games) for k in MARKETS[market]}


def _num_or_none(x):
    return PE.maybe(x)


def player_rows(rotation_list: Sequence[Dict], defense, market: str, cur_table: Dict, prior_table: Optional[Dict],
                cur_pgames, prior_pgames, lines: Optional[Dict] = None, mode: str = "blend",
                current_is_prior: bool = False, context: Optional[Dict] = None) -> List[Dict]:
    """One row per rotation player for `market` against `defense`.

    projection = per-minute rate x projected minutes x matchup factor x game environment, where
      * rate and minutes are recency weighted over his last 10 games (props_engine.rate_and_opportunity);
      * a FRESH absence's minutes and usage go to teammates (props_engine.redistribute) -- the basketball
        "next man up";
      * rest (back-to-backs, a tired opponent) and blowout risk (big spreads) adjust minutes and rate;
      * the game environment is the implied team total from the spread + total vs the team's normal scoring.

    `lines` is {pid: line} typed by the user. `context` (all optional):
      team, rest_days, opp_rest_days, spread (THIS team's, negative = favored), env (factor from
      props_engine.env_factor), offers (the books' parsed player-prop offers), prices {pid: {"over","under"}}
      typed by the user, slope (calibration), model_weight.
    `current_is_prior` means the season table is really last season's (opening weeks)."""
    lines = lines or {}
    ctx = context or {}
    prices = ctx.get("prices") or {}
    odds_key = ODDS_MARKETS.get(market)
    dist = DIST.get(market, "normal")
    team_games = team_recent_games(cur_pgames, ctx.get("team")) if ctx.get("team") is not None else []

    base = []
    for r in rotation_list:
        f = form_games(cur_pgames, prior_pgames, r["pid"])
        games = f["games"]
        values = [market_value(g.get("stats") or {}, market) for g in games]
        mins = [_num((g.get("stats") or {}).get("min")) for g in games]
        rate, proj_min = PE.rate_and_opportunity(values, mins, f["weights"])
        out = is_out(r.get("status"))
        fresh = out and PE.fresh_absence([g.get("game") for g in _games(cur_pgames, r["pid"], HIT_N)], team_games)
        base.append({"r": r, "f": f, "values": values, "games": games, "rate": rate, "proj_min": proj_min,
                     "w": f["weights"],
                     "out": out, "fresh": fresh})
    shifts = PE.redistribute([{"pid": b["r"]["pid"], "name": b["r"]["name"], "slot": b["r"]["slot"],
                               "opp": b["proj_min"] or 0.0, "rate": b["rate"] or 0.0, "out": b["out"],
                               "fresh": b["fresh"]} for b in base], cap=42.0, primary_n=PE.PRIMARY_N)

    rows = []
    for b in base:
        r = b["r"]
        slot = r["slot"]
        cur = None if current_is_prior else raw_factor(cur_table, defense, slot)
        pri = raw_factor(prior_table, defense, slot) if prior_table else (raw_factor(cur_table, defense, slot)
                                                                          if current_is_prior else None)
        fac = blended_factor(cur, pri, mode)
        if r.get("slot2"):                      # a double big: half his group's matchup, half the forwards'
            import position_matchups as PM
            s2 = r["slot2"]
            cur2 = None if current_is_prior else raw_factor(cur_table, defense, s2)
            pri2 = raw_factor(prior_table, defense, s2) if prior_table else (raw_factor(cur_table, defense, s2)
                                                                             if current_is_prior else None)
            fac = dict(fac, factor=PM.blend_factor(fac["factor"], blended_factor(cur2, pri2, mode)["factor"]),
                       basis=fac["basis"] + f" · {slot}/{s2} blend")
        values = b["values"]
        recent_avg = PE.wmean(values, b["w"]) if values else None
        flags: List[str] = []
        proj, opp = None, None
        env_mult = 1.0
        if not b["out"] and b["rate"] is not None:
            sh = shifts.get(r["pid"], {"opp_add": 0.0, "rate_mult": 1.0, "from": []})
            opp = (b["proj_min"] or 0.0) + sh["opp_add"]
            rate = b["rate"] * sh["rate_mult"]
            if sh["from"]:
                flags.append("↑ usage bump (" + ", ".join(n for n in sh["from"] if n) + " out)")
            rest = PE.rest_effect(ctx.get("rest_days"), ctx.get("opp_rest_days"), r["avg_min"], "basketball")
            blow = PE.blowout_effect(ctx.get("spread"), r["avg_min"], "basketball")
            opp *= rest["opp_mult"] * blow["opp_mult"]
            rate *= rest["rate_mult"]
            flags += rest["flags"] + blow["flags"]
            env_mult = PE.env_multiplier(ctx.get("env"), _component_shares(b["games"], market), ENV_WEIGHTS)
            proj = rate * opp * fac["factor"] * env_mult * _tuning(ctx.get("sport") or "NBA", market, slot)
        if b["f"]["filled"] and not b["f"]["season_games"]:
            # Oct 31: no game this season yet -- every number is last season's, on a role that may have changed
            # (college rosters turn over; a bench player can be this year's starter).
            flags.insert(0, "⚠️ No games this season yet — all form is last season's; his role and minutes may "
                            "have changed")
        elif b["f"]["filled"]:
            flags.append("form incl. last season")
        if b["out"] and not b["fresh"]:
            flags.append("already out — teammates' numbers include it")
        # Missed his team's most recent game but isn't listed out tonight: likely returning from something (an
        # injury, rest, illness). Minutes may be limited -- exactly what a low book line can be pricing.
        my_games = {g.get("game") for g in _games(cur_pgames, r["pid"], HIT_N)}
        returning = (not b["out"] and bool(team_games) and bool(my_games) and team_games[0] not in my_games)
        if returning:
            flags.insert(0, "⚠️ Missed the team's last game — returning? minutes may be limited")

        typed_line = lines.get(r["pid"])
        line = _num_or_none(typed_line)
        line_src = "typed" if line is not None else None
        book = None
        if odds_key and ctx.get("offers"):
            mine = PE.offers_for(ctx["offers"], r["name"], odds_key)
            book = PE.shop(mine, line, ctx.get("book")) if line is not None else PE.shop(mine, None, ctx.get("book"))
            if line is None and book:
                line, line_src = book["line"], "book"
        typed = prices.get(r["pid"]) or {}
        t_over, t_under = _num_or_none(typed.get("over")), _num_or_none(typed.get("under"))
        if t_over is not None or t_under is not None:
            over_p, under_p, price_src, p_mkt = t_over, t_under, "manual", None
        elif book:
            over_p = book["best_over"][1] if book.get("best_over") else None
            under_p = book["best_under"][1] if book.get("best_under") else None
            price_src, p_mkt = "book", book.get("p_market")
        else:
            over_p = under_p = price_src = p_mkt = None
        read = PE.read_line(proj, values, line, dist, over_p, under_p, p_mkt, ctx.get("slope", 1.0),
                            ctx.get("model_weight", PE.MODEL_WEIGHT), news_checked=bool(ctx.get("news_checked")))
        if returning and read["lean"] == "Over" and not ctx.get("news_checked"):
            read["lean"] = "Check news"
        absorbs = bool(not b["out"] and shifts.get(r["pid"], {}).get("primary"))
        if absorbs:
            flags.insert(0, "⚠️ Top option with a teammate freshly out — Unders on this role lost 0-8 Oct 29-30")
            if read["lean"] == "Under" and not ctx.get("news_checked"):
                read["lean"] = "Check news"
        hits = [v for v in values if line is not None and clears(v, line)]
        rows.append({
            "pid": r["pid"], "player": r["name"], "slot": slot, "status": r.get("status"), "out": b["out"],
            "returning": returning, "absorbs": absorbs,
            "avg_min": r["avg_min"], "opp": opp, "recent_avg": recent_avg, "form": recent_avg,
            "games": len(values), "season_games": b["f"]["season_games"], "filled": b["f"]["filled"],
            "factor": fac["factor"], "season_weight": fac["season_weight"], "basis": fac["basis"],
            "env": env_mult, "projection": proj, "line": line, "line_src": line_src,
            "over_price": over_p, "under_price": under_p, "price_src": price_src, "book": book,
            "hit": (len(hits), len(values)) if line is not None and values else None,
            "p_model": read["p_model"], "p_market": read["p_market"], "p_final": read["p_final"], "gap": read.get("gap"), "gap_pct": read.get("gap_pct"),
            "p_over": read["p_final"], "side": read["side"], "ev": read["ev"], "lean": read["lean"],
            "flags": flags, "dist": dist, "values": list(values),
        })
    return carry_points_flags(rows, rotation_list, defense, market, cur_pgames, prior_pgames, mode,
                              current_is_prior, ctx)


def carry_points_flags(rows: List[Dict], rotation_list, defense, market: str, cur_pgames, prior_pgames,
                       mode: str, current_is_prior: bool, ctx: Dict) -> List[Dict]:
    """When the books' POINTS line for a player is far from his points projection -- the clearest sign of a minutes
    or role change the box scores don't show -- his points combos (PA, PR, PRA, PB) inherit the flag: a news check
    before any lean. Needs the Points offers loaded alongside (the page fetches them with any points combo)."""
    if market not in POINTS_COMBOS or ctx.get("_no_carry"):
        return rows
    offers = ctx.get("offers") or []
    if not any(o.get("market") == ODDS_MARKETS["Points"] for o in offers):
        return rows
    import position_matchups as PM
    sport = ctx.get("sport", "NBA")
    ct = defense_allowed(PM.allowed_by_slot(cur_pgames or [], sport), "Points")
    pt = defense_allowed(PM.allowed_by_slot(prior_pgames, sport), "Points") if prior_pgames else None
    pts = player_rows(rotation_list, defense, "Points", ct, pt, cur_pgames, prior_pgames, lines=None, mode=mode,
                      current_is_prior=current_is_prior, context=dict(ctx, prices={}, _no_carry=True))
    flagged = {x["pid"]: x for x in pts if x.get("gap") == "big"}
    for row in rows:
        f = flagged.get(row["pid"])
        if not f or row.get("gap") == "big":
            continue
        row["gap"], row["gap_pct"] = "big", f["gap_pct"]
        row["gap_from"] = (f"Points line {f['line']:g} vs points projection {f['projection']:.1f} "
                           f"({f['gap_pct']:+.0%})")
        if row.get("lean") in ("Over", "Under") and not ctx.get("news_checked"):
            row["lean"] = "Check news"
    return rows


# --------------------------------------------------------------------------- one recipe, every page
# Position Matchups' Player props and the slate-wide pick pages (Best Bets, Edge Board, Graded Picks, Parlays,
# Slip Lab...) build a team's reads through THESE helpers, so the same player never gets two projections.
def market_tables(cur_pgames, prior_pgames, market: str, sport: str = "NBA") -> Dict:
    """{"cur", "prior"} defense-allowed tables for `market` (what player_rows' matchup factor reads)."""
    import position_matchups as PM
    return {"cur": defense_allowed(PM.allowed_by_slot(cur_pgames or [], sport), market),
            "prior": defense_allowed(PM.allowed_by_slot(prior_pgames, sport), market) if prior_pgames else None}


def team_rotation(cur_pgames, fallback_pgames, team, injuries: Optional[Dict[str, str]] = None,
                  sport: str = "NBA", last_n: int = 7, chart: Optional[Dict] = None) -> List[Dict]:
    """Every rotation player of `team`, from THIS season's games when the team has any (a traded player belongs
    to his new team), otherwise from `fallback_pgames`. `chart` (tonight's depth chart) puts each listed player in
    the group he is playing tonight (position_matchups.apply_depth_chart)."""
    import position_matchups as PM
    own = cur_pgames if any(p.get("team") == team for p in cur_pgames or []) else (fallback_pgames or [])
    return rotation(PM.apply_depth_chart(PM.usage_depth(own, team, sport, last_n=last_n), chart), injuries)


def game_context(team, is_home: bool, spread_home: Optional[float], total: Optional[float],
                 rest_days: Optional[int], opp_rest_days: Optional[int], baseline_pgames, offers=None,
                 book: Optional[str] = None, news_checked: bool = False, slope: float = 1.0,
                 model_weight: float = PE.MODEL_WEIGHT, sport: str = "NBA") -> Dict:
    """player_rows' `context` for one team in one game: rest both ways, this team's spread, the game environment
    (implied team total vs the team's normal scoring), the books' offers and whose prices to use."""
    implied = PE.implied_team_totals(total, spread_home)
    team_imp = (implied[0] if is_home else implied[1]) if implied else None
    spread_team = None if spread_home is None else (spread_home if is_home else -spread_home)
    return {"team": team, "sport": sport, "rest_days": rest_days, "opp_rest_days": opp_rest_days,
            "spread": spread_team, "env": PE.env_factor(team_imp, team_baseline(baseline_pgames, team)),
            "offers": offers, "book": book, "news_checked": bool(news_checked), "slope": slope,
            "model_weight": model_weight}


def display(rows: Sequence[Dict]) -> List[Dict]:
    """Rows -> table strings (props_engine.display); 'Line' and the odds columns stay numeric (editable)."""
    return PE.display(rows, "Min")


def plays_for_log(rows: Sequence[Dict], market: str, game_label: str) -> List[Dict]:
    """Rows with a line -> quick_log play dicts (see props_engine.plays_for_log)."""
    return PE.plays_for_log([dict(r, p_final=r.get("p_final", r.get("p_over"))) for r in rows], market, game_label)


def team_baseline(pgames, team) -> Optional[float]:
    """The team's normal points per game in the sample (the yardstick an implied team total is read against)."""
    ts = team_scoring(pgames).get(team)
    return ts["for"] if ts else None


# --------------------------------------------------------------------------- pace (fix 5)
def team_scoring(pgames: Iterable[Dict]) -> Dict:
    """{team: {"for": avg points scored, "against": avg allowed, "games"}} from player lines."""
    pts: Dict[Tuple, float] = {}
    pair: Dict[Tuple, object] = {}
    for p in pgames or []:
        key = (p.get("game"), p.get("team"))
        pts[key] = pts.get(key, 0.0) + _num((p.get("stats") or {}).get("pts"))
        pair[key] = p.get("opp")
    agg: Dict = {}
    for (g, t), v in pts.items():
        a = agg.setdefault(t, {"for": [], "against": []})
        a["for"].append(v)
        opp_pts = pts.get((g, pair[(g, t)]))
        if opp_pts is not None:
            a["against"].append(opp_pts)
    return {t: {"for": sum(a["for"]) / len(a["for"]), "games": len(a["for"]),
                "against": (sum(a["against"]) / len(a["against"])) if a["against"] else None}
            for t, a in agg.items() if a["for"]}


def pace_flag(pgames: Iterable[Dict], home, away) -> Optional[Dict]:
    """Projected game total from both teams' scoring for/against vs the sample's average game total."""
    ts = team_scoring(pgames)
    h, a = ts.get(home), ts.get(away)
    if not h or not a or h["against"] is None or a["against"] is None:
        return None
    proj = (h["for"] + a["against"]) / 2 + (a["for"] + h["against"]) / 2
    totals = [t["for"] + t["against"] for t in ts.values() if t["against"] is not None]
    league = sum(totals) / len(totals) if totals else None
    if not league:
        return None
    pct = (proj - league) / league * 100
    label = ("⚡ Fast, high-scoring matchup" if pct >= PACE_FLAG_PCT else
             "🐢 Slow, low-scoring matchup" if pct <= -PACE_FLAG_PCT else "Normal pace")
    return {"projected_total": proj, "league_total": league, "pct": pct, "label": label}


# --------------------------------------------------------------------------- one matchup number for every page
STAT_MARKET = {"pts": "Points", "reb": "Rebounds", "ast": "Assists", "fg3m": "Threes Made"}


def player_slots(pgames) -> Dict:
    """{player id: G/F/C} from each player's most recent game in the sample."""
    import position_matchups as PM
    latest: Dict = {}
    for p in pgames or []:
        pid = p.get("pid")
        if pid is None:
            continue
        o = str(p.get("order") or "")
        if pid not in latest or o > latest[pid][0]:
            latest[pid] = (o, PM.position_group(p.get("pos")))
    return {pid: slot for pid, (_, slot) in latest.items() if slot}


def position_factors(players: Iterable[Tuple], cur_pgames, prior_pgames, sport: str = "NBA",
                     mode: str = "blend", charts: Optional[Dict] = None) -> Dict:
    """The position-level matchup factor -- shrunk for small samples and blended with last season, exactly as the
    Player props tab computes it -- for each (player id, opponent id) in `players`, for every stat in STAT_MARKET.
    Returns {(player id, stat key): factor}. Hot Hand Engine and Matchup Lab show this same number, so a player's
    matchup reads the same on every page."""
    import position_matchups as PM
    slots = player_slots(list(cur_pgames or []) + list(prior_pgames or []))
    charted = PM.chart_groups(charts)          # tonight's depth chart wins over the roster label
    slots.update(charted)
    cur_allowed = PM.allowed_by_slot(cur_pgames or [], sport)
    prior_allowed = PM.allowed_by_slot(prior_pgames or [], sport) if prior_pgames else None
    tables = {}
    for stat, market in STAT_MARKET.items():
        tables[stat] = (defense_allowed(cur_allowed, market),
                        defense_allowed(prior_allowed, market) if prior_allowed else None)
    second = PM.secondary_slots(cur_pgames or prior_pgames or [])
    out: Dict = {}
    for pid, opp in players:
        slot = slots.get(pid)
        if slot is None:
            continue
        for stat, (cur_t, pri_t) in tables.items():
            cur = raw_factor(cur_t, opp, slot)
            pri = raw_factor(pri_t, opp, slot) if pri_t else None
            if cur is None and pri is None:
                continue
            f = blended_factor(cur, pri, mode)["factor"]
            s2 = None if pid in charted else second.get(pid)
            if s2 and s2 != slot:                 # a double big (position_matchups.secondary_slots)
                c2, p2 = raw_factor(cur_t, opp, s2), (raw_factor(pri_t, opp, s2) if pri_t else None)
                if c2 is not None or p2 is not None:
                    f = PM.blend_factor(f, blended_factor(c2, p2, mode)["factor"])
            out[(pid, stat)] = f
    return out


def _tuning(sport: str, market: str, slot: str = "") -> float:
    """Approved Postgame Review adjustments (model_tuning); 1.0 when none."""
    try:
        import model_tuning as MT
        return MT.factor(sport, market, slot)
    except Exception:                                           # noqa: BLE001
        return 1.0
