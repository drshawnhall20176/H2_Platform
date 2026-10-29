"""
slate_props.py — the Player props model run across a whole slate, for the pages that rank plays across every
game (Best Bets, Graded Picks, Suggested Parlays, Speculative Basket, Slip Lab, Analyst Desk, Command Center) and
for Edge Board's prices.

WHY THIS EXISTS (Oct 28 sync check): those pages used to run their own, older engine -- an unweighted resample of
a player's last 10 games (last season's padding at full weight), no matchup, rest, minutes or game environment --
while Hot Hand, Matchup Lab and Position Matchups shared one model. The same player came out at two different
numbers (Davion Mitchell's points: 15.6 on Edge Board vs 18.2 everywhere else), and plays were ranked against
placeholder lines (22.5 points for a bench player), so the top of Best Bets was a wall of meaningless Unders.

Now every page reads a player through the SAME function Position Matchups uses (player_props.player_rows, with
player_props.market_tables / team_rotation / game_context building its inputs), against the book's real line:

  * Projection   -- identical to Player props' Projection.
  * Model %      -- Player props' Chance (the model's probability blended with the books' no-vig price).
  * Side / Lean  -- Player props' lean, including its gap policy ("Check news" when the line is far from the
                    projection, the low-count rule, the hit-rate and returning-player checks).
  * Conviction   -- how far the MODEL's own probability is from the market's for that side; a play gets one
                    only when Player props leans that way, so every graded play is a play Player props likes.
  * No book line -- no play. (A placeholder line isn't a bet.)

pmf() turns a projection into the probability array Edge Board's pricing reads, so its model probability at
any line is the Player props model probability at that line.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import player_props as PPR
import props_engine as PE

# Best Bets' four basketball markets: Odds API key -> Player props market.
YES_ONLY = ("player_anytime_td", "player_1st_td", "player_last_td")   # = odds_api.YES_ONLY_MARKETS ("Yes" only)
CORE_MARKETS = {"player_points": "Points", "player_rebounds": "Rebounds", "player_assists": "Assists",
                "player_threes": "Threes Made"}
ROTATION_GAMES = 7          # = position_data.LEAGUE_GAMES_PER_TEAM


def _int_or(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return x


def _norm_team(name) -> str:
    return " ".join(str(name or "").lower().replace(".", "").split())


def game_lines_for(game_lines: Iterable[Dict], home_name: str, away_name: str) -> Dict:
    """{"spread_home", "total"} for one game out of odds_api.fetch_slate_game_lines' list (matched on team names;
    {} when the books haven't listed it)."""
    h, a = _norm_team(home_name), _norm_team(away_name)
    for g in game_lines or []:
        gh, ga = _norm_team(g.get("home_team")), _norm_team(g.get("away_team"))
        if (gh == h or gh.endswith(h.split()[-1] if h else "#")) and (ga == a or ga.endswith(a.split()[-1] if a else "#")):
            spreads = g.get("spreads") or {}
            sh = spreads.get(g.get("home_team"))
            if sh is None and spreads.get(g.get("away_team")) is not None:
                sh = -spreads[g.get("away_team")]
            return {"spread_home": sh, "total": g.get("total")}
    return {}


