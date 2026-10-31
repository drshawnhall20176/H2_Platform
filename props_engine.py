"""
props_engine.py — the shared modelling core behind Position Matchups' Player props tabs (basketball, football,
hockey). PURE LOGIC, NO NETWORK: the sport modules (player_props.py, football_props.py, hockey_props.py) decide
WHAT a player's opportunity and rate are; this module supplies the pieces every sport shares.

What lives here, and the order a projection is built in:

  1. RECENCY. Form is a weighted average of the last 10 games, newest weighted most (half-life 4 games), instead of
     a flat last-5 average -- recent role changes show up sooner, one old outlier fades out.
  2. OPPORTUNITY FIRST. A projection is RATE x OPPORTUNITY (minutes, targets/carries, ice time). `redistribute`
     moves a player's opportunity to his teammates when he's ruled out -- the basketball/hockey version of the
     football "next man up" -- and only for a FRESH absence (he played in the team's last games); a player who has
     already been out a while is baked into everyone's recent numbers and would be double counted.
  3. CONTEXT. `rest_effect` (back-to-backs, extra rest, a tired opponent) and `blowout_effect` (big spreads bench
     starters late) adjust opportunity and rate.
  4. THE MARKET AS A STARTING POINT. `implied_team_totals` turns a game's spread and total into what each team is
     expected to score; `env_multiplier` scales a player's projection by that against his team's normal output.
     `shop` reads the books' posted lines (best price per side and the no-vig consensus probability), and
     `blend` mixes the model's probability with that consensus -- the market is usually right, so the model only
     gets MODEL_WEIGHT of the vote and a lean needs a real edge at the price you can actually get.
  5. HONEST PROBABILITIES. Points-style totals use a normal curve; low counts (blocks, steals, receptions, shots,
     goals) use a negative binomial (Poisson when a player is very steady) -- P(1+ blocks) is not a normal-curve
     question. `calibrate` shrinks probabilities toward 50% by the slope the Scorecard measured.
  6. SAME-GAME PARLAYS. `sgp` prices a set of legs with correlation (via slip_sim's Gaussian copula) instead of
     multiplying them as if they were independent.

Every constant below is a STARTING POINT -- the Scorecard tab exists so they can be checked against real results.
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- constants
HALF_LIFE = 4.0              # games: a game 4 back counts half as much as the newest
FORM_WINDOW = 10             # games of form used for rates and spread
MODEL_WEIGHT = 0.40          # the model's share of the vote when a market price exists (the market gets the rest)
MIN_EV = 0.03                # a lean at a real price needs +3% expected value at that price
LEAN_EDGE = 0.05             # no price: the projection must clear the line by 5% ...
LEAN_P = 0.55                # ... and the probability agree (55%+), roughly +5% EV at -110
ASSUMED_VIG = 0.045          # a single posted price with no other side: assume a normal two-way margin
ENV_RANGE = (0.88, 1.12)     # how far a game environment (implied team total vs normal) may move a projection
REDISTRIBUTE_SAME_SLOT = 0.6 # share of an absent player's minutes that goes to his own position group
USAGE_GAP_FILL = 0.5         # share of his remaining lost production picked up by teammates' higher usage
USAGE_RATE_CAP = 0.10        # nobody's per-minute rate goes up more than 10% from one absence set
# Toned down Oct 28: the books disagreed with most "next man up" bumps (Jay Huff form 7.6 -> projection 14.4,
# Terrence Shannon 14.2 -> 20.5). Coaches don't hand an absent starter's minutes out in proportion -- some go
# to the end of the bench, some to a lineup change -- so only part of them reaches the rotation, and no one
# player's minutes jump by more than this. The Scorecard tab checks these against results.
REDISTRIBUTE_SHARE = 0.75    # share of an absent player's minutes (TOI...) that reaches the rotation we model
# Oct 31: ...but the TOP remaining scorers are the exception. With a star freshly out, Unders on the players who take
# over his shots went 0-8 on Oct 29-30 (Bane x3 and F. Wagner with Suggs out; LaMelo x2 and McDaniels x2 with Edwards
# out) while the bench bumps held up. So the top PRIMARY_N by production get a bigger share of the missing usage and a
# higher rate cap, and an Under on them asks for a news check (props_engine.leg_warnings / player_props).
PRIMARY_N = 2
PRIMARY_USAGE_WEIGHT = 2.0   # a primary's share of the leftover usage counts double
USAGE_RATE_CAP_PRIMARY = 0.20
BUMP_MAX_FRAC = 0.35         # a teammate's minutes go up at most 35% of his own ...
BUMP_MAX_ABS = 8.0           # ... and at most 8 (minutes / TOI minutes)
FRESH_OUT_GAMES = 3          # an absence is "fresh" when he played in at least 2 of the team's last 3 games
BLOWOUT_SPREAD = 10.0        # basketball: spreads this big start to cost starters late minutes
CALIBRATION_RANGE = (0.3, 1.3)
# MARKET DISAGREEMENT. When the projection sits this far from a book's posted line -- at least GAP_PCT of the line
# AND at least GAP_Z of the player's own game-to-game spread -- the books almost always know something the box
# scores don't (a minutes cap, a role change, a returning starter, an injury not yet on the report). Such a row
# is flagged, the model's share of the probability drops to GAP_MODEL_WEIGHT, and it gets no lean until someone
# has checked the news ("news_checked"). Bets logged on it are tagged "market-gap" so the Scorecard can say, over
# time, who was right on these -- the model or the market.
GAP_PCT = 0.20
GAP_Z = 1.0
GAP_PCT_OUTRIGHT = 0.25
# A lean the player's own recent results flatly contradict isn't one: Over when he's cleared the line in a quarter
# or fewer of his recent games (Under when he's cleared it in three quarters or more) -- one big night shouldn't
# drag the average over a line he usually misses.
HIT_CONFLICT = 0.25
# LOW-COUNT MARKETS (a count line under LOW_COUNT_LINE: rebounds 2.5, assists 3.5, steals, blocks, threes): a gap of
# a rebound or two looks enormous in percent but rarely means hidden news -- minutes and role news shows up in the
# points and combo lines. So a big gap here still hands the market 80% of the vote, but asks for LOW_COUNT_MIN_EV
# value instead of a news check. (A player who missed his team's last game is still gated, separately.)
LOW_COUNT_LINE = 5.0
LOW_COUNT_MIN_EV = 0.06
HIT_CONFLICT_MIN_GAMES = 4
GAP_MODEL_WEIGHT = 0.20
GAP_TAG = "market-gap"
STAR_OUT_TAG = "star-out"    # Oct 31: a teammate freshly out moved this player's projection (bump or top option)


def is_star_out(row: Dict) -> bool:
    """Did a fresh teammate absence move this row -- a usage bump, or a top option absorbing a missing star?"""
    return bool(row.get("absorbs")) or any(str(f).startswith("↑ usage bump") for f in row.get("flags") or [])

_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}


def num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) or math.isinf(v) else v


def maybe(x) -> Optional[float]:
    """A float or None (blank / NaN / text)."""
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def norm_name(name) -> str:
    words = re.sub(r"[^a-z0-9 ]+", "", str(name or "").lower().replace(".", "").replace("'", "")).split()
    while words and words[-1] in _SUFFIX:
        words.pop()
    return " ".join(words)


# --------------------------------------------------------------------------- 1. recency
def recency_weights(n: int, half_life: float = HALF_LIFE) -> List[float]:
    """Weights for n values listed NEWEST FIRST."""
    return [0.5 ** (i / half_life) for i in range(n)]


def wmean(values: Sequence[float], weights: Optional[Sequence[float]] = None) -> Optional[float]:
    vals = list(values)
    if not vals:
        return None
    w = list(weights) if weights is not None else recency_weights(len(vals))
    tot = sum(w[: len(vals)])
    return sum(v * x for v, x in zip(vals, w)) / tot if tot else None


def wvar(values: Sequence[float]) -> Optional[float]:
    """Recency-weighted variance (newest first), with the usual small-sample correction."""
    vals = list(values)
    if len(vals) < 2:
        return None
    w = recency_weights(len(vals))
    m = wmean(vals, w)
    v1, v2 = sum(w), sum(x * x for x in w)
    denom = v1 - v2 / v1
    return sum(x * (v - m) ** 2 for v, x in zip(vals, w)) / denom if denom > 0 else None


def rate_and_opportunity(values: Sequence[float], opps: Sequence[float],
                         game_weights: Optional[Sequence[float]] = None) -> Tuple[Optional[float], Optional[float]]:
    """(production per unit of opportunity, projected opportunity), both recency weighted, newest first.
    Games with no opportunity (a DNP) are skipped. `game_weights` (one per game, e.g. form_policy.weights)
    replaces the plain recency weights."""
    triples = [(v, o, (game_weights[i] if game_weights is not None else None))
               for i, (v, o) in enumerate(zip(values, opps)) if o > 0]
    pairs = [(v, o) for v, o, _ in triples]
    if not pairs:
        return None, None
    w = [t[2] for t in triples] if game_weights is not None else recency_weights(len(pairs))
    tot_o = sum(x * o for (_, o), x in zip(pairs, w))
    rate = sum(x * v for (v, _), x in zip(pairs, w)) / tot_o if tot_o else None
    return rate, wmean([o for _, o in pairs], w)


# --------------------------------------------------------------------------- 5. distributions
def threshold(line: float) -> float:
    """A whole-number line is an alt "N+" ladder line (cleared at N, continuity point N - 0.5); a half line is
    cleared above it."""
    line = float(line)
    return line - 0.5 if line == int(line) else line


def clears(value: float, line: float) -> bool:
    return value > threshold(line)


def k_needed(line: float) -> int:
    """The whole count that clears a line: 1.5 -> 2, an alt 2+ line -> 2, 0.5 -> 1."""
    return int(math.floor(threshold(line))) + 1


def normal_sf(mean: float, sd: float, x: float) -> float:
    if sd <= 0:
        return 1.0 if mean > x else 0.0
    return 0.5 * (1 - math.erf((x - mean) / (sd * math.sqrt(2))))


def count_sf(mean: float, var: Optional[float], k: int) -> float:
    """P(X >= k) for a count with this mean: negative binomial when the spread is wider than the mean
    (most player counts), Poisson otherwise."""
    if k <= 0:
        return 1.0
    if mean <= 0:
        return 0.0
    var = mean if var is None else max(var, mean)
    if var <= mean * 1.0001:
        pmf = math.exp(-mean)
        cdf = pmf
        for x in range(1, k):
            pmf *= mean / x
            cdf += pmf
    else:
        r = mean * mean / (var - mean)
        p = r / (r + mean)
        pmf = math.exp(r * math.log(p))
        cdf = pmf
        for x in range(0, k - 1):
            pmf *= (x + r) / (x + 1) * (1 - p)
            cdf += pmf
    return max(0.0, min(1.0, 1.0 - cdf))


def prob_over(projection: Optional[float], values: Sequence[float], line: Optional[float],
              dist: str = "normal", sd_floor_frac: float = 0.25, sd_floor_abs: float = 1.0) -> Optional[float]:
    """P(stat clears line). "normal": around the projection with the player's own (recency-weighted) spread,
    floored so a short sample can't claim certainty. "count": negative binomial around the projection, its
    variance taken from the player's games and pulled toward a typical over-dispersion while the sample is short."""
    if line is None or projection is None:
        return None
    vals = list(values)
    if dist == "count":
        n = len(vals)
        sample = wvar(vals)
        typical = projection * 1.25
        var = typical if sample is None else (sample * n + typical * 5) / (n + 5)
        p = count_sf(max(projection, 0.0), max(var, projection), k_needed(line))
    else:
        sd = math.sqrt(wvar(vals) or 0.0)
        sd = max(sd, sd_floor_frac * max(projection, 1.0), sd_floor_abs)
        p = normal_sf(projection, sd, threshold(line))
    return max(0.01, min(0.99, p))


