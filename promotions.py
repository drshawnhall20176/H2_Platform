"""
promotions.py — sportsbook promotions for the Media Room, and who the model likes for each.

HONEST SCOPE: promotion terms change weekly and the platform can't read a sportsbook's live promo
page, so the catalog below is a hand-maintained list of RECURRING promos (summary written from
public coverage, with its source) — the page always tells the owner to confirm the promo is live
for the game in the book's app. The owner can also add a one-off promo on the page (session only).
Nothing here claims a promo is active today; the owner switches promos on.

Selections are model-driven, never invented: each promo `kind` maps to the model markets it
relates to, and the ranking rule is stated in plain words with the pick.
"""

from __future__ import annotations

from typing import Dict, List, Optional

ANYTIME_TD = "Anytime TD"
FIRST_TD = "First TD Scorer"
LAST_TD = "Last TD Scorer"

# kind -> (model markets to draw picks from — None means "any market", how picks are ranked,
#          plain-words explanation shown with the picks)
KINDS = {
    "longest_td": ([ANYTIME_TD], "longest-TD score",
                   "ranked by chance to score a rushing/receiving TD, weighted up for explosive "
                   "players (yards per touch) since the LONGEST TD wins"),
    "anytime_td": ([ANYTIME_TD], "model probability", "ranked by modeled chance to score a TD"),
    "first_td": ([FIRST_TD], "model probability", "ranked by modeled chance to score the first TD"),
    "last_td": ([LAST_TD], "model probability", "ranked by modeled chance to score the last TD"),
    "first_last_td": ([FIRST_TD], "model probability",
                      "ranked by modeled chance to score the first TD (the model gives the same chance "
                      "for the last TD)"),
    "boost": (None, "value / conviction",
              "the model's best-priced plays in the game — ranked by live EV% when it's on, otherwise "
              "by conviction — to consider spending a boost on"),
    "sgp": (None, "conviction",
            "the model's strongest plays in this game, one per player — same-game legs are correlated, "
            "so price the combined bet in the app before using it"),
    "info": ([], "", ""),     # shown for context only, no picks
}

# Hand-kept catalog of RECURRING promos, each summarized from public coverage (source named).
# book = the Odds API book key (odds_api.ALL_BOOKS). days = weekdays it is tied to (None = any
# day). Terms change by week and game — the page always says to confirm in the book's app.
PROMO_CATALOG: List[Dict] = [
    {
        "id": "dk_king_of_the_end_zone", "book": "draftkings", "name": "King of the End Zone",
        "sport": "NFL", "kind": "longest_td", "days": None,
        "summary": ("Opt in, then place a $5+ single on a player in the TD Scorers market. The bettor "
                    "whose player scores the LONGEST touchdown of the night shares a bonus-bet pool; "
                    "a less-popular player means a bigger share. Passing TDs don't count (rushing "
                    "and receiving only; defense/special teams can win)."),
        "source": "DraftKings Network / CBS / Oddschecker coverage of the 2025-26 promo",
        "note": "Prize pool, qualifying games and terms change by game — confirm in the DraftKings app.",
    },
    {
        "id": "dk_mnf_sgp_no_sweat", "book": "draftkings", "name": "MNF SGP No Sweat",
        "sport": "NFL", "kind": "sgp", "days": ["Monday"],
        "summary": "Same-game-parlay protection for Monday Night Football.",
        "source": "Legal Sports Report NFL promos roundup (Week 4, 2026)",
        "note": "Stake limits and what you get back vary — confirm in the DraftKings app.",
    },
    {
        "id": "dk_50_boost_gameday", "book": "draftkings", "name": "50% Boost Every Gameday",
        "sport": "NFL", "kind": "boost", "days": None,
        "summary": "A 50% profit boost on select wagers each game day.",
        "source": "Legal Sports Report NFL promos roundup (Week 4, 2026)",
        "note": "Which wagers are eligible varies — confirm in the DraftKings app.",
    },
    {
        "id": "fd_td_jackpot", "book": "fanduel", "name": "TD Jackpot",
        "sport": "NFL", "kind": "first_last_td", "days": ["Thursday"],
        "summary": ("Claim the token, then put $5+ on an Anytime TD Scorer straight bet (no parlays) in "
                    "the featured game. Two pools of $1M in bonus bets: one for bettors whose player "
                    "scores the FIRST TD, one for the LAST. Winners split their pool with everyone who "
                    "picked the same player."),
        "source": "Sports promo coverage of FanDuel's TNF TD Jackpot (2026)",
        "note": "Featured game/night can change — confirm in the FanDuel app.",
    },
    {
        "id": "fd_td_tally_boosts", "book": "fanduel", "name": "Touchdown-tally Profit Boosts",
        "sport": "NFL", "kind": "boost", "days": ["Sunday"],
        "summary": ("Use an Action Token on a $5+ bet (-200 or longer); the more TDs scored across the "
                    "day's NFL games, the more 100% profit boost tokens you earn (30+ TDs = 1, 50+ = 2, "
                    "70+ = 3)."),
        "source": "FanDuel Research promo post for Oct 4, 2026",
        "note": "Thresholds and dates are set per promo — confirm in the FanDuel app.",
    },
    {
        "id": "fd_injury_protection", "book": "fanduel", "name": "Free Full-Game Injury Protection",
        "sport": "NFL", "kind": "info", "days": None,
        "summary": "A player prop leg is voided (not lost) if the player leaves the game early.",
        "source": "Legal Sports Report NFL promos roundup (Week 4, 2026)",
        "note": "Confirm eligible bets in the FanDuel app.",
    },
    {
        "id": "mgm_first_td_boost", "book": "betmgm", "name": "First TD Scorer Boost Token",
        "sport": "NFL", "kind": "first_td", "days": None,
        "summary": "A 20% boost on winnings when your First TD Scorer pick is right.",
        "source": "Legal Sports Report NFL promos roundup (Week 4, 2026)",
        "note": "Token availability and limits vary — confirm in the BetMGM app.",
    },
    {
        "id": "mgm_no_sweat", "book": "betmgm", "name": "Pro Football No Sweat Token",
        "sport": "NFL", "kind": "info", "days": None,
        "summary": "Stake refunded as a bonus bet if the NFL wager loses (odds -300 or longer, $1-$5).",
        "source": "Legal Sports Report NFL promos roundup (Week 4, 2026)",
        "note": "Confirm in the BetMGM app.",
    },
    {
        "id": "b365_early_bird_mnf", "book": "bet365", "name": "Early Bird Special",
        "sport": "NFL", "kind": "sgp", "days": ["Monday"],
        "summary": "A 100% profit boost on a Monday Night Football same-game parlay.",
        "source": "Legal Sports Report NFL promos roundup (Week 4, 2026)",
        "note": "bet365 has no live prop feed here — prices are by hand. Confirm in the bet365 app.",
    },
    {
        "id": "fanatics_survivor", "book": "fanatics", "name": "FanCash Survivor Contest",
        "sport": "NFL", "kind": "info", "days": None,
        "summary": "A free-to-play weekly survivor pick contest with a FanCash prize pool.",
        "source": "Legal Sports Report NFL promos roundup (Week 4, 2026)",
        "note": "Confirm in the Fanatics app.",
    },
]


