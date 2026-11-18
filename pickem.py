"""
pickem.py -- the Pick'em board: PrizePicks, Underdog and DraftKings Pick6 lines read for More / Less (Nov 18).

Owner: "for player props for college sports that are not getting lines from DraftKings, FanDuel ... is there a manner
that we can ... tell me whether a player is a good Pick6, PrizePicks, Underdog pick ... Can we build a section
specific to those for the sports?"

What a pick'em pick needs: its chance of clearing the app's line has to beat the entry's break-even per pick (a
2-pick Power Play paying 3x needs 57.7% a pick: (1/3)^(1/2)). Where that chance comes from matters more than anything:

  * BOOKS-CHECKED (the app's player is also priced at a sportsbook): the books' no-vig chance, moved from the
    books' line to the app's line along the model's own outcome curve for that player, then the model gets its
    usual measured say (MODEL_WEIGHT x the sport's trust, ~0.2 in the NBA). This is the honest edge in pick'em:
    the app's line is fixed for everyone, so when the books have moved off it, the app line is stale.
  * MODEL ONLY (no sportsbook posts him -- most college props): research/pickem_study.py (Nov 18, 390 NBA, 254 NHL,
    114 NCAAF, 64 NFL graded reads with only a pick'em line) found the model's side hit 44-51% in the NBA and NFL --
    below a coin flip at a 52-80% stated chance, and well below 57.7%. Held out, a coin flip beat the model as is
    (log loss 0.693 vs 0.754). So these keep only NO_BOOK_SHARE of the model's lean and almost never clear a
    break-even; they are listed for the record, labelled, and graded, not sold as picks.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

NO_BOOK_SHARE = 0.10      # research/pickem_study.py: held-out best share of the model's lean with no book, 0.05-0.10

# Checked Nov 18, 2026. PrizePicks: its own payouts page (updated Oct 19, 2026). Underdog and Pick6: third-party
# summaries (Pick6 is a pooled contest -- its "multipliers" are DraftKings' estimates of past results, not fixed).
APPS = {
    "prizepicks": {"name": "PrizePicks",
                   "power": {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5},
                   "flex": {2: {2: 2.0, 1: 0.5}, 3: {3: 3.0, 2: 1.0}, 4: {4: 6.0, 3: 1.5},
                            5: {5: 10.0, 4: 2.0, 3: 0.4}, 6: {6: 25.0, 5: 2.0, 4: 0.4}},
                   "note": "PrizePicks payouts page, updated Oct 19, 2026. Demons, goblins and same-game lineups "
                           "pay less -- check the payout on your entry screen.",
                   "source": "https://www.prizepicks.com/resources/prizepicks-payouts"},
    "underdog": {"name": "Underdog",
                 "power": {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0},
                 "flex": None,
                 "note": "Underdog's standard payouts (third-party summary, Mar 2026). Picks with their own "
                         "multiplier pay more or less -- check the entry screen.",
                 "source": "https://oddsreference.pages.dev/dfs/tools/pickem-payout-calculator"},
    "pick6": {"name": "DK Pick6",
              "power": {2: 3.0, 3: 5.0, 4: 10.0, 5: 15.0, 6: 25.0},
              "flex": None,
              "note": "Pick6 is a pooled contest: prizes depend on how many entries go perfect. These are typical "
                      "results (third-party summary), not fixed payouts.",
              "source": "https://www.legalsportsreport.com/dfs-sites/draftkings-pick6/"},
}


def breakeven(mult: float, n: int) -> float:
    """Chance each pick needs for an all-correct n-pick entry paying `mult` x to break even."""
    return (1.0 / float(mult)) ** (1.0 / n)


def _norm(s) -> str:
    import props_engine as PE
    return PE.norm_name(s)


def p_more(projection, values, dist, line) -> Optional[float]:
    """Chance of MORE at an app line. A whole-number line can tie (the apps void a tied pick and drop the entry a
    level), so it is the chance of more GIVEN no tie: P(X >= L+1) / (P(X >= L+1) + P(X <= L-1))."""
    import props_engine as PE
    L = float(line)
    if L != int(L):
        return PE.prob_over(projection, values, L, dist)
    gt = PE.prob_over(projection, values, L + 0.5, dist)
    ge = PE.prob_over(projection, values, L - 0.5, dist)
    if gt is None or ge is None:
        return None
    lt = 1.0 - ge
    return gt / (gt + lt) if gt + lt > 0 else None


def books_chance_at(read: Dict, book_line: float, p_book_over: float, app_line: float) -> Optional[float]:
    """The books' no-vig chance of OVER, moved from their line to the app's line along the model's own outcome curve
    for this player (the projection is slid until the curve gives the books' chance at the books' line)."""
    import props_engine as PE
    values, dist = list(read.get("values") or []), read.get("dist") or "normal"
    if abs(float(book_line) - float(app_line)) < 1e-9 and float(app_line) != int(float(app_line)):
        return p_book_over
    proj = read.get("projection")
    if proj is None:
        return None
    lo, hi = -max(abs(proj), 5.0) * 2 - 20, max(abs(proj), 5.0) * 3 + 20
    lo = max(lo, 0.0) if dist == "count" else lo
    for _ in range(60):
        mid = (lo + hi) / 2
        p = PE.prob_over(mid, values, float(book_line), dist)
        if p is None:
            return None
        if p < p_book_over:
            lo = mid
        else:
            hi = mid
    return p_more((lo + hi) / 2, values, dist, float(app_line))


def legs(reads: Dict, offers: Sequence[Dict], app: str, sport: str) -> List[Dict]:
    """Every line `app` posts that the model has read: chance of More at the app's line, the side, and where the
    chance came from ("books" / "model only")."""
    import props_engine as PE
    by_key = {}
    for r in (reads or {}).values():
        if r.get("player") and r.get("market_key") and r.get("projection") is not None:
            by_key[(_norm(r["player"]), r["market_key"])] = r
    groups: Dict = {}
    for o in offers or []:
        groups.setdefault((_norm(o.get("player")), o.get("market")), []).append(o)
    out = []
    for (pl, mk), offs in groups.items():
        read = by_key.get((pl, mk))
        if not read:
            continue
        # the app's line for each side (DK Pick6 sometimes posts More and Less at different numbers)
        cands = []
        for o in offs:
            for pside, entry in ((o.get("pickem") or {}).get(app) or {}).items():
                cands.append((pside, float(o["point"]), (entry or {}).get("multiplier"), o.get("commence_time")))
        if not cands:
            continue
        priced = [o for o in offs if (o.get("over") or {}) and (o.get("under") or {})]
        book = PE.shop(priced) if priced else None
        t = PE.trust_for(sport, read.get("market"))
        w = PE.MODEL_WEIGHT * (1.0 if t is None else t)
        best = None
        for pside, line, mult, kick in cands:
            pm = p_more(read["projection"], read.get("values") or [], read.get("dist") or "normal", line)
            if pm is None:
                continue
            pb = books_chance_at(read, book["line"], book["p_market"], line) \
                if book and book.get("p_market") is not None else None
            p = (pb + w * (pm - pb)) if pb is not None else (0.5 + NO_BOOK_SHARE * (pm - 0.5))
            side = "More" if pside == "over" else "Less"
            chance = p if side == "More" else 1 - p
            if best is None or chance > best["chance"]:
                best = {"player": read["player"], "market": read.get("market"), "market_key": mk,
                        "game": read.get("game"), "team": read.get("team_name") or read.get("team"), "kickoff": kick,
                        "app_line": line, "side": side, "chance": chance, "p_over": p,
                        "basis": "books" if pb is not None else "model only", "projection": read["projection"],
                        "model_over": pm, "book_line": book["line"] if book else None,
                        "book_over": book.get("p_market") if book else None, "books_over_at_app": pb,
                        "multiplier": mult}
        if best:
            out.append(best)
    out.sort(key=lambda x: (x["basis"] != "books", -x["chance"]))
    return out


def best_entry(legs_: Sequence[Dict], n: int, floor: float) -> List[Dict]:
    """The n strongest books-checked legs clearing `floor`, at most one player per game (owner's rule for anything
    that isn't a same-game parlay -- pick'em apps also cut payouts on same-game lineups)."""
    out, games = [], set()
    for x in sorted(legs_, key=lambda x: -x["chance"]):
        if x["basis"] != "books" or x["chance"] < floor or x.get("game") in games:
            continue
        out.append(x)
        games.add(x.get("game"))
        if len(out) == n:
            break
    return out


def entry_odds(entry: Sequence[Dict], app: str, flex: bool = False, sport: Optional[str] = None,
               sims: int = 40000) -> Optional[Dict]:
    """{"all": chance every pick hits, "ev": expected return per $1 (payout x chance - 1), "dist": {hits: chance}}.
    Legs from different games are close to independent (measured same-game correlation is what slip_sim models);
    the simulator is used anyway so a flex entry's partial payouts come out of the same draw."""
    import numpy as np
    import slip_sim as SIM
    n = len(entry)
    cfg = APPS.get(app) or {}
    table = (cfg.get("flex") or {}).get(n) if flex else None
    mult = None if flex else (cfg.get("power") or {}).get(n)
    if n < 2 or (mult is None and table is None):
        return None
    legs_sim = [{"p": x["chance"], "player": x["player"], "game": x.get("game"), "market": x.get("market"),
                 "side": "Over" if x["side"] == "More" else "Under", "sport": sport} for x in entry]
    R = SIM.correlation_matrix(legs_sim)
    rng = np.random.default_rng(7)
    from statistics import NormalDist
    z = np.array([NormalDist().inv_cdf(min(max(x["chance"], 1e-6), 1 - 1e-6)) for x in entry])
    try:
        L = np.linalg.cholesky(R)
    except np.linalg.LinAlgError:
        L = np.eye(n)
    draws = rng.standard_normal((sims, n)) @ L.T
    hits = (draws < z).sum(axis=1)
    dist = {k: float((hits == k).mean()) for k in range(n + 1)}
    pay = sum(dist[k] * (table.get(k, 0.0) if table else (mult if k == n else 0.0)) for k in dist)
    return {"all": dist[n], "ev": pay - 1.0, "dist": dist, "mult": mult, "table": table}