# --------------------------------------------------------------------------- 4. prices, the market, the blend
def implied(american) -> Optional[float]:
    a = maybe(american)
    if a is None or a == 0 or -100 < a < 100:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def decimal(american) -> Optional[float]:
    a = maybe(american)
    if a is None or a == 0 or -100 < a < 100:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def american(p: Optional[float]) -> Optional[int]:
    if p is None or p <= 0 or p >= 1:
        return None
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def devig(over, under) -> Optional[float]:
    """No-vig P(over) from a two-way price."""
    a, b = implied(over), implied(under)
    if a is None or b is None or a + b <= 0:
        return None
    return a / (a + b)


def market_prob(over=None, under=None) -> Optional[float]:
    """P(over) the prices imply: no-vig from both sides, or one side with a normal margin taken off."""
    p = devig(over, under)
    if p is not None:
        return p
    if implied(over) is not None:
        return min(0.99, implied(over) / (1 + ASSUMED_VIG))
    if implied(under) is not None:
        return max(0.01, 1 - implied(under) / (1 + ASSUMED_VIG))
    return None


def blend(p_model: Optional[float], p_market: Optional[float], w: float = MODEL_WEIGHT) -> Optional[float]:
    if p_model is None:
        return p_market
    if p_market is None:
        return p_model
    return w * p_model + (1 - w) * p_market


def ev(p: Optional[float], price) -> Optional[float]:
    d = decimal(price)
    return None if (p is None or d is None) else p * d - 1


def calibrate(p: Optional[float], slope: float = 1.0) -> Optional[float]:
    """Shrink (slope < 1) or stretch a probability around 50% -- the Scorecard's fitted correction."""
    if p is None:
        return None
    lo, hi = CALIBRATION_RANGE
    s = min(hi, max(lo, slope))
    return max(0.01, min(0.99, 0.5 + (p - 0.5) * s))


def best_price(prices: Dict[str, float]) -> Optional[Tuple[str, float]]:
    good = [(b, p) for b, p in (prices or {}).items() if decimal(p) is not None]
    if not good:
        return None
    return max(good, key=lambda bp: decimal(bp[1]))


def offers_for(offers: Iterable[Dict], player: str, market_key: str) -> List[Dict]:
    want = norm_name(player)
    return [o for o in offers or [] if o.get("market") == market_key and norm_name(o.get("player")) == want]


def _book_count(o: Dict) -> int:
    return len(set(o.get("over") or {}) | set(o.get("under") or {}))