def slate_reads(games: Sequence[Dict], sample: Dict, offers: Optional[List[Dict]], book: Optional[str] = None,
                injuries: Optional[Dict] = None, rest: Optional[Dict] = None, game_lines: Optional[List[Dict]] = None,
                markets: Optional[Dict[str, str]] = None, mode: str = "blend", sport: str = "NBA",
                news_checked: bool = False) -> Dict[Tuple, Dict]:
    """{(player id, odds market key): Player props row} for every rotation player in every game.

    games: build_slate meta ({"label","home_id","away_id","home_name","away_name",...}); sample: {"cur","prior"}
    league player-games (position_data.nba_league_props_sample); injuries: {team id: {name: status}};
    rest: {team id: rest days}; game_lines: odds_api.fetch_slate_game_lines' list. Each row also carries
    "game", "team_id", "opp_id" and "market_key"."""
    cur, prior = list(sample.get("cur") or []), list(sample.get("prior") or [])
    if not cur and not prior:
        return {}
    markets = markets or CORE_MARKETS
    injuries, rest = injuries or {}, rest or {}
    baseline = cur or prior
    tables = {mk: PPR.market_tables(cur, prior, m, sport) for mk, m in markets.items()}
    out: Dict[Tuple, Dict] = {}
    for g in games:
        home, away = _int_or(g.get("home_id")), _int_or(g.get("away_id"))
        gl = (game_lines.get(g.get("label")) or {}) if isinstance(game_lines, dict) else \
            game_lines_for(game_lines, g.get("home_name"), g.get("away_name"))
        for team, opp, is_home in ((home, away, True), (away, home, False)):
            rot = PPR.team_rotation(cur, prior, team, injuries.get(team), sport, last_n=ROTATION_GAMES)
            if not rot:
                continue
            ctx = PPR.game_context(team, is_home, gl.get("spread_home"), gl.get("total"), rest.get(team),
                                   rest.get(opp), baseline, offers=offers, book=book, news_checked=news_checked,
                                   sport=sport)
            for mk, market in markets.items():
                t = tables[mk]
                for row in PPR.player_rows(rot, opp, market, t["cur"], t["prior"], cur, prior, mode=mode,
                                           context=ctx):
                    row.update(game=g.get("label"), team_id=team, opp_id=opp, market_key=mk, market=market,
                               home=is_home, team_name=g.get("home_name" if is_home else "away_name"),
                               opp_name=g.get("away_name" if is_home else "home_name"),
                               game_date=g.get("game_date"))
                    out[(row["pid"], mk)] = row
    return out


# --------------------------------------------------------------------------- football + hockey (Oct 29)
def props_markets(sport: str) -> Dict[str, str]:
    """{Odds API market key: Player props market} for the markets both this sport's pick pages and its props model
    cover. Markets the props model doesn't have keep the older engine (placeholder lines dropped)."""
    import position_matchups as PM
    import sports
    fam = PM.FAMILY_BY_SPORT.get(sport)
    wanted = set(sports.get(sport).markets or [])
    if fam == "basketball":
        return {k: v for k, v in CORE_MARKETS.items() if k in wanted}
    if fam == "football":
        import football_props as FP
        return {m["odds"]: name for name, m in FP.MARKETS.items() if m.get("odds") in wanted}
    if fam == "hockey":
        import hockey_props as HP
        return {m["odds"]: name for name, m in HP.MARKETS.items() if m.get("odds") in wanted}
    return {}


def team_rows(family: str, sport: str, bundle: Dict, team, opp, market: str, spread_home: Optional[float],
              total: Optional[float], offers=None, book=None, news_checked: bool = False, slope: float = 1.0,
              model_weight: float = PE.MODEL_WEIGHT, lines: Optional[Dict] = None,
              prices: Optional[Dict] = None) -> List[Dict]:
    """One team's football or hockey Player props rows for one market -- the ONE recipe Position Matchups and the
    slate pages share. `bundle` is position_data.load_bundle's game bundle; spread_home is the home side's spread
    (hockey: the goal margin worked out from the moneyline, props_odds.hockey_spread_from_ml)."""
    props = bundle.get("props") or {}
    is_home = team == bundle.get("home")
    implied = PE.implied_team_totals(total, spread_home)
    team_imp = (implied[0] if is_home else implied[1]) if implied else None
    opp_imp = (implied[1] if is_home else implied[0]) if implied else None
    spread_team = None if spread_home is None else (spread_home if is_home else -spread_home)
    rest = props.get("rest") or {}
    ctx = {"rest_days": (rest.get(team) or {}).get("rest_days"), "opp_rest_days": (rest.get(opp) or {}).get("rest_days"),
           "spread": spread_team, "offers": offers, "slope": slope, "model_weight": model_weight, "book": book,
           "news_checked": bool(news_checked), "prices": prices or {}}
    if family == "football":
        import football_props as FP
        roster = (props.get("roster") or {}).get(team) or []
        return FP.player_rows(roster, team, opp, market, props.get("pgames") or [], bundle.get("allowed") or {},
                              lines=lines, context=dict(ctx, implied=team_imp), sport=sport)
    if family == "hockey":
        import hockey_props as HP
        pg = props.get("pgames") or []
        rot = (props.get("rotation") or {}).get(team) or {}
        return HP.player_rows(rot, team, opp, market, pg, lines=lines,
                              context=dict(ctx, env=PE.env_factor(team_imp, HP.team_goals(pg, team)),
                                           opp_env=PE.env_factor(opp_imp, HP.team_goals(pg, opp)),
                                           team_games=(props.get("team_games") or {}).get(team)))
    return []


