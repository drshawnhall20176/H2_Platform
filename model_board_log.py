"""
model_board_log.py -- log a Model Board (no odds) pick to the Bet Log with the price you
actually got.

Why this exists: Edge Board's own logging lives inside the Live edges section, because every
row there carries a real book price (entry_odds), a Kelly stake sized off that price, and a
book name. The Model Board has none of those -- its rows are priced at the model's DEFAULT
line with only a model fair price -- so there was no logging path for it at all. That left out
exactly the plays the Odds API can't price (thin markets, books it doesn't cover), which are
often the ones worth recording most.

The fix keeps the Bet Log honest:
  * entry_odds is the price YOU type in from your book, never silently the model's fair price.
  * entry_odds_source is "manual", a third value next to "book" (captured by the Odds API) and
    "model_fair" (quick_log's fallback). Since Oct 28 betlog.real_price_clv_summary counts "book" AND
    "manual" (a typed price is a real price), and reports how many of each.
  * model_prob is re-evaluated AT THE LINE YOU BET (from the same Monte Carlo distribution the
    board was built from), not left at the default line's probability -- otherwise a bet at a
    different number would be graded against the wrong belief.

Everything here is pure (no Streamlit) so it is unit tested directly.
"""

from typing import Dict, Optional, Tuple

import odds_api as O

# Same discipline defaults Edge Board's Live edges section uses (bet_sizing.apply_stake_discipline).
DEFAULT_SHADE_PTS = 5.0
DEFAULT_KELLY_FRAC = 0.25
DEFAULT_CAP_PCT = 0.05

MANUAL_SOURCE = "manual"


def market_key_for(display_market: str, market_map: Dict[str, str]) -> Optional[str]:
    """Board rows carry the DISPLAY market ("Hits", "Points"); the projection index is keyed by
    the Odds API market key. sports.<sport>.market_map maps display -> key. Accepts a value that
    is already a key, too (some sports' boards pass the key through unchanged)."""
    if not display_market:
        return None
    if display_market in market_map:
        return market_map[display_market]
    if display_market in market_map.values():
        return display_market
    return None


def _over_side(side: str) -> str:
    """"Yes" (e.g. an anytime HR) is the over side of a 0.5 line."""
    s = (side or "").strip().lower()
    return "Over" if s.startswith("o") or s == "yes" else "Under"


def flip_side(side: str) -> str:
    s = (side or "").strip().lower()
    return {"over": "Under", "under": "Over", "yes": "No", "no": "Yes"}.get(s, side)


def _same_line(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < 1e-9


def model_prob_for_bet(row: Dict, index: Dict, projections_module, side: str,
                       line: Optional[float], market_map: Optional[Dict[str, str]] = None
                       ) -> Tuple[Optional[float], str]:
    """The model's probability for the bet you're actually logging. Returns (prob, how) where
    `how` is one of:
      "board"     -- same side and line as the board row: the board's own probability, exactly.
      "repriced"  -- different line and/or side: the board's probability moved by however much
                     the slate's own simulated distribution changes between the two (see below).
      "board_only"-- the player/market isn't in the index, but the bet matches the board row.
      "unavailable" -- not in the index AND the bet differs from the board row: no honest number
                     exists, so None (the Bet Log stores a blank, not a guess).

    Why "moved by" rather than re-reading the raw distribution: MLB's board probability IS the
    raw distribution, but the other sports shrink it toward a baseline by sample size and clip it
    (e.g. nfl_projections.default_board_from_index). Reading the raw number at the new line would
    silently drop that shrinkage and overstate confidence. Shifting the board's own (already
    shrunk) probability by the raw change keeps the same discipline; for MLB it is exactly the raw
    probability at the new line."""
    board_side, board_line = row.get("Side"), row.get("Line")
    board_p = row.get("ModelProb")
    unchanged = side == board_side and _same_line(line, board_line)
    if unchanged and board_p is not None:
        return float(board_p), "board"

    mkey = row.get("MarketKey") or market_key_for(row.get("Market"), market_map or {})
    entry = None
    if index and row.get("Player") and mkey:
        entry = index.get((projections_module.normalize_name(row["Player"]), mkey))
    if entry is None or entry.get("dist") is None or board_p is None:
        return (float(board_p), "board_only") if (unchanged and board_p is not None) else (None, "unavailable")

    dist = entry["dist"]
    eval_board = 0.5 if board_line is None else float(board_line)
    eval_user = 0.5 if line is None else float(line)
    want = _over_side(side)
    board_p_want = float(board_p) if _over_side(board_side) == want else 1.0 - float(board_p)
    raw_board = float(projections_module.prob_for_side(dist, eval_board, want))
    raw_user = float(projections_module.prob_for_side(dist, eval_user, want))
    return min(0.99, max(0.01, board_p_want + (raw_user - raw_board))), "repriced"


def suggested_stake(prob: Optional[float], american: Optional[float], bankroll: Optional[float],
                    shade_pts: float = DEFAULT_SHADE_PTS, kelly_frac: float = DEFAULT_KELLY_FRAC,
                    cap_pct: float = DEFAULT_CAP_PCT) -> float:
    """Quarter-Kelly on the SHADED probability, capped -- identical math to Live edges, so a pick
    sized here matches what the Edge Board would have recommended at that price. 0.0 when there
    is no edge after shading, or inputs are missing."""
    if prob is None or american is None or not bankroll or bankroll <= 0:
        return 0.0
    shaded = max(0.0, float(prob) - shade_pts / 100.0)
    return O.kelly_stake(shaded, float(american), float(bankroll), kelly_frac, cap_pct)


def ev_at_price(prob: Optional[float], american: Optional[float]) -> Optional[float]:
    if prob is None or american is None:
        return None
    return round(O.ev_percent(float(prob), float(american)), 2)


def build_bet_fields(row: Dict, *, date_str: str, sport_key: str, side: str,
                     line: Optional[float], entry_odds: int, stake: float, book: str,
                     model_prob: Optional[float], notes: str = "") -> Dict:
    """Exact kwargs for betlog.add_bet. Pass model_prob from model_prob_for_bet; a None there is
    stored as a blank, never back-filled with the board's number for a different bet."""
    return {
        "slate_date": date_str,
        "game": row.get("Game"),
        "player": row.get("Player"),
        "player_id": row.get("PlayerId"),
        "market": row.get("Market"),
        "side": side,
        "line": None if line is None else float(line),
        "entry_odds": int(entry_odds),
        "entry_odds_source": MANUAL_SOURCE,
        "model_prob": None if model_prob is None else round(float(model_prob), 4),
        "stake": round(float(stake or 0.0), 2),
        "book": book,
        "notes": notes or None,
        "sport": sport_key,
    }


def signature(fields: Dict) -> tuple:
    """Session dedup key -- same shape Edge Board's Live edges logging uses."""
    return (fields["slate_date"], fields["player"], fields["market"], fields["side"],
            fields["line"], fields["entry_odds"])