PICKEM_BOOKS = ("prizepicks", "pick6")        # = odds_api.PICKEM_BOOKS: a line and a payout multiplier, no odds
BOOK_PRIORITY = ("draftkings", "fanduel")      # Oct 29: your book first, then the next one that posts the player


def book_order(selected) -> Optional[List[str]]:
    """The books to try, in order, for a "Price at" choice: None / "best" -> no preference (best price anywhere);
    "priority" -> BOOK_PRIORITY; a sportsbook -> it, then the rest of BOOK_PRIORITY; a pick'em app -> only it."""
    if selected in (None, "best"):
        return None
    if selected == "priority":
        return list(BOOK_PRIORITY)
    if isinstance(selected, (list, tuple)):
        return [b for b in selected if b]
    if selected in PICKEM_BOOKS:
        return [selected]
    return [selected] + [b for b in BOOK_PRIORITY if b != selected]


def shop(player_offers: Sequence[Dict], line: Optional[float] = None, book=None) -> Optional[Dict]:
    """The books' read on one player market. Without `line`: the MAIN line (posted by the most books, then the
    most balanced). With `line`: that exact line, or None when no book posts it.

    `book`: a book key ("draftkings"), an ORDER of books (["draftkings", "fanduel"] -- see book_order), or None
    for the best price anywhere. The line and prices come from the first book in the order that posts the
    player (its most balanced line when it posts several); when none does, the consensus line at the best
    price anywhere, with "missing_book": True. A pick'em app ("pick6", "prizepicks") gives its LINE and no odds
    ("pickem": True) -- it pays a multiplier per entry, not a price per pick. The no-vig probability is always
    the sportsbooks' consensus at that line.

    {"line", "best_over": (book, price) | None, "best_under": ..., "p_market", "books": count, "book": the book
     used | None, "wanted": your first choice | None, "missing_book": bool, "pickem": bool}"""
    pool = list(player_offers or [])
    if line is not None:
        pool = [o for o in pool if maybe(o.get("point")) is not None and abs(float(o["point"]) - float(line)) < 1e-9]
    if not pool:
        return None
    prefs = book_order(book) if not isinstance(book, (list, tuple)) else [b for b in book if b]
    prefs = prefs or []

    def balance(o, only=None):
        ov, un = o.get("over") or {}, o.get("under") or {}
        if only:
            ov, un = {k: v for k, v in ov.items() if k == only}, {k: v for k, v in un.items() if k == only}
        bo_, bu_ = best_price(ov), best_price(un)
        p = market_prob(bo_[1] if bo_ else None, bu_[1] if bu_ else None)
        return -abs((p if p is not None else 0.0) - 0.5)

    def consensus(o):
        over, under = o.get("over") or {}, o.get("under") or {}
        per_book = [devig(over[b], under[b]) for b in set(over) & set(under)]
        per_book = [p for p in per_book if p is not None]
        if per_book:
            return sum(per_book) / len(per_book)
        b_o, b_u = best_price(over), best_price(under)
        return market_prob(b_o[1] if b_o else None, b_u[1] if b_u else None)

    wanted = prefs[0] if prefs else None
    for i, b in enumerate(prefs):
        if b in PICKEM_BOOKS:
            at = [o for o in pool if b in (o.get("pickem") or {})]
            if at:
                o = max(at, key=lambda x: (_book_count(x), balance(x)))
                return {"line": float(o["point"]), "best_over": None, "best_under": None, "p_market": consensus(o),
                        "books": _book_count(o), "book": b, "wanted": wanted, "missing_book": i > 0, "pickem": True}
            continue
        at = [o for o in pool if b in (o.get("over") or {}) or b in (o.get("under") or {})]
        if at:
            o = max(at, key=lambda x: balance(x, b))
            over, under = o.get("over") or {}, o.get("under") or {}
            return {"line": float(o["point"]), "best_over": (b, over[b]) if b in over else None,
                    "best_under": (b, under[b]) if b in under else None, "p_market": consensus(o),
                    "books": _book_count(o), "book": b, "wanted": wanted, "missing_book": i > 0, "pickem": False}
    priced = [o for o in pool if o.get("over") or o.get("under")]
    o = max(priced or pool, key=lambda x: (_book_count(x), balance(x)))
    over, under = o.get("over") or {}, o.get("under") or {}
    return {"line": float(o["point"]), "best_over": best_price(over), "best_under": best_price(under),
            "p_market": consensus(o), "books": _book_count(o), "book": None if prefs else None, "wanted": wanted,
            "missing_book": bool(prefs), "pickem": False}


# --------------------------------------------------------------------------- 4b. the game environment
def implied_team_totals(total: Optional[float], spread_home: Optional[float]) -> Optional[Tuple[float, float]]:
    """(home, away) expected points from the game total and the HOME spread (negative = home favored)."""
    t = maybe(total)
    if t is None or t <= 0:
        return None
    s = maybe(spread_home) or 0.0
    home = t / 2 - s / 2
    return home, t - home


def env_factor(implied_total: Optional[float], baseline: Optional[float]) -> Optional[float]:
    """Implied team total vs the team's normal output, clipped to ENV_RANGE (None when either is unknown)."""
    if not implied_total or not baseline:
        return None
    lo, hi = ENV_RANGE
    return min(hi, max(lo, implied_total / baseline))


def env_multiplier(factor: Optional[float], shares: Dict[str, float], weights: Dict[str, float]) -> float:
    """How much a game environment moves one market for one player: each stat in the market moves by its own
    sensitivity (points fully, rebounds a little), weighted by that stat's share of his production."""
    if factor is None:
        return 1.0
    tot = sum(shares.values())
    if tot <= 0:
        return 1.0 + weights.get("_default", 1.0) * (factor - 1)
    return 1.0 + sum((s / tot) * weights.get(k, weights.get("_default", 1.0)) * (factor - 1)
                     for k, s in shares.items())


# --------------------------------------------------------------------------- 3. rest + blowouts
def rest_effect(rest_days: Optional[int], opp_rest_days: Optional[int], avg_opp: float, family: str,
                role: str = "skater") -> Dict:
    """Opportunity / rate multipliers and flags from schedule rest. rest_days is days since the last game
    (1 = second night of a back-to-back). Unknown rest changes nothing.

    basketball: second night -> heavy-minute players (30+) lose ~3% of their minutes (coaches trim, some sit)
    and everyone's efficiency dips ~2%; three or more days off -> +1%; the OPPONENT on a back-to-back -> +1.5%
    (tired legs on defense). hockey: second night -> skaters -3%, and a goalie who played last night is flagged
    (teams usually start the backup). football: weekly, no effect."""
    out = {"opp_mult": 1.0, "rate_mult": 1.0, "flags": []}
    if family == "football":
        return out
    b2b = rest_days is not None and rest_days <= 1
    if family == "basketball":
        if b2b:
            out["rate_mult"] *= 0.98
            if avg_opp >= 30:
                out["opp_mult"] *= 0.97
                out["flags"].append("B2B: rest risk")
            else:
                out["flags"].append("B2B")
        elif rest_days is not None and rest_days >= 3:
            out["rate_mult"] *= 1.01
        if opp_rest_days is not None and opp_rest_days <= 1:
            out["rate_mult"] *= 1.015
            out["flags"].append("Opp on B2B")
    elif family == "hockey":
        if b2b:
            if role == "goalie":
                out["flags"].append("B2B: backup goalie likely")
            else:
                out["rate_mult"] *= 0.97
                out["flags"].append("B2B")
        if opp_rest_days is not None and opp_rest_days <= 1:
            out["rate_mult"] *= 1.02
            out["flags"].append("Opp on B2B")
    return out