def game_line_values(family: str, gl: Optional[Dict]) -> Tuple[Optional[float], Optional[float]]:
    """(spread_home, total) the page would default to from props_odds.game_lines -- hockey's spread from the
    moneyline (the +/-1.5 puck line says little), exactly as Position Matchups does."""
    gl = gl or {}
    if family == "hockey":
        import props_odds as PO
        return PO.hockey_spread_from_ml(gl.get("p_home")), gl.get("total")
    return gl.get("spread_home"), gl.get("total")


def family_slate_reads(sport: str, games: Sequence[Dict], bundles: Dict, offers, game_lines: Dict, book=None,
                       markets: Optional[Dict[str, str]] = None, news_checked: bool = False) -> Dict[Tuple, Dict]:
    """{(player key, market key): row} for every football / hockey game on the slate. `bundles` {label: bundle},
    `game_lines` {label: props_odds.game_lines}."""
    import position_matchups as PM
    family = PM.FAMILY_BY_SPORT.get(sport)
    markets = markets or props_markets(sport)
    out: Dict[Tuple, Dict] = {}
    for g in games:
        b = bundles.get(g.get("label"))
        if not b or not b.get("props"):
            continue
        spread_home, total = game_line_values(family, game_lines.get(g.get("label")))
        names = b.get("names") or {}
        for team, opp in ((b["home"], b["away"]), (b["away"], b["home"])):
            for mk, market in markets.items():
                for row in team_rows(family, sport, b, team, opp, market, spread_home, total, offers=offers,
                                     book=book, news_checked=news_checked):
                    row.update(game=g.get("label"), team_id=team, opp_id=opp, market_key=mk, market=market,
                               home=team == b["home"], team_name=names.get(team, team),
                               opp_name=names.get(opp, opp), game_date=g.get("game_date"))
                    out[(row["pid"], mk)] = row
    return out


def index_from_reads(reads: Dict[Tuple, Dict], rows: Sequence[Dict], normalize_name) -> Dict:
    """Edge Board index entries from the reads (any sport): the Player props distribution around ITS projection,
    the read itself (odds_api.compute_edges blends it with the market and applies the gap policy) and the book line."""
    import numpy as np
    by_pid = {r.get("_pid"): r for r in rows or []}
    index: Dict = {}
    for (pid, mkey), row in reads.items():
        if row.get("out") or row.get("projection") is None:
            continue
        s = by_pid.get(pid) or {}
        values = list(row.get("values") or [])
        ctx = {"player": row["player"], "team": s.get("Team") or row.get("team_name"), "game": row.get("game"),
               "opp": s.get("Opp") or row.get("opp_name"), "lineup": "Active",
               "game_date": s.get("_game_date") or row.get("game_date"), "pid": pid, "position": row.get("slot")}
        floor = row.get("sd_floor") or (0.25, 1.0)
        index[(normalize_name(row["player"]), mkey)] = {
            "dist": np.asarray(pmf(row["projection"], values, row.get("dist") or "normal", sd_floor=floor), dtype=np.float64),
            "mean": float(row["projection"]), "n_games": row.get("games") or 0, "ctx": ctx, "read": row,
            "line": row.get("line") if row.get("line_src") == "book" else None}
    return index


