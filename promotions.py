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

# kind -> (model markets to draw picks from, how picks are ranked, plain-words explanation)
KINDS = {
    "longest_td": ([ANYTIME_TD], "longest-TD score",
                   "ranked by chance to score a rushing/receiving TD, weighted up for explosive "
                   "players (yards per touch) since the LONGEST TD wins"),
    "anytime_td": ([ANYTIME_TD], "model probability", "ranked by modeled chance to score a TD"),
    "first_td": ([FIRST_TD], "model probability", "ranked by modeled chance to score the first TD"),
    "last_td": ([LAST_TD], "model probability", "ranked by modeled chance to score the last TD"),
    "info": ([], "", ""),     # shown for context only, no picks
}

PROMO_CATALOG: List[Dict] = [
    {
        "id": "dk_king_of_the_end_zone", "book": "DraftKings", "name": "King of the End Zone",
        "sport": "NFL", "kind": "longest_td",
        "summary": ("Opt in, then place a $5+ single on a player in the TD Scorers market. The bettor "
                    "whose player scores the LONGEST touchdown of the night shares a bonus-bet pool; "
                    "a less-popular player means a bigger share. Passing TDs don't count (rushing "
                    "and receiving only; defense/special teams can win)."),
        "source": "DraftKings Network / CBS / Oddschecker coverage of the 2025-26 promo",
        "note": "Prize pool, qualifying games and terms change by game — confirm in the DraftKings app.",
    },
]


def catalog_for(sport_key: str, extra: Optional[List[Dict]] = None) -> List[Dict]:
    """Catalog (+ owner-added) promos that apply to this sport."""
    return [p for p in (PROMO_CATALOG + list(extra or [])) if p.get("sport") in (sport_key, "ALL")]


def make_custom_promo(book: str, name: str, sport: str, kind: str, summary: str = "") -> Dict:
    """Validated owner-entered promo. Raises ValueError on a blank book/name or unknown kind."""
    book, name = (book or "").strip(), (name or "").strip()
    if not book or not name:
        raise ValueError("A promo needs a sportsbook and a name.")
    if kind not in KINDS:
        raise ValueError(f"Unknown promo kind {kind!r}.")
    return {"id": f"custom:{book}:{name}".lower(), "book": book, "name": name, "sport": sport,
            "kind": kind, "summary": (summary or "").strip(), "source": "added by you",
            "note": "Owner-entered — confirm terms in the book's app."}


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


def promo_picks(plays: List[Dict], promo: Dict, n: int = 3) -> List[Dict]:
    """Top `n` picks for a promo from model plays (already narrowed to the game/day the caller
    wants). Each: {play, score, rank_basis, tag, ypt}. `tag` is 'chalk' for the 3 most likely
    scorers in the pool (likely the crowd's favorites — a shared pool pays less) else 'leverage'.
    Popularity is NOT measured; this is only a proxy. Unpriced/unknown kinds give []."""
    markets, basis, _ = KINDS.get(promo.get("kind"), ([], "", ""))
    pool = [p for p in plays if p.get("Market") in markets and p.get("ModelProb") is not None]
    if not pool:
        return []
    by_prob = sorted(pool, key=lambda p: p["ModelProb"], reverse=True)
    chalk_ids = {id(p) for p in by_prob[:3]}
    scored = []
    for p in pool:
        ypt = explosiveness(p) if promo.get("kind") == "longest_td" else None
        score = p["ModelProb"] * (_factor(ypt) if promo.get("kind") == "longest_td" else 1.0)
        scored.append({"play": p, "score": round(score, 4), "rank_basis": basis, "ypt": ypt,
                       "tag": "chalk" if id(p) in chalk_ids else "leverage"})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max(0, n)]


def pick_line(pick: Dict) -> str:
    """One readable line: player, team, model chance, yards/touch (if used), price, tag."""
    p = pick["play"]
    bits = [f"{p['Player']} ({p.get('Team', '')})", f"model ~{p['ModelProb'] * 100:.0f}% to score"]
    if pick.get("ypt") is not None:
        bits.append(f"{pick['ypt']:.1f} yds/touch recently")
    if p.get("PriceSource") == "book" and p.get("RealPrice") is not None:
        book = f" at {p['RealPriceBook']}" if p.get("RealPriceBook") else ""
        bits.append(f"{p['RealPrice']:+.0f}{book}")
    elif p.get("Fair") is not None:
        bits.append(f"fair ~{p['Fair']:+.0f}")
    line = " · ".join(bits)
    if pick["tag"] == "chalk":
        line += " · likely a popular name — a shared pool pays less"
    else:
        line += " · less obvious — more upside if it hits"
    return line


def promo_blurb(promo: Dict) -> str:
    _, _, how = KINDS.get(promo.get("kind"), ([], "", ""))
    base = f"{promo['book']} — {promo['name']}: {promo.get('summary') or 'see the book for terms'}"
    return base + (f" (Picks {how}.)" if how else "")