def blowout_effect(spread_for_team: Optional[float], avg_opp: float, family: str = "basketball") -> Dict:
    """Big spreads cost starters fourth-quarter minutes (both sides: the winner rests, the loser waves the
    towel) and give the bench garbage time. Basketball only; football's game script is handled in
    football_props (pass/run mix), hockey has no equivalent."""
    out = {"opp_mult": 1.0, "flags": []}
    s = maybe(spread_for_team)
    if family != "basketball" or s is None or abs(s) < BLOWOUT_SPREAD:
        return out
    cut = min(0.08, 0.01 * (abs(s) - BLOWOUT_SPREAD + 2))
    if avg_opp >= 28:
        out["opp_mult"] = 1 - cut
        out["flags"].append(f"Blowout risk ({s:+.1f})")
    elif avg_opp < 20:
        out["opp_mult"] = 1 + cut / 2
        out["flags"].append("Garbage-time boost")
    return out


# --------------------------------------------------------------------------- 2. next man up (opportunity)
def fresh_absence(player_games: Sequence[str], team_recent_games: Sequence[str], need: int = 2) -> bool:
    """True when the player was part of the team's last FRESH_OUT_GAMES games (played `need` of them) -- his
    absence is news the recent numbers don't already contain."""
    recent = list(team_recent_games)[:FRESH_OUT_GAMES]
    return sum(1 for g in recent if g in set(player_games)) >= min(need, len(recent)) if recent else False


def redistribute(players: Sequence[Dict], cap: float = 40.0, primary_n: int = 0) -> Dict:
    """Spread FRESH absences' opportunity to the teammates still playing.

    players: [{"pid","name","slot","opp" (minutes / TOI / ...), "rate" (production per unit), "out", "fresh"}].
    Returns {pid: {"opp_add", "rate_mult", "from": [names]}} for the healthy players. An absent player's
    opportunity (REDISTRIBUTE_SHARE of it) goes REDISTRIBUTE_SAME_SLOT to his own position group (by their
    opportunity) and the rest to everyone (capped at `cap`, and no one gains more than BUMP_MAX_FRAC of his own
    or BUMP_MAX_ABS); whatever production that doesn't replace, teammates make up USAGE_GAP_FILL of
    through a higher rate (more shots / touches), spread by current production and capped at USAGE_RATE_CAP.
    With `primary_n`, the top primary_n healthy players by production are the team's primary options: their share
    of that leftover usage is weighted PRIMARY_USAGE_WEIGHT, their cap is USAGE_RATE_CAP_PRIMARY, and their entry
    carries "primary": True (an Under on them then asks for a news check)."""
    live = [p for p in players if not p.get("out") and num(p.get("opp")) > 0]
    res = {p["pid"]: {"opp_add": 0.0, "rate_mult": 1.0, "from": []} for p in live}
    absent = [p for p in players if p.get("out") and p.get("fresh") and num(p.get("opp")) > 0]
    if not live or not absent:
        return res
    gap = 0.0
    for a in absent:
        m = num(a["opp"])
        lost = m * num(a.get("rate"))
        same = [p for p in live if p.get("slot") == a.get("slot")]
        pools = [(same, REDISTRIBUTE_SAME_SLOT), (live, 1 - REDISTRIBUTE_SAME_SLOT)] if same else [(live, 1.0)]
        recovered = 0.0
        for pool, share in pools:
            tot = sum(num(p["opp"]) for p in pool)
            for p in pool:
                r = res[p["pid"]]
                gain_cap = min(BUMP_MAX_ABS, BUMP_MAX_FRAC * num(p["opp"]))
                room = max(0.0, min(cap - num(p["opp"]), gain_cap) - r["opp_add"])
                add = min(room, m * REDISTRIBUTE_SHARE * share * num(p["opp"]) / tot) if tot else 0.0
                r["opp_add"] += add
                recovered += add * num(p.get("rate"))
                if add > 0.05 and a.get("name") not in r["from"]:
                    r["from"].append(a.get("name"))
        gap += max(0.0, lost - recovered)
    prod = {p["pid"]: (num(p["opp"]) + res[p["pid"]]["opp_add"]) * num(p.get("rate")) for p in live}
    primary = set(sorted((pid for pid in prod if prod[pid] > 0), key=lambda pid: -prod[pid])[:primary_n])
    for pid in primary:
        res[pid]["primary"] = True
    weight = {pid: prod[pid] * (PRIMARY_USAGE_WEIGHT if pid in primary else 1.0) for pid in prod}
    tot_prod = sum(weight.values())
    if gap > 0 and tot_prod > 0:
        for p in live:
            share = weight[p["pid"]] / tot_prod
            rcap = USAGE_RATE_CAP_PRIMARY if p["pid"] in primary else USAGE_RATE_CAP
            bump = min(rcap, USAGE_GAP_FILL * gap * share / prod[p["pid"]]) if prod[p["pid"]] else 0.0
            res[p["pid"]]["rate_mult"] = 1 + bump
            if bump > 0.005:
                for a in absent:
                    if a.get("name") not in res[p["pid"]]["from"]:
                        res[p["pid"]]["from"].append(a.get("name"))
    return res


# --------------------------------------------------------------------------- the read on one line
def read_line(projection: Optional[float], values: Sequence[float], line: Optional[float], dist: str,
              over_price=None, under_price=None, p_market: Optional[float] = None, slope: float = 1.0,
              model_weight: float = MODEL_WEIGHT, sd_floor_frac: float = 0.25, sd_floor_abs: float = 1.0,
              news_checked: bool = False) -> Dict:
    """Everything the table shows for one line: model probability (calibrated), the market's, the blend,
    the side worth betting and its EV at the price you'd get. Prices are American odds (None when unknown).

    Lean rules: with a price, the side must show MIN_EV+ at that price AND the projection must sit on that side
    of the line (the model and the blend agree). Without a price: projection 5%+ past the line and the
    model's probability 55%+ (about +5% at -110)."""
    out = {"p_model": None, "p_market": None, "p_final": None, "side": None, "price": None, "ev": None,
           "lean": "—", "gap": None, "gap_pct": None}
    if projection is None or line is None:
        return out
    p_model = calibrate(prob_over(projection, values, line, dist, sd_floor_frac, sd_floor_abs), slope)
    p_mkt = p_market if p_market is not None else (market_prob(over_price, under_price)
                                                  if (over_price is not None or under_price is not None) else None)
    thr = threshold(line)
    above = projection > thr
    if p_mkt is not None and thr > 0:
        g = market_gap(projection, values, line, dist, sd_floor_frac, sd_floor_abs)
        out.update(gap_pct=g["pct"], gap=g["level"])
        if g["level"] == "big":
            model_weight = min(model_weight, GAP_MODEL_WEIGHT)
    p = blend(p_model, p_mkt, model_weight)
    out.update(p_model=p_model, p_market=p_mkt, p_final=p)
    if over_price is not None or under_price is not None:
        ev_o, ev_u = ev(p, over_price), ev(1 - p if p is not None else None, under_price)
        cands = [(e, s, pr) for e, s, pr in ((ev_o, "Over", over_price), (ev_u, "Under", under_price))
                 if e is not None]
        if cands:
            e, side, price = max(cands)
            out.update(side=side, price=price, ev=e)
            agrees = above if side == "Over" else not above
            low_count = dist == "count" and thr < LOW_COUNT_LINE
            need = LOW_COUNT_MIN_EV if (out["gap"] == "big" and low_count) else MIN_EV
            out["lean"] = side if (e >= need and agrees and not _hit_conflict(values, line, side)) else "No lean"
            if out["gap"] == "big" and low_count:
                out["gap"] = "big-low-count"          # listed, market-weighted, but no news check
            if out["gap"] == "big" and not news_checked and out["lean"] in ("Over", "Under"):
                out["lean"] = "Check news"
            return out
    edge = (projection - thr) / thr if thr > 0 else 0.0
    side = "Over" if above else "Under"
    out["side"] = side
    out["ev"] = None          # no real price (none typed, or only a pick'em app posts this line): no edge to show
    if edge >= LEAN_EDGE and p >= LEAN_P and not _hit_conflict(values, line, "Over"):
        out["lean"] = "Over"
    elif edge <= -LEAN_EDGE and p <= 1 - LEAN_P and not _hit_conflict(values, line, "Under"):
        out["lean"] = "Under"
    else:
        out["lean"] = "No lean"
    return out