def board_from_index(index: Dict, P) -> List[Dict]:
    """The model board for an index mixing Player props reads with the older engine's entries: reads at the
    book's line with Player props' Chance (no placeholder lines), the rest from P.default_board_from_index."""
    reads = {k: v for k, v in index.items() if "read" in v}
    rest = {k: v for k, v in index.items() if "read" not in v}
    out = []
    for (_nm, mkey), entry in reads.items():
        row, ctx = entry["read"], entry["ctx"]
        sp = side_probs(row) if entry.get("line") is not None else None
        if sp is None:
            continue
        use = PE.use_tag(row)[0]
        out.append(P._signal(ctx["player"], ctx["team"], ctx["game"], row.get("market"), sp["side"], entry["line"],
                             sp["p_final"], entry["mean"], Opp=ctx.get("opp"), Lineup=ctx.get("lineup"),
                             GameTime=ctx.get("game_date"), PlayerId=ctx.get("pid"), MarketKey=mkey,
                             LineSource="book", Lean=row.get("lean"), Use=use))
    if rest:
        out += [b for b in P.default_board_from_index(rest) if b.get("LineSource", "book") != "default"
                or not reads]
    return out


def by_name(reads: Dict[Tuple, Dict]) -> Dict[Tuple, Dict]:
    """The same reads keyed (normalized name, market key), for callers that only have a name."""
    return {(PE.norm_name(r["player"]), mk): r for (_pid, mk), r in reads.items()}


def side_probs(row: Dict) -> Optional[Dict]:
    """{"side", "p_final", "p_model", "p_market"} for the row's side (each as the probability OF that side)."""
    side = row.get("side")
    if side not in ("Over", "Under") or row.get("p_final") is None:
        return None

    def flip(p):
        return None if p is None else (p if side == "Over" else 1.0 - p)
    return {"side": side, "p_final": flip(row["p_final"]), "p_model": flip(row.get("p_model")),
            "p_market": flip(row.get("p_market"))}


def why(row: Dict) -> str:
    """One line in Player props' own terms: form, matchup, projection vs the line, and any flag."""
    bits = []
    if row.get("recent_avg") is not None:
        bits.append(f"form {row['recent_avg']:.1f}" + (" (incl. last season)" if row.get("filled") else ""))
    if row.get("factor") is not None and abs(row["factor"] - 1.0) >= 0.005:
        bits.append(f"matchup {row['factor'] - 1:+.0%}")
    if row.get("projection") is not None and row.get("line") is not None:
        bits.append(f"projects {row['projection']:.1f} vs {row['line']:g}")
    if row.get("hit"):
        h, n = row["hit"]
        bits.append(f"cleared {row['line']:g} in {h} of {n}")
    flags = [f for f in (row.get("flags") or []) if f]
    text = ", ".join(bits)
    if row.get("gap_from"):
        text = f"⚠️ {row['gap_from']} — {text}"
    elif row.get("gap") in ("big", "big-low-count"):
        text = f"⚠️ line {row['gap_pct']:+.0%} from the projection — {text}"
    if flags:
        text += " · " + "; ".join(flags[:2])
    return text


