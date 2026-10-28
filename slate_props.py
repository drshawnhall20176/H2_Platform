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
        gl = game_lines_for(game_lines, g.get("home_name"), g.get("away_name"))
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
    sp = side_probs(row)
    if sp is None:
        return None
    side, p_final = sp["side"], sp["p_final"]
    p_mkt = sp["p_market"]
    lean = row.get("lean")
    leaning = lean in ("Over", "Under") and lean == side
    if leaning and p_mkt and sp["p_model"] is not None and p_mkt > 0:
        conviction = round(max(sp["p_model"] / p_mkt, 1.0), 2)
    else:
        conviction = 1.0
    price = row.get("over_price") if side == "Over" else row.get("under_price")
    bk = row.get("book") or {}
    best = bk.get("best_over") if side == "Over" else bk.get("best_under")
    s = slate_row or {}
    return {
        "Player": row["player"], "PlayerId": row["pid"], "Team": s.get("Team") or row.get("team_name"), "Game": row.get("game") or s.get("GameLabel"),
        "Opp": s.get("Opp") or row.get("opp_name"), "Versus": s.get("Opp") or row.get("opp_name"),
        "GameDate": s.get("_game_date") or row.get("game_date"),
        "Market": row["market"], "Side": side, "Line": row["line"], "LineSource": "book",
        "Projection": round(row["projection"], 2) if row.get("projection") is not None else None,
        "ModelProb": round(p_final, 4), "Fair": PE.american(p_final),
        "RealPrice": price, "RealPriceBook": best[0] if best else None, "PriceSource": "book" if price is not None else "model_fair",
        "Conviction": conviction, "ConvictionSource": "book" if p_mkt else "model_typical",
        "_ceiling": round(1.0 / p_mkt, 2) if p_mkt else None,
        "Lean": lean, "EV": row.get("ev"), "Gap": row.get("gap"), "GapPct": row.get("gap_pct"),
        "Notes": PE.GAP_TAG if row.get("gap") in ("big", "big-low-count") or row.get("gap_from") else None,
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
def pmf(projection: Optional[float], values: Sequence[float], dist: str, max_k: Optional[int] = None) -> List[float]:
    """P(X = k) for k = 0..max_k under the Player props distribution, so P(X > line) read off this array equals
    props_engine.prob_over(projection, values, line, dist) at every half line."""
    if projection is None:
        return []
    top = max_k or int(max(projection * 3 + 10, max(values or [0]) + 10))
    sf = [1.0] + [PE.prob_over(projection, values, k - 0.5, dist) or 0.0 for k in range(1, top + 1)]
    sf = [min(sf[k], sf[k - 1]) if k else sf[k] for k in range(len(sf))]          # never increasing
    probs = [sf[k] - sf[k + 1] for k in range(top)] + [sf[top]]                   # the tail sits in the last cell
    return probs