def _hit_conflict(values: Sequence[float], line: float, side: str) -> bool:
    vals = list(values)
    if len(vals) < HIT_CONFLICT_MIN_GAMES:
        return False
    rate = sum(1 for v in vals if clears(v, line)) / len(vals)
    return rate <= HIT_CONFLICT if side == "Over" else rate >= 1 - HIT_CONFLICT


def market_gap(projection: float, values: Sequence[float], line: float, dist: str = "normal",
               sd_floor_frac: float = 0.25, sd_floor_abs: float = 1.0) -> Dict:
    """How far the model's projection is from the book's line: {"pct" (share of the line), "z" (in the player's
    own game-to-game spreads), "level": "agree" | "lean" | "big"}."""
    thr = threshold(line)
    v = wvar(list(values))
    if dist == "count":
        sd = math.sqrt(max(v if v is not None else projection, projection, 0.25))
    else:
        sd = max(math.sqrt(v or 0.0), sd_floor_frac * max(projection, 1.0), sd_floor_abs)
    pct = (projection - thr) / thr if thr > 0 else 0.0
    z = (projection - thr) / sd if sd > 0 else 0.0
    # Big when the line is a quarter or more off the projection outright, or a fifth off AND outside his usual
    # game-to-game swing. (The outright rule stops high-variance combos -- PRA, PR -- slipping under the z test.)
    level = ("big" if (abs(pct) >= GAP_PCT_OUTRIGHT or (abs(pct) >= GAP_PCT and abs(z) >= GAP_Z))
             else ("lean" if abs(z) >= 0.5 else "agree"))
    return {"pct": pct, "z": z, "level": level}


# --------------------------------------------------------------------------- shared table + logging
LEAN_ICON = {"Over": "🟢 Over", "Under": "🔴 Under", "No lean": "⚪ No lean", "Check news": "⚠️ Check news"}


def display(rows: Sequence[Dict], opp_label: str = "Min") -> List[Dict]:
    """Rows -> table strings. 'Line', 'Over odds' and 'Under odds' stay numeric: they're the editable columns."""
    out = []
    for r in rows:
        status = f" 🚫 {r['status']}" if r.get("out") else (f" ⚠️ {r['status']}" if r.get("status") else "")
        flags = list(r.get("flags") or [])
        best = r.get("book") or {}
        bo, bu = best.get("best_over"), best.get("best_under")
        out.append({
            "Player": f"{r['player']}{status}",
            "Pos": r.get("slot") or "",
            opp_label: "—" if r.get("opp") is None else (f"{r['opp']:.0f}" if r["opp"] >= 10 else f"{r['opp']:.1f}"),
            "Form": "—" if r.get("form") is None else
                    f"{r['form']:.1f} ({r['games']} g{', incl. last season' if r.get('filled') else ''})",
            "Matchup": "—" if r.get("factor") is None else f"{r['factor'] - 1:+.0%}",
            "Game env": "—" if r.get("env", 1.0) in (None, 1.0) else f"{r['env'] - 1:+.0%}",
            "Projection": "—" if r.get("projection") is None else f"{r['projection']:.1f}",
            "Line": r.get("line"),
            "Over odds": r.get("over_price"),
            "Under odds": r.get("under_price"),
            "Best price": ("—" if not (bo or bu) else
                           " / ".join(x for x in (f"O {bo[1]:+.0f} {bo[0]}" if bo else "",
                                                  f"U {bu[1]:+.0f} {bu[0]}" if bu else "") if x)),
            "Hit rate": "—" if not r.get("hit") else f"{r['hit'][0]}/{r['hit'][1]}",
            "P(over)": "—" if r.get("p_final") is None else f"{r['p_final']:.0%}",
            "Edge": "—" if r.get("ev") is None else f"{r['ev']:+.1%}",
            "Lean": LEAN_ICON.get(r.get("lean"), "—"),
            "Notes": " · ".join(flags),
        })
    return out


def plays_for_log(rows: Sequence[Dict], market: str, game_label: str) -> List[Dict]:
    """Rows with a line -> quick_log play dicts. Side follows the lean (or the better side when there's none).
    A price you typed or the books posted rides along as the real entry price (PriceSource "manual" / "book"),
    so it counts toward closing-line value; otherwise the model's fair price is logged."""
    plays = []
    for r in rows:
        if r.get("line") is None or r.get("p_final") is None:
            continue
        side = r["lean"] if r.get("lean") in ("Over", "Under") else (r.get("side") or "Over")
        p = r["p_final"] if side == "Over" else 1 - r["p_final"]
        play = {"Player": r["player"], "PlayerId": r.get("pid"), "Game": game_label, "Market": market,
                "Side": side, "Line": r["line"], "ModelProb": round(p, 4), "Fair": american(p)}
        tags = [GAP_TAG] if r.get("gap") in ("big", "big-low-count") else []
        if is_star_out(r):
            tags.append(STAR_OUT_TAG)                       # the Scorecard grades star-out nights separately
        tag = use_tag(r, side, r["line"])[0]
        if tag in USE_KEY:
            tags.append(f"use:{USE_KEY[tag]}")              # the Scorecard grades each tag
        if tags:
            play["Notes"] = ",".join(tags)
        price = r.get("over_price") if side == "Over" else r.get("under_price")
        if price is not None:
            play.update(RealPrice=price, PriceSource=r.get("price_src") or "manual")
        plays.append(play)
    return plays