def play_from_row(row: Dict, slate_row: Optional[Dict] = None) -> Optional[Dict]:
    """A Player props row -> the play shape every pick page reads (build_best_bets' schema), or None when there is
    no book line or no side. Conviction and grade go only to plays Player props leans on."""
    if row.get("line") is None or row.get("line_src") != "book" or row.get("out"):
        return None
    yes_only = row.get("market_key") in YES_ONLY
    sp = side_probs(row)
    if sp is None:
        return None
    side, p_final = sp["side"], sp["p_final"]
    if row.get("market_key") in YES_ONLY and side != "Over":
        return None                                      # "won't score" isn't a play (no Under is posted)
    p_mkt = sp["p_market"]
    lean = row.get("lean")
    price = row.get("over_price") if side == "Over" else row.get("under_price")
    bk = row.get("book") or {}
    if bk.get("missing_book") and bk.get("wanted") in PE.PICKEM_BOOKS:
        return None                      # pricing at Pick6 / PrizePicks: a player the app doesn't post isn't a pick
    # What the play is fit for (props_engine.use_tag): only playable ones get a Conviction (and so a grade). A
    # sportsbook play needs a real price for that side; a pick'em play is measured against the entry break-even.
    use, use_why = PE.use_tag(row, side, row["line"])
    playable = use in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE)
    if playable and bk.get("pickem"):
        conviction = round(max(p_final / PE.PICKEM_BREAKEVEN, 1.0), 2)
    elif playable and price is not None and p_mkt and sp["p_model"] is not None and p_mkt > 0:
        conviction = round(max(sp["p_model"] / p_mkt, 1.0), 2)
    else:
        conviction = 1.0
    best = bk.get("best_over") if side == "Over" else bk.get("best_under")
    s = slate_row or {}
    return {
        "Player": row["player"], "PlayerId": row["pid"], "Team": s.get("Team") or row.get("team_name"), "Game": row.get("game") or s.get("GameLabel"),
        "Opp": s.get("Opp") or row.get("opp_name"), "Versus": s.get("Opp") or row.get("opp_name"),
        "GameDate": s.get("_game_date") or row.get("game_date"),
        "Market": row["market"], "Side": "Yes" if yes_only else side, "Line": None if yes_only else row["line"],
        "LineSource": "book",
        "Projection": round(row["projection"], 2) if row.get("projection") is not None else None,
        "ModelProb": round(p_final, 4), "Fair": PE.american(p_final),
        "RealPrice": price, "RealPriceBook": best[0] if best else None, "PriceSource": "book" if price is not None else "model_fair",
        "Conviction": conviction, "ConvictionSource": "book" if p_mkt else "model_typical",
        "_ceiling": round(1.0 / p_mkt, 2) if p_mkt else None,
        "Lean": lean, "EV": row.get("ev"), "Gap": row.get("gap"), "GapPct": row.get("gap_pct"),
        "Cushion": PE.cushion(row.get("projection"), row["line"], side),
        "Warnings": [w for w in PE.leg_warnings(row, side, row["line"]) if not w.startswith("thin cushion")],
        "Use": use, "UseWhy": use_why, "Pickem": bk.get("pickem", False), "PricedAt": bk.get("book"),
        "Notes": ",".join(([PE.GAP_TAG] if row.get("gap") in ("big", "big-low-count") or row.get("gap_from") else [])
                          + ([f"use:{PE.USE_KEY[use]}"] if use in PE.USE_KEY else [])) or None,
        "Why": why(row), "Model": "player-props",
        "PriorGames": row.get("games", 0) - row.get("season_games", 0) if row.get("filled") else 0,
        "PreseasonGames": 0,
        "_stat_key": "+".join(PPR.MARKETS.get(row["market"], ())), "_game_log": s.get("_game_log") or [],
    }


def plays(reads: Dict[Tuple, Dict], slate_rows: Sequence[Dict]) -> List[Dict]:
    """Every priced play on the slate, highest grade-worthy conviction first."""
    by_pid = {r.get("_pid"): r for r in slate_rows or []}
    out = []
    for (pid, _mk), row in reads.items():
        p = play_from_row(row, by_pid.get(pid))
        if p is None:
            continue
        out.append(p)
    out.sort(key=lambda x: (x["Conviction"], x["ModelProb"]), reverse=True)
    return out


# --------------------------------------------------------------------------- Edge Board
def pmf(projection: Optional[float], values: Sequence[float], dist: str, max_k: Optional[int] = None,
        sd_floor: Tuple[float, float] = (0.25, 1.0)) -> List[float]:
    """P(X = k) for k = 0..max_k under the Player props distribution, so P(X > line) read off this array equals
    props_engine.prob_over(projection, values, line, dist) at every half line."""
    if projection is None:
        return []
    top = max_k or int(max(projection * 3 + 10, max(values or [0]) + 10))
    sf = [1.0] + [PE.prob_over(projection, values, k - 0.5, dist, *sd_floor) or 0.0 for k in range(1, top + 1)]
    sf = [min(sf[k], sf[k - 1]) if k else sf[k] for k in range(len(sf))]          # never increasing
    probs = [sf[k] - sf[k + 1] for k in range(top)] + [sf[top]]                   # the tail sits in the last cell
    return probs