def applies_on(promo: Dict, date_str: str) -> bool:
    """False only when the promo is tied to specific weekdays and `date_str` isn't one of them."""
    days = promo.get("days")
    if not days:
        return True
    try:
        from datetime import datetime
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A") in days
    except ValueError:
        return True


def catalog_for(sport_key: str, extra: Optional[List[Dict]] = None, book: Optional[str] = None,
                date_str: Optional[str] = None) -> List[Dict]:
    """Catalog (+ owner-added) promos for this sport — narrowed to one book (Odds API book key) and
    to the weekday of `date_str` when given."""
    out = [p for p in (PROMO_CATALOG + list(extra or [])) if p.get("sport") in (sport_key, "ALL")]
    if book:
        out = [p for p in out if p.get("book") == book]
    if date_str:
        out = [p for p in out if applies_on(p, date_str)]
    return out


def make_custom_promo(book: str, name: str, sport: str, kind: str, summary: str = "",
                      days: Optional[List[str]] = None) -> Dict:
    """Validated owner-entered promo. `book` is the Odds API book key (the page passes the selected
    book). Raises ValueError on a blank book/name or unknown kind."""
    book, name = (book or "").strip(), (name or "").strip()
    if not book or not name:
        raise ValueError("A promo needs a sportsbook and a name.")
    if kind not in KINDS:
        raise ValueError(f"Unknown promo kind {kind!r}.")
    return {"id": f"custom:{book}:{name}".lower(), "book": book, "name": name, "sport": sport,
            "kind": kind, "days": days or None, "summary": (summary or "").strip(),
            "source": "added by you", "note": "Owner-entered — confirm terms in the book's app."}


def explosiveness(play: Dict, min_touches: int = 3) -> Optional[float]:
    """Yards per touch (rushing + receiving) over the play's recent game log; None if too few
    touches to say. A proxy for big-play ability — the LONGEST TD tends to come from explosive
    players, not goal-line backs."""
    yds = touches = 0.0
    for g in play.get("_game_log") or []:
        yds += float(g.get("rushing_yards") or 0) + float(g.get("receiving_yards") or 0)
        touches += float(g.get("carries") or 0) + float(g.get("receptions") or 0)
    if touches < min_touches:
        return None
    return yds / touches


def _factor(ypt: Optional[float]) -> float:
    """Explosiveness multiplier: ~4.5 yds/touch is neutral; clipped so it nudges, never dominates."""
    if ypt is None:
        return 1.0
    return min(max(ypt / 4.5, 0.7), 1.6)