# --------------------------------------------------------------------------- 6. same-game parlays
def market_stats(market: Optional[str]) -> Tuple[str, ...]:
    """The box-score stats a market is made of (PRA -> pts, reb, ast), across every sport's props menu."""
    if not market:
        return ()
    try:
        import player_props as _PPR
        if market in _PPR.MARKETS:
            return tuple(_PPR.MARKETS[market])
        import football_props as _FP
        if market in _FP.MARKETS:
            return tuple(_FP.MARKETS[market]["stats"])
        import hockey_props as _HP
        if market in _HP.MARKETS:
            return (_HP.MARKETS[market]["stat"],)
    except Exception:                                             # noqa: BLE001
        pass
    return (market,)


SAME_PLAYER_BASE = 0.25     # two different stats of one player still share his minutes / usage
SAME_PLAYER_SHARED = 0.65   # ... plus this much more the more of the same box-score stats they share
SAME_GAME = 0.10            # two different players in one game share its pace


def leg_correlation(a: Dict, b: Dict) -> float:
    """Correlation between two legs' outcomes. Same player: 0.25 for unrelated stats (rebounds vs points move
    together through minutes), rising with shared stats (points vs PRA ~0.6, the same market at two lines 0.9).
    Same game, different players: 0.10 (pace). Signed by the sides: an Over with an Under pulls the other way --
    if he plays more, his points over AND his rebounds over both get likelier, so "Under rebounds + Over points"
    is (correctly) slightly negatively correlated."""
    if not a.get("game") or a.get("game") != b.get("game"):
        return 0.0
    sign = (1 if str(a.get("side")).lower() != "under" else -1) * (1 if str(b.get("side")).lower() != "under" else -1)
    if a.get("player") and a.get("player") == b.get("player"):
        sa, sb = set(market_stats(a.get("market"))), set(market_stats(b.get("market")))
        overlap = len(sa & sb) / math.sqrt(len(sa) * len(sb)) if sa and sb else 0.0
        return sign * min(0.95, SAME_PLAYER_BASE + SAME_PLAYER_SHARED * overlap)
    return sign * SAME_GAME


def sgp(legs: Sequence[Dict], book_price=None, n_sims: int = 40000, seed: int = 11) -> Optional[Dict]:
    """Price a same-game parlay with correlation (leg_correlation), not as independent legs.
    legs: [{"player","game","side","p","market"}] (p = that side's probability).

    {"p_joint" (correlated), "p_independent", "fair" (American), "ev" at book_price (None without one),
     "lift" (joint / independent)}."""
    legs = [l for l in legs if l.get("p") is not None]
    if len(legs) < 2:
        return None
    import numpy as np
    import slip_sim as S
    k = len(legs)
    R = np.eye(k)
    for i in range(k):
        for j in range(i + 1, k):
            R[i, j] = R[j, i] = leg_correlation(legs[i], legs[j])
    R = S._nearest_psd_correlation(R)
    Z = S.draw_normals(R, n_sims, np.random.default_rng(seed))
    sim_legs = [{"p": float(l["p"]), "game": l.get("game"), "player": l.get("player"), "side": l.get("side"),
                 "n_eff": 40} for l in legs]
    dec = decimal(book_price)
    res = S.evaluate(sim_legs, {"mode": "parlay", "decimal": dec or 2.0}, n_sims=n_sims, n_worlds=1, seed=seed,
                     uncertainty=False, _Z=Z)
    pj, pi = res["p_all"], res["p_all_independent"]
    return {"p_joint": pj, "p_independent": pi, "fair": american(pj) if 0 < pj < 1 else None,
            "ev": (pj * dec - 1) if dec else None, "lift": (pj / pi) if pi else None, "legs": len(legs)}


# --------------------------------------------------------------------------- 1b. scorecard maths
def calibration_buckets(preds: Sequence[Tuple[float, bool]], n_bins: int = 5) -> List[Dict]:
    """[(probability, hit)] -> [{"lo","hi","predicted","actual","n"}] for non-empty buckets."""
    out = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        grp = [(p, y) for p, y in preds if lo <= p < hi or (i == n_bins - 1 and p == 1.0)]
        if grp:
            out.append({"lo": lo, "hi": hi, "predicted": sum(p for p, _ in grp) / len(grp),
                        "actual": sum(1 for _, y in grp if y) / len(grp), "n": len(grp)})
    return out


def fitted_slope(preds: Sequence[Tuple[float, bool]]) -> Optional[float]:
    """The calibration slope: how far real hit rates moved per unit the model's probability moved away from
    50% (least squares through 50/50). 1.0 = well calibrated; 0.7 = the model is 30% too confident."""
    sxx = sum((p - 0.5) ** 2 for p, _ in preds)
    if sxx <= 1e-9 or len(preds) < 30:
        return None
    sxy = sum((p - 0.5) * ((1.0 if y else 0.0) - 0.5) for p, y in preds)
    lo, hi = CALIBRATION_RANGE
    return min(hi, max(lo, sxy / sxx))


def brier(preds: Sequence[Tuple[float, bool]]) -> Optional[float]:
    if not preds:
        return None
    return sum((p - (1.0 if y else 0.0)) ** 2 for p, y in preds) / len(preds)


# --------------------------------------------------------------------------- the at-a-glance view
def _side_prob(r: Dict) -> Optional[float]:
    p, side = r.get("p_final"), r.get("side")
    if p is None or side not in ("Over", "Under"):
        return None
    return p if side == "Over" else 1 - p


def view_order(rows: Sequence[Dict]) -> List[Dict]:
    """Leans first (best edge, then highest chance), then everything else with a line, then players with no line
    posted, then players who are out."""
    def key(r):
        tier = 0 if r.get("lean") in ("Over", "Under", "Check news") else (1 if r.get("line") is not None else (3 if r.get("out") else 2))
        return (tier, -(r.get("ev") or -1), -(_side_prob(r) or 0))
    return sorted(rows, key=key)


