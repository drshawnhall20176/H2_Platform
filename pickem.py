"""
pickem.py -- the Pick'em board: PrizePicks, Underdog, DraftKings Pick6, ParlayPlay and Dabble lines read for More /
Less (Nov 18). Novig and ProphetX (prediction exchanges) are price sources here, not apps: their two-sided prices join
the sportsbooks' in the "books-checked" chance.

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
    # Nov 18 (owner: "add Novig and any other pick'em app"): the other two apps in the odds feed. Both pay a table by
    # pick count like the others, AND post a price on every pick (Dabble near even, e.g. -118/+119; ParlayPlay with a
    # margin, e.g. -125/-125). A pick the app itself prices heavy pays less on the entry screen, so a pick there has to
    # clear BOTH the table's break-even and its own price's implied chance.
    "parlayplay": {"name": "ParlayPlay", "priced": True,
                   "power": {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 35.0},
                   "flex": None,
                   "note": "ParlayPlay All-In payouts (third-party summary, Apr 2026); each pick also carries its own "
                           "multiplier, so heavy-priced picks pay less -- check the entry screen.",
                   "source": "https://bettorsinsider.com/dfs/2026/04/29/prizepicks-vs-parlayplay-vs-dabble-a-complete-dfs-pickem-comparison-for-2026/"},
    "dabble_us_dfs": {"name": "Dabble", "priced": True,
                      "power": {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5},
                      "flex": None,
                      "note": "Dabble publishes no fixed table; reviewers call its standard payouts comparable to "
                              "PrizePicks', which is what's assumed here -- check the entry screen.",
                      "source": "https://bettorsinsider.com/dfs/2026/04/29/prizepicks-vs-parlayplay-vs-dabble-a-complete-dfs-pickem-comparison-for-2026/"},
}


def is_priced(app: str) -> bool:
    """True for an app that posts a price on each pick (Dabble, ParlayPlay) on top of its payout table."""
    return bool((APPS.get(app) or {}).get("priced"))


def _decimal(price) -> Optional[float]:
    try:
        a = float(price)
    except (TypeError, ValueError):
        return None
    if a >= 100:
        return 1 + a / 100.0
    if a <= -100:
        return 1 + 100.0 / -a
    return None


def needed(price) -> Optional[float]:
    """The chance a pick priced `price` (American) needs to break even: its implied probability."""
    d = _decimal(price)
    return 1.0 / d if d else None


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


# Nov 18 (research/dabble_ladder.py): the exchanges carry resting orders nobody has matched -- ProphetX -25000 on both
# sides, Novig -456 / +178 -- which would wreck a no-vig average. An exchange price counts only as a two-sided quote
# inside +-1000 whose two sides add up to no more than EXCHANGE_MAX_HOLD (a tight, traded market).
EXCHANGE_MAX_HOLD = 1.08

# Nov 18 (research/pickem_apps_live.py): Dabble hung lines 2-5 below every book (Quickley 4.5 assists, books 6.5,
# Novig -456 on the over) -- a "41% for a 3-pick at 6x" entry nobody should believe. A line that far from the books
# is a discounted alt (PrizePicks goblins pay less), stale, or a different setup; it's listed and flagged, never put
# in an entry.
FAR_GAP = 1.0             # points, or FAR_SHARE of the books' line, whichever is larger
FAR_SHARE = 0.12


def far_from_books(app_line: float, book_line: Optional[float]) -> bool:
    if book_line is None:
        return False
    return abs(float(app_line) - float(book_line)) > max(FAR_GAP, FAR_SHARE * abs(float(book_line)))


def _implied(a: float) -> float:
    return 100.0 / (a + 100.0) if a >= 100 else -a / (-a + 100.0)


def clean_exchanges(o: Dict) -> Dict:
    """The offer with any exchange quote that isn't a tight two-sided market removed."""
    import odds_api as O
    over, under = dict(o.get("over") or {}), dict(o.get("under") or {})
    changed = False
    for b in O.EXCHANGE_BOOKS:
        if b not in over and b not in under:
            continue
        a, u = over.get(b), under.get(b)
        ok = False
        try:
            if a is not None and u is not None and max(abs(float(a)), abs(float(u))) <= 1000 \
                    and abs(float(a)) >= 100 and abs(float(u)) >= 100:
                ok = _implied(float(a)) + _implied(float(u)) <= EXCHANGE_MAX_HOLD
        except (TypeError, ValueError):
            ok = False
        if not ok:
            over.pop(b, None)
            under.pop(b, None)
            changed = True
    return {**o, "over": over, "under": under} if changed else o


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
                cands.append((pside, float(o["point"]), (entry or {}).get("multiplier"), o.get("commence_time"),
                              (entry or {}).get("price")))
        if not cands:
            continue
        priced = [c for c in (clean_exchanges(o) for o in offs) if (c.get("over") or {}) and (c.get("under") or {})]
        book = PE.shop(priced) if priced else None
        t = PE.trust_for(sport, read.get("market"))
        w = PE.MODEL_WEIGHT * (1.0 if t is None else t)
        best = None
        priced_app = is_priced(app)
        for pside, line, mult, kick, price in cands:
            pm = p_more(read["projection"], read.get("values") or [], read.get("dist") or "normal", line)
            if pm is None:
                continue
            pb = books_chance_at(read, book["line"], book["p_market"], line) \
                if book and book.get("p_market") is not None else None
            p = (pb + w * (pm - pb)) if pb is not None else (0.5 + NO_BOOK_SHARE * (pm - 0.5))
            side = "More" if pside == "over" else "Less"
            chance = p if side == "More" else 1 - p
            need = needed(price) if priced_app else None
            score = chance - (need if need is not None else 0.5) if priced_app else chance
            if best is None or score > best["_score"]:
                best = {"player": read["player"], "market": read.get("market"), "market_key": mk,
                        "game": read.get("game"), "team": read.get("team_name") or read.get("team"), "kickoff": kick,
                        "app_line": line, "side": side, "chance": chance, "p_over": p,
                        "basis": "books" if pb is not None else "model only", "projection": read["projection"],
                        "model_over": pm, "book_line": book["line"] if book else None,
                        "book_over": book.get("p_market") if book else None, "books_over_at_app": pb,
                        "multiplier": mult, "price": price if priced_app else None, "needed": need,
                        "far": far_from_books(line, book["line"] if book else None),
                        "_score": score}
        if best:
            best.pop("_score", None)
            out.append(best)
    out.sort(key=lambda x: (x["basis"] != "books", -(x["chance"] - (x.get("needed") or 0.0))))
    return out


def best_entry(legs_: Sequence[Dict], n: int, floor: float) -> List[Dict]:
    """The n strongest books-checked legs clearing `floor`, at most one player per game (owner's rule for anything
    that isn't a same-game parlay -- pick'em apps also cut payouts on same-game lineups)."""
    out, games = [], set()
    for x in sorted(legs_, key=lambda x: -(x["chance"] - (x.get("needed") or 0.0))):
        bar = max(floor, x["needed"]) if x.get("needed") is not None else floor   # table AND its own price
        if x["basis"] != "books" or x.get("far") or x["chance"] < bar or x.get("game") in games:
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