def _is_td_kind(kind: Optional[str]) -> bool:
    return KINDS.get(kind, ([], "", ""))[0] not in (None, [])


def promo_picks(plays: List[Dict], promo: Dict, n: int = 3) -> List[Dict]:
    """Top `n` picks for a promo from model plays (already narrowed to the game(s) the caller wants).
    Each: {play, score, rank_basis, tag, ypt, kind}.
      * TD-scorer kinds draw from the TD markets; `tag` is 'chalk' for the 3 most likely scorers in
        the pool (likely the crowd's favorites — a shared pool pays less) else 'leverage'. Popularity
        is NOT measured; that is only a proxy.
      * 'boost' / 'sgp' draw from every non-longshot market (First/Last TD excluded). 'boost' ranks by
        live EV% when plays carry it, else conviction, and prefers plays with a real book price;
        'sgp' ranks by conviction and takes one play per player.
      * 'info' (or an unknown kind) gives []."""
    kind = promo.get("kind")
    if kind not in KINDS or kind == "info":
        return []
    markets, basis, _ = KINDS[kind]
    if _is_td_kind(kind):
        pool = [p for p in plays if p.get("Market") in markets and p.get("ModelProb") is not None]
        if not pool:
            return []
        chalk_ids = {id(p) for p in sorted(pool, key=lambda p: p["ModelProb"], reverse=True)[:3]}
        scored = []
        for p in pool:
            ypt = explosiveness(p) if kind == "longest_td" else None
            score = p["ModelProb"] * (_factor(ypt) if kind == "longest_td" else 1.0)
            scored.append({"play": p, "score": round(score, 4), "rank_basis": basis, "ypt": ypt,
                           "tag": "chalk" if id(p) in chalk_ids else "leverage", "kind": kind})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max(0, n)]

    pool = [p for p in plays if p.get("ModelProb") is not None
            and p.get("Market") not in (FIRST_TD, LAST_TD)]

    def key(p: Dict):
        if kind == "boost":
            priced = p.get("PriceSource") == "book" or p.get("EV") is not None
            return (priced, p["EV"] if p.get("EV") is not None else float("-inf"), p.get("Conviction") or 0)
        return (p.get("Conviction") or 0,)

    out, seen = [], set()
    for p in sorted(pool, key=key, reverse=True):
        if kind == "sgp":
            if p.get("Player") in seen:
                continue
            seen.add(p.get("Player"))
        out.append({"play": p, "score": round(p.get("Conviction") or 0, 4), "rank_basis": basis,
                    "ypt": None, "tag": "", "kind": kind})
        if len(out) >= max(0, n):
            break
    return out


def _price_bit(p: Dict) -> Optional[str]:
    if p.get("PriceSource") == "book" and p.get("RealPrice") is not None:
        book = f" at {p['RealPriceBook']}" if p.get("RealPriceBook") else ""
        return f"{p['RealPrice']:+.0f}{book}"
    if p.get("Fair") is not None:
        return f"fair ~{p['Fair']:+.0f}"
    return None


def pick_line(pick: Dict) -> str:
    """One readable line for a promo pick (TD kinds: chance to score, yards/touch, tag; boost/sgp kinds:
    the market and line, model chance, price, EV)."""
    p = pick["play"]
    if _is_td_kind(pick.get("kind", "longest_td")):
        bits = [f"{p['Player']} ({p.get('Team', '')})", f"model ~{p['ModelProb'] * 100:.0f}% to score"]
        if pick.get("ypt") is not None:
            bits.append(f"{pick['ypt']:.1f} yds/touch recently")
        price = _price_bit(p)
        if price:
            bits.append(price)
        line = " · ".join(bits)
        if pick.get("tag") == "chalk":
            line += " · likely a popular name — a shared pool pays less"
        elif pick.get("tag"):
            line += " · less obvious — more upside if it hits"
        return line
    what = f"{p.get('Market')} {p.get('Side', '')} {p['Line']:g}".strip() if p.get("Line") is not None \
        else f"{p.get('Market')} {p.get('Side', '')}".strip()
    bits = [f"{p['Player']} ({p.get('Team', '')}) — {what}", f"model ~{p['ModelProb'] * 100:.0f}%"]
    price = _price_bit(p)
    if price:
        bits.append(price)
    if p.get("EV") is not None:
        bits.append(f"{p['EV']:+.1f}% EV")
    return " · ".join(bits)


def promo_blurb(promo: Dict, book_label: Optional[str] = None) -> str:
    _, _, how = KINDS.get(promo.get("kind"), ([], "", ""))
    base = f"{book_label or promo['book']} — {promo['name']}: {promo.get('summary') or 'see the book for terms'}"
    return base + (f" (Picks: {how}.)" if how else "")