def display_compact(rows: Sequence[Dict], details: bool = False, opp_label: str = "Min",
                    market: Optional[str] = None) -> List[Dict]:
    """The default table: what someone needs to make a pick and nothing blank-looking. Every cell has words in it
    -- a player with no posted line says so instead of showing empty columns. `details` adds the model's working
    (minutes / volume, form, matchup, game environment)."""
    out = []
    for r in view_order(rows):
        status = f" 🚫 {r['status']}" if r.get("out") else (f" ⚠️ {r['status']}" if r.get("status") else "")
        side, line = r.get("side"), r.get("line")
        price = r.get("over_price") if side == "Over" else r.get("under_price")
        best = (r.get("book") or {}).get("best_over" if side == "Over" else "best_under")
        chance = _side_prob(r)
        if r.get("out"):
            pick, lean = "—", "Out tonight"
        elif line is None:
            pick, lean = "No line posted", "—"
        else:
            pick = f"{side} {line:g}" if side else f"{line:g}"
            lean = LEAN_ICON.get(r.get("lean"), "—") if r.get("lean") != "No lean" else "⚪ No edge"
        flags = list(r.get("flags") or [])
        bk = r.get("book") or {}
        if bk.get("pickem"):
            flags.insert(0, f"{bk.get('book')} line — pays a multiplier per entry, no odds")
        if bk.get("missing_book"):
            where = sorted({b for b in (x[0] for x in (bk.get("best_over"), bk.get("best_under")) if x)})
            flags.insert(0, f"not posted at {bk.get('wanted') or bk.get('book')}"
                         + (f" — priced at {', '.join(where)}" if where else " — no sportsbook price"))
        if r.get("gap_from"):
            flags.insert(0, f"⚠️ {r['gap_from']} — check minutes / role / injury news")
        elif r.get("gap") in ("big", "big-low-count") and r.get("gap_pct") is not None:
            flags.insert(0, f"⚠️ Market disagrees: line {line:g} vs projection {r['projection']:.1f} "
                            f"({r['gap_pct']:+.0%}) — "
                            + ("low-count market: books weighted 80%, needs +6% value" if r.get("gap") == "big-low-count"
                               else "check minutes / role / injury news"))
        row = {"Player": f"{r['player']}{status}", "Pos": r.get("slot") or "",
               "Projection": "—" if r.get("projection") is None else f"{r['projection']:.1f}",
               "Line": "—" if line is None else f"{line:g}",
               "Pick": pick,
               "Chance": "—" if chance is None else f"{chance:.0%}",
               "Cushion": cushion_text(cushion(r.get("projection"), line, side)) if not r.get("out") else "—",
               "Use": use_tag(r)[0],
               "Milestones": ladder_text(r, market) if not r.get("out") else "—",
               "Price": ("—" if price is None else f"{price:+.0f}" + (f" {best[0]}" if best and best[1] == price else "")),
               "Edge": "—" if r.get("ev") is None else f"{r['ev']:+.1%}",
               "Lean": lean,
               "Hit rate": "—" if not r.get("hit") else f"{r['hit'][0]}/{r['hit'][1]}",
               "Notes": " · ".join(flags) or "—"}
        if details:
            row.update({opp_label: "—" if r.get("opp") is None else (f"{r['opp']:.0f}" if r["opp"] >= 10 else f"{r['opp']:.1f}"),
                        "Form": "—" if r.get("form") is None else f"{r['form']:.1f} ({r['games']} g)",
                        "Matchup": "—" if r.get("factor") is None else f"{r['factor'] - 1:+.0%}",
                        "Game env": "—" if r.get("env", 1.0) in (None, 1.0) else f"{r['env'] - 1:+.0%}"})
        out.append(row)
    return out


# --------------------------------------------------------------------------- cushion, milestones, leg warnings (Oct 29)
# After the Oct 28 tickets: every leg whose projection cleared its number by 30%+ hit; legs within ~10% went 2 for 6
# -- coin flips. The "X+" milestone legs (Durant 40+, LaMelo 30+) had no probability on the page at all, and the
# pricer couldn't see a whole multi-game ticket.
CUSHION_MIN = 0.15            # a parlay leg wants its projection 15%+ past the number
BLOWOUT_WORDS = ("blowout",)


def cushion(projection: Optional[float], line: Optional[float], side: Optional[str]) -> Optional[float]:
    """How far the projection sits past the number, as a share of it, on the side you're betting (negative = the
    projection is on the other side)."""
    if projection is None or line is None or side not in ("Over", "Under"):
        return None
    thr = threshold(line)
    if thr <= 0:
        return None
    return (projection - thr) / thr if side == "Over" else (thr - projection) / thr


# Milestone ladders the books post ("25+", "30+"...), by market.
LADDER_STEP = {"Points": 5, "PRA": 5, "PR": 5, "PA": 5, "PB": 5, "RA": 2, "Rebounds": 2, "Assists": 2,
               "Threes Made": 1, "Blocks": 1, "Steals": 1}


def ladder_step(market: Optional[str], projection: float) -> float:
    if market in LADDER_STEP:
        return LADDER_STEP[market]
    for step in (1, 2, 5, 10, 25):                 # yards, shots...: a rung roughly every 15-25% of the projection
        if step >= 0.15 * max(projection, 1.0):
            return step
    return 25


def milestone_chance(row: Dict, n: float) -> Optional[float]:
    """The model's chance of N or more (an "N+" milestone) for a props row -- the model alone, since the books'
    milestone prices aren't loaded."""
    if row.get("projection") is None or row.get("out"):
        return None
    floor = row.get("sd_floor") or (0.25, 1.0)
    p = prob_over(row["projection"], row.get("values") or [], float(n) - 0.5, row.get("dist") or "normal", *floor)
    return calibrate(p, row.get("slope", 1.0)) if p is not None else None


def ladder(row: Dict, market: Optional[str], rungs: int = 3) -> List[Tuple[float, float]]:
    """[(N, chance of N+)] for the milestone rungs around his projection (one below, the nearest, one above)."""
    proj = row.get("projection")
    if proj is None or row.get("out"):
        return []
    step = ladder_step(market, proj)
    base = math.floor(proj / step) * step
    ns = [base - step, base, base + step] if rungs == 3 else [base + step * k for k in range(-(rungs // 2), rungs - rungs // 2)]
    out = []
    for n in ns:
        if n < step or n <= 0:
            continue
        p = milestone_chance(row, n)
        if p is not None:
            out.append((n, p))
    return out


def ladder_text(row: Dict, market: Optional[str]) -> str:
    rungs = ladder(row, market)
    return " · ".join(f"{n:g}+ {p:.0%}" for n, p in rungs) or "—"


def leg_warnings(row: Dict, side: Optional[str], line: Optional[float]) -> List[str]:
    """Why a leg is risky in a parlay: a news check, a returning player, the projection on the wrong side or thin,
    blowout risk."""
    w = []
    if row.get("out"):
        w.append("ruled out")
    if row.get("lean") == "Check news" or row.get("gap") == "big" or row.get("gap_from"):
        w.append("check news (line far from projection)")
    if row.get("returning"):
        w.append("missed his team's last game")
    if row.get("absorbs") and side == "Under":
        w.append("top option with a star freshly out — the books price that bump better; check news")
    c = cushion(row.get("projection"), line, side)
    if c is not None:
        if c < 0:
            w.append(f"projection {row['projection']:.1f} is on the other side")
        elif c < CUSHION_MIN:
            w.append(f"thin cushion ({c:+.0%})")
    if any(any(k in str(f).lower() for k in BLOWOUT_WORDS) for f in row.get("flags") or []):
        w.append("blowout risk")
    return w


def cushion_text(c: Optional[float]) -> str:
    if c is None:
        return "—"
    return f"{c:+.0%}" + (" ⚠️" if c < CUSHION_MIN else "")


# --------------------------------------------------------------------------- what a play is fit for (Oct 29)
# Cushion says how SAFE a leg is (how wrong the model can be and still win) -- what a parlay needs, since every leg
# must hit. Edge says whether the PRICE pays enough -- what a single needs. A parlay leg also needs a positive edge:
# a parlay's value compounds, so legs without one compound the book's cut instead.
USE_BOTH, USE_PARLAY, USE_SINGLE, USE_PASS = "🎟️ Parlay + Single", "🎟️ Parlay leg", "🎯 Single only", "⛔ Pass"
USE_KEY = {USE_BOTH: "both", USE_PARLAY: "parlay", USE_SINGLE: "single", USE_PASS: "pass"}
PARLAY_MIN_CHANCE = 0.60          # each parlay leg 60%+ to hit ...
MILESTONE_PARLAY_CHANCE = 0.70    # ... a model-only milestone leg 70%+ (no market check on it)
PICKEM_BREAKEVEN = 3.0 ** -0.5    # a 2-pick entry paying 3x needs ~57.7% a pick; the ticket builder uses yours


def same_game_stacks(items: Sequence[Dict], game_key: str = "game", label_key: str = "label") -> Dict[str, List[str]]:
    """{game: [labels]} for every game with more than one selection. Oct 31: two of the Oct 30 singles came from
    Magic-Raptors and lost together (same game script, same star out) -- a card should spread across games."""
    by: Dict[str, List[str]] = {}
    for it in items or []:
        g = it.get(game_key)
        if g:
            by.setdefault(str(g), []).append(str(it.get(label_key) or "?"))
    return {g: labs for g, labs in by.items() if len(labs) > 1}


def stack_warning(items: Sequence[Dict], game_key: str = "game", label_key: str = "label") -> Optional[str]:
    stacks = same_game_stacks(items, game_key, label_key)
    if not stacks:
        return None
    return ("More than one pick from the same game — they tend to win or lose together: "
            + "; ".join(f"{g} ({len(labs)}: {', '.join(labs)})" for g, labs in stacks.items()))


def is_parlay_use(tag: Optional[str]) -> bool:
    return tag in (USE_BOTH, USE_PARLAY)


def use_tag(row: Dict, side: Optional[str] = None, line: Optional[float] = None, p: Optional[float] = None,
            ev=..., milestone: bool = False) -> Tuple[str, str]:
    """(tag, reason): 🎟️ Parlay + Single / 🎟️ Parlay leg / 🎯 Single only / ⛔ Pass / "—" for one play.

    Parlay leg: cushion CUSHION_MIN+, chance PARLAY_MIN_CHANCE+ (MILESTONE_PARLAY_CHANCE for a model-only "N+"),
      a positive edge at the price (pick'em: the chance clears PICKEM_BREAKEVEN), no warnings.
    Single: a real lean -- MIN_EV+ at a real price, the model on that side (pick'em apps have no singles).
    Pass: a warning (news check, missed last game, blowout risk), the projection on the other side, or neither."""
    side = side or row.get("side")
    line = row.get("line") if line is None else line
    if row.get("out") or line is None or side not in ("Over", "Under") or row.get("projection") is None:
        return "—", "no line"
    if p is None:
        p = _side_prob(row) if side == row.get("side") else (None if row.get("p_final") is None else
                                                               (row["p_final"] if side == "Over" else 1 - row["p_final"]))
    if milestone:
        ev = None                                   # an "N+" rung has no market price of its own
    elif ev is ...:
        ev = row.get("ev") if side == row.get("side") else None
    pickem = bool((row.get("book") or {}).get("pickem"))
    warns = [w for w in leg_warnings(row, side, line) if not w.startswith("thin cushion")]
    if warns:
        return USE_PASS, "; ".join(warns)
    c = cushion(row.get("projection"), line, side)
    if c is None or c < 0:
        return USE_PASS, "projection on the other side of the number"
    need = MILESTONE_PARLAY_CHANCE if milestone else PARLAY_MIN_CHANCE
    if pickem:
        value_ok = p is not None and p >= PICKEM_BREAKEVEN
    else:
        value_ok = ev is None if milestone else (ev is not None and ev > 0)
    parlay = c >= CUSHION_MIN and p is not None and p >= need and value_ok
    single = (not milestone and not pickem and row.get("lean") == side and ev is not None and ev >= MIN_EV)
    bits = [f"cushion {c:+.0%}"] + ([f"chance {p:.0%}"] if p is not None else []) + \
           ([f"edge {ev:+.1%}"] if ev is not None else (["model-only milestone"] if milestone else []))
    if parlay and single:
        return USE_BOTH, ", ".join(bits)
    if parlay:
        return USE_PARLAY, ", ".join(bits) + ("" if pickem or milestone else " — edge under +3%, not enough alone")
    if single:
        return USE_SINGLE, ", ".join(bits) + " — too close to the number to chain"
    why = []
    if c < CUSHION_MIN:
        why.append("thin cushion")
    if p is not None and p < need:
        why.append(f"chance under {need:.0%}")
    if not value_ok:
        why.append("below the pick'em break-even" if pickem else "no edge at this price")
    return USE_PASS, ", ".join(bits) + (" — " + ", ".join(why) if why else "")


def note_tags(notes) -> List[str]:
    return [t.strip() for t in str(notes or "").split(",") if t.strip()]


def has_tag(notes, tag: str) -> bool:
    return tag in note_tags(notes)


def best_reads(rows: Sequence[Dict], team_of: Dict, limit: int = 6) -> List[Dict]:
    """The game's strongest leans across both teams: real leans first by edge, then the most likely sides."""
    leans = [r for r in rows if r.get("lean") in ("Over", "Under")]
    leans.sort(key=lambda r: (-(r.get("ev") or 0), -(_side_prob(r) or 0)))
    out = []
    for r in leans[:limit]:
        price = r.get("over_price") if r["side"] == "Over" else r.get("under_price")
        out.append({"Player": r["player"], "Team": team_of.get(r.get("pid"), ""),
                    "Pick": f"{r['side']} {r['line']:g}", "Chance": f"{_side_prob(r):.0%}",
                    "Cushion": cushion_text(cushion(r.get("projection"), r.get("line"), r.get("side"))),
                    "Use": use_tag(r)[0],
                    "Price": "—" if price is None else f"{price:+.0f}",
                    "Edge": "—" if r.get("ev") is None else f"{r['ev']:+.1%}",
                    "Why": " · ".join([f"projects {r['projection']:.1f}"] + list((r.get("flags") or [])[:2]))})
    return out


def market_gaps(rows: Sequence[Dict], team_of: Dict) -> List[Dict]:
    """The "check before betting" list: rows where the books and the model disagree by a lot, and players who
    missed their team's last game (returning, maybe on a minutes limit) with an Over the model likes."""
    out = []
    for r in rows:
        big = r.get("gap") in ("big", "big-low-count")
        back = bool(r.get("returning")) and r.get("lean") in ("Check news", "Over")
        if not (big or back) or r.get("projection") is None or r.get("line") is None:
            continue
        why = []
        if r.get("gap_from"):
            why.append(r["gap_from"])
        elif big:
            why.append("line far from projection" + (" (low count — no news check)" if r.get("gap") == "big-low-count"
                                                     else ""))
        if r.get("returning"):
            why.append("missed team's last game")
        sp = _side_prob(r)
        out.append({"Player": r["player"], "Team": team_of.get(r.get("pid"), ""),
                    "Line": f"{r['line']:g}", "Projection": f"{r['projection']:.1f}",
                    "Gap": "—" if r.get("gap_pct") is None else f"{r['gap_pct']:+.0%}",
                    "Why flagged": " + ".join(why),
                    "Model says": f"{r['side']} ({sp:.0%} after leaning on the market)" if sp is not None else "—",
                    "Status": "news checked — lean shown" if r.get("lean") in ("Over", "Under") else
                              ("⚠️ check news first" if r.get("lean") == "Check news" else "no value at this price")})
    out.sort(key=lambda d: -abs(float(d["Gap"].rstrip("%"))) if d["Gap"] != "—" else 0)
    return out
