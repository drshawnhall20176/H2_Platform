"""
grading.py — sport-agnostic letter-grade/tier logic for ranking "plays" (the shared shape
build_best_bets produces across every sport on this platform: Player/Market/Side/Line/ModelProb/
Fair/Conviction/Why).

WHY THIS IS ITS OWN, SEPARATE MODULE, NOT LIVING IN MLB's projections.py: a real bug found while
auditing cross-sport consistency, not a preemptive guess. Graded Picks called
P.organize_graded_picks(plays), where P is whichever sport's own projections module happens to be
active — but organize_graded_picks/conviction_to_grade only ever existed in MLB's own
projections.py. Confirmed directly: opening Graded Picks on WNBA, NBA, NFL, or NCAAMB would have
crashed immediately with an AttributeError, not degraded gracefully. The grading logic itself
never actually depended on anything MLB-specific — it operates purely on Conviction, a number
every sport's own build_best_bets already produces in the same shape — so it belongs in a shared
module every sport's page can call directly, not duplicated per sport and not left silently
assuming MLB's projections.py is always the one in scope.

MLB's projections.py re-exports everything here for backward compatibility with existing callers
(e.g. best_bets_data.py, and this session's own earlier tests) that reference these by their
original P.* path — the values are identical, just sourced from one real place instead of five
separate copies waiting to drift.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

# Conviction -> letter grade + tier label. Thresholds are this platform's OWN, grounded in its
# own already-established Conviction scale (Best Bets' own min-conviction slider already treats
# 1.2x as the floor worth showing at all, and real top plays observed on this platform's own
# slates cluster in the 2.7-4.25x range), not reverse-engineered from any other product's scoring.
# Labels are this platform's own wording, not copied badge text -- see conviction_to_grade's own
# docstring for the real reason this matters.
GRADE_THRESHOLDS = [
    (3.0, "A", "Top Lean"),
    (2.0, "B", "Strong Lean"),
    (1.5, "C", "Lean"),
    (1.2, "D", "Watch"),
]

# A real, confirmed finding, not a hypothetical: Conviction = ModelProb / RefProb has a hard
# ceiling of 1/RefProb (the favored side's probability can never exceed 1.0). MLB's own
# BEST_BET_REF["Batter HR"] = 0.11 gives HR a ceiling near 9.09x, comfortably above the 3.0x "A"
# threshold -- but checked directly against every OTHER market on this platform, 9 of MLB's own
# 11 markets have a ceiling BELOW 3.0x, meaning an "A" grade is mathematically impossible for
# them no matter how good the play is. Checked cross-sport too: every other sport (WNBA, NBA,
# NFL, NCAAMB) uses ref=0.5 for every single one of its markets, giving a ceiling of exactly
# 2.0x -- meaning NO play on any of those sports could ever reach even a "B" grade, let alone
# "A", under the raw-conviction thresholds alone. GRADE_THRESHOLDS were set by watching real
# Best Bets output that was itself dominated by HR (the market with by far the most headroom),
# so the thresholds ended up implicitly calibrated to HR's own range without anyone realizing
# every other market was structurally locked out of the top grades.
REFERENCE_CEILING = 1.0 / 0.11   # ~9.09 -- MLB Batter HR's own theoretical ceiling, kept as the
                                 # fixed benchmark every OTHER market's own ceiling gets
                                 # normalized against below, so HR's own grades don't change at
                                 # all under this normalization -- everything else gets scaled
                                 # fairly relative to the market the thresholds were already,
                                 # if unintentionally, calibrated around, not a new arbitrary
                                 # number invented for this fix.


def conviction_to_grade(conviction: Optional[float], ceiling: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Map a play's Conviction number to a letter grade + tier label for quick visual scanning --
    NOT a fabricated 0-100 "score" that doesn't map to anything real. The raw Conviction number
    (e.g. "3.2x") is a genuinely interpretable value on its own -- "this play's real probability
    is 3.2x the market-typical rate for this prop" -- so the grade is presented ALONGSIDE it, not
    instead of it, honest about what's actually driving the label rather than hiding it behind an
    opaque score. The DISPLAYED conviction in the returned dict is always the real, raw number --
    never the normalized one used only internally to pick the letter, so nothing shown to a
    person is a value that doesn't actually mean what it says.

    A REAL, DELIBERATE NAMING CHOICE: labels here ("Top Lean" / "Strong Lean" / "Lean" / "Watch")
    are this platform's own wording, chosen specifically to describe the SAME underlying concept
    (a tiered conviction label) without reusing another product's specific badge text -- avoiding
    exactly the "duplicating someone else's badges" concern raised directly during scoping, not
    just applied to the genuinely unclear proprietary terms ("Blast Match" etc, deliberately left
    out entirely) but to the clearer ones too.

    ceiling: this SPECIFIC play's own theoretical maximum possible conviction (1/RefProb for
    whichever side is favored) -- when supplied, conviction is normalized against it (scaled by
    REFERENCE_CEILING / ceiling) BEFORE comparing to GRADE_THRESHOLDS, so a market with a
    genuinely lower ceiling than HR's isn't structurally locked out of ever reaching a high
    grade, and a market with a HIGHER ceiling than HR's (Stolen Bases, whose rarity gives it even
    more headroom than HR) gets appropriately compressed rather than dominating every ranking for
    reasons that have nothing to do with how good the actual play is. When ceiling is None (a
    play with no such info, or an older caller not yet passing it), falls back to comparing the
    RAW conviction directly -- stays backward compatible rather than silently reinterpreting a
    caller's numbers it wasn't given enough context to normalize correctly.

    SPORT-AGNOSTIC BY DESIGN: takes a plain Conviction number (and optional ceiling), not a
    sport-specific row shape -- works identically whether the play came from MLB, WNBA, NBA, NFL,
    or NCAAMB's own build_best_bets, since Conviction and ceiling mean the same thing (ModelProb
    / a market-typical reference rate; 1 / that reference rate) in every one of them.

    Returns None for anything below the lowest real threshold (1.2x on the NORMALIZED value,
    matching Best Bets' own established "worth showing at all" floor) -- a play that isn't
    notable shouldn't get a grade that implies it is."""
    if conviction is None:
        return None
    graded_value = conviction
    if ceiling and ceiling > 0:
        graded_value = conviction * (REFERENCE_CEILING / ceiling)
    for threshold, letter, tier in GRADE_THRESHOLDS:
        if graded_value >= threshold:
            return {"letter": letter, "tier": tier, "conviction": conviction}
    return None


def organize_graded_picks(plays: List[Dict]) -> List[Dict[str, Any]]:
    """Grade every play, drop what doesn't clear the real floor, and organize what's left into a
    game-by-game structure ready to render -- the core, testable logic behind the Graded Picks
    page, deliberately kept separate from any Streamlit rendering code so it can be unit tested
    directly rather than only trusted by eye in the browser.

    WHY GAME-BY-GAME, NOT A FLAT RANKED LIST -- the real reasoning this was built from: a flat
    top-N naturally clusters on whichever 2-3 games happen to have the juiciest matchups that
    night, leaving the rest of the slate invisible to anyone specifically interested in a
    different game. Every game with at least one graded play gets its own section here; nothing
    is silently dropped for not being in a top-N cut.

    SORT ORDER, at both levels: games are ordered by their own single BEST play's Conviction
    (most interesting game first), and players within a game are ordered by their own best play's
    Conviction the same way -- "most interesting first," not alphabetical or arbitrary.

    SPORT-AGNOSTIC BY DESIGN, same reasoning as conviction_to_grade: operates purely on each
    play's own Game/Player/Team/Conviction fields, present in the same shape regardless of which
    sport's build_best_bets produced the list.

    Returns a list of {"game": str, "players": [{"player": str, "team": str, "plays": [play,...]}
    ]}, already sorted at both levels, with each play carrying its own "_grade" (from
    conviction_to_grade) already attached. A play with no real grade (below the floor) is not
    included anywhere in the output -- this function IS the grading floor, not just a display
    filter applied on top of it elsewhere."""
    graded = []
    for pl in plays:
        grade = conviction_to_grade(pl.get("Conviction"), pl.get("_ceiling"))
        if grade:
            graded.append({**pl, "_grade": grade})
    if not graded:
        return []

    games: Dict[str, List[Dict]] = {}
    for pl in graded:
        games.setdefault(pl["Game"], []).append(pl)

    game_order = sorted(games.keys(), key=lambda g: max(p["Conviction"] for p in games[g]), reverse=True)

    out = []
    for game_label in game_order:
        game_plays = games[game_label]
        by_player: Dict[str, List[Dict]] = {}
        for pl in game_plays:
            by_player.setdefault(pl["Player"], []).append(pl)
        player_order = sorted(by_player.keys(),
                              key=lambda pn: max(p["Conviction"] for p in by_player[pn]),
                              reverse=True)
        players = []
        for player in player_order:
            player_plays = sorted(by_player[player], key=lambda p: p["Conviction"], reverse=True)
            players.append({"player": player, "team": player_plays[0].get("Team", ""),
                           "plays": player_plays})
        out.append({"game": game_label, "players": players})
    return out


def grade_accuracy_by_letter(graded_plays: List[Dict]) -> List[Dict]:
    """Takes ALREADY-GRADED plays (each carrying "Hit": True/False/None and "Conviction" -- e.g.
    retro.grade_slate's own output) and breaks down REAL hit rate by letter grade
    (conviction_to_grade) -- the direct test of whether Graded Picks' own letter grades mean
    anything: does an A actually hit more often than a C, using real settled outcomes, not a
    hypothetical.

    WHY THIS EXISTS, THE ACTUAL QUESTION IT ANSWERS: Graded Picks shows a letter grade on every
    play, but nothing previously checked whether that grade correlates with real results.
    retro.grade_slate already breaks down hit rate by conviction tier using its own separate
    numeric thresholds (>=1.75x, 1.4-1.75x, etc) -- a real, useful metric, but a DIFFERENT one.
    This uses the SAME letter-grade thresholds Graded Picks itself shows, so the answer comes
    back in the exact terms a person actually sees on that page, not a parallel, differently-
    bucketed one that doesn't map onto what's displayed there.

    NOW SPORT-AGNOSTIC, A REAL CHANGE FROM WHEN THIS FIRST SHIPPED: originally lived in MLB's own
    projections.py specifically because conviction_to_grade was MLB-only at the time, and calling
    it from retro.py (shared across every sport) would have broken retro.py's own sport-agnostic
    design. Moving conviction_to_grade itself here removes that constraint entirely -- this can
    now be called for any sport's own graded plays without an MLB-only gate anywhere upstream.

    Only settled plays (Hit is not None) count. A grade with zero settled plays in this window is
    simply absent from the output -- not shown as a fabricated 0% or 100%."""
    settled = [g for g in graded_plays if g.get("Hit") is not None]
    by_letter: Dict[str, List[Dict]] = {}
    for g in settled:
        grade = conviction_to_grade(g.get("Conviction"), g.get("_ceiling"))
        if grade:
            by_letter.setdefault(grade["letter"], []).append(g)
    out = []
    for threshold, letter, tier in GRADE_THRESHOLDS:
        grp = by_letter.get(letter, [])
        if grp:
            out.append({
                "letter": letter, "tier": tier, "n": len(grp),
                "hit_rate": round(sum(1 for g in grp if g["Hit"]) / len(grp), 3),
            })
    return out


# ===========================================================================
# SUGGESTED PARLAYS -- for a Discord/public audience that doesn't want to comb through the
# graded board themselves. A REAL, DELIBERATE CORRELATION SAFEGUARD IS THE CORE OF THIS DESIGN,
# NOT AN AFTERTHOUGHT: a parlay's combined probability is only honestly the product of each
# leg's own probability if the legs are independent. Two legs on the SAME PLAYER are almost never
# independent -- a home run leg and a total-bases leg on the same hitter are so tightly coupled
# that multiplying their individual probabilities would badly UNDERSTATE the real combined
# chance, producing a number that's actively misleading, not just imprecise. This matters more,
# not less, on a page built specifically for people who explicitly don't want to dig into why a
# number is what it is -- they're trusting it at face value.
PARLAY_TIER_SIZES = [
    (2, "Safer"),
    (4, "Balanced"),
    (6, "Longshot"),
]   # cumulative from the SAME ranked pool below (the 4-leg tier's first two legs are the exact
   # same two legs as the 2-leg tier) -- a real, deliberate choice: "safer" means fewer of the
   # model's own top picks chained together, "longshot" means more of those SAME picks chained
   # together, so the risk difference comes honestly from the math of multiplying more legs
   # together, not from quietly swapping in worse plays for the bigger tiers.


def build_parlay_leg_pool(plays: List[Dict], max_per_game: int = 2, max_per_market: int = 2,
                          min_pool_size: int = 0) -> List[Dict]:
    """Rank graded plays by Conviction, then walk them building a pool that's actually SAFE to
    combine into parlays: at most ONE leg per player (a hard constraint -- see this section's own
    module-level comment for why this is the single most important rule here, not a minor
    detail), at most max_per_game legs sharing a game (a real but weaker correlation concern --
    two different hitters on opposing teams in the same game can share some game-script/weather
    correlation, but nowhere near as severe as a same-player pairing), and at most max_per_market
    legs sharing a market (keeps a parlay from reading as six home-run bets in a trenchcoat --
    default tightened from 3 to 2 after a real, concrete example: Stolen Bases is a genuinely
    high-variance market, so an elite base stealer's conviction ratio can run well above an elite
    slugger's HR conviction for a similar raw probability, not because either model is wrong, but
    because SB really is a more skewed market than HR. Left unconstrained, that skew let three
    different burners' SB legs alone fill an entire tier before any other market appeared,
    reading as far less realistic than what a person would actually build themselves).

    min_pool_size: a REAL, reported bug this parameter fixes -- fixed caps alone silently strand
    a person who deliberately narrows Suggested Parlays down to one market (or a thin slate with
    few games): with max_per_market=2, selecting ONLY "Pitcher Strikeouts" caps the whole pool at
    2 legs total, even if 6 different real, graded pitchers exist that night, because the cap was
    designed to force diversity ACROSS markets, not to punish someone who already chose to narrow
    to one. When min_pool_size > 0, max_per_game and/or max_per_market are LOOSENED (never
    tightened) just enough to make a pool of that size achievable, given how many DISTINCT games
    and markets are actually present among the graded plays -- e.g. with only 1 distinct market
    graded and min_pool_size=6, max_per_market effectively becomes 6, not because 2 stopped
    mattering, but because there's nothing left to diversify into. If there are genuinely enough
    distinct games/markets already, the original caps are used unchanged.

    Returns a FLAT, conviction-ranked list -- not grouped by game the way organize_graded_picks
    is, since parlay legs are chosen across the WHOLE board at once, not within one game.

    Player uniqueness is keyed on (Player, Team), not Player alone -- two genuinely different
    people can share a common name across different teams, and keying on name alone could
    wrongly treat them as the same person and drop one for no real reason."""
    graded = []
    for pl in plays:
        grade = conviction_to_grade(pl.get("Conviction"), pl.get("_ceiling"))
        if grade:
            graded.append({**pl, "_grade": grade})
    graded.sort(key=lambda p: p["Conviction"], reverse=True)

    if min_pool_size > 0:
        distinct_games = len({p.get("Game") for p in graded})
        distinct_markets = len({p.get("Market") for p in graded})
        if distinct_games > 0:
            max_per_game = max(max_per_game, math.ceil(min_pool_size / distinct_games))
        if distinct_markets > 0:
            max_per_market = max(max_per_market, math.ceil(min_pool_size / distinct_markets))

    pool: List[Dict] = []
    seen_players = set()
    game_counts: Dict[str, int] = {}
    market_counts: Dict[str, int] = {}
    for pl in graded:
        player_key = (pl.get("Player"), pl.get("Team"))
        if player_key in seen_players:
            continue
        game = pl.get("Game")
        market = pl.get("Market")
        if game_counts.get(game, 0) >= max_per_game:
            continue
        if market_counts.get(market, 0) >= max_per_market:
            continue
        pool.append(pl)
        seen_players.add(player_key)
        game_counts[game] = game_counts.get(game, 0) + 1
        market_counts[market] = market_counts.get(market, 0) + 1
    return pool


def combined_parlay_prob(legs: List[Dict]) -> float:
    """Combined probability of every leg hitting, ASSUMING INDEPENDENCE -- the product of each
    leg's own ModelProb. This assumption is exactly why build_parlay_leg_pool exists and is used
    upstream of this: it eliminates the worst, most severe violation of independence (same-player
    legs) before this math ever runs. It does NOT make the remaining legs perfectly independent
    (same-game-different-player legs can still share weaker correlation) -- callers displaying
    this number should say so, not present it as an exact, guaranteed probability."""
    p = 1.0
    for leg in legs:
        p *= leg.get("ModelProb", 0.0)
    return p


def build_suggested_parlays(plays: List[Dict], tier_sizes: Optional[List] = None,
                            max_per_game: int = 2, max_per_market: int = 2) -> List[Dict]:
    """Build tiered parlay suggestions from a graded plays list -- the actual feature: someone
    who doesn't want to comb through the board themselves gets a few ready-made options instead.

    tier_sizes defaults to PARLAY_TIER_SIZES ((2, "Safer"), (4, "Balanced"), (6, "Longshot")).
    Each tier's legs are the top N (by Conviction) from the SAME pool build_parlay_leg_pool
    produces -- so a 4-leg tier's first two legs are literally the same two legs as the 2-leg
    tier, not a different, re-optimized set. This is a deliberate simplicity choice: the risk
    difference between tiers comes honestly from chaining more legs together (probabilities
    multiply down as you add legs, even when every individual leg is a real, graded pick), not
    from quietly substituting worse plays into the bigger tiers to make them "feel" different.

    A tier is SKIPPED ENTIRELY, not padded with weaker plays, when the pool doesn't have enough
    genuinely diverse legs to fill it honestly (e.g. a thin slate with only 3 real graded plays
    across 3 different players can't honestly support a 4-leg tier) -- silently forcing a 6-leg
    parlay out of a pool that only had 3 safe options would defeat the entire point of the
    diversity safeguards above.

    Calls build_parlay_leg_pool with min_pool_size set to the LARGEST requested tier size -- a
    real, reported fix: without this, selecting a single market (e.g. only "Pitcher Strikeouts")
    silently capped the whole pool at max_per_market (2) regardless of how many real, different
    pitchers were actually graded that night, since the per-market cap has nothing left to
    diversify into once only one market is selected. See build_parlay_leg_pool's own docstring
    for the full mechanism.

    Returns a list of {"tier": str, "size": int, "legs": [play, ...], "combined_prob": float,
    "combined_fair_decimal": float, "combined_fair_american": int}, one entry per tier that could
    actually be filled."""
    from projections import prob_to_decimal, prob_to_american   # lazy, not module-level -- avoids
                                                                 # a real circular import
                                                                 # (projections.py itself imports
                                                                 # FROM this module at its own top
                                                                 # level), same lazy-import pattern
                                                                 # already used elsewhere in this
                                                                 # codebase for exactly this
                                                                 # situation (e.g. sports.py's
                                                                 # require_trading_access).
                                                                 # Genuinely sport-agnostic pure
                                                                 # math, reused the same way every
                                                                 # other sport's own projections
                                                                 # module already does -- not
                                                                 # duplicated, just imported late.
    sizes = tier_sizes if tier_sizes is not None else PARLAY_TIER_SIZES
    largest_tier = max((size for size, _ in sizes), default=0)
    pool = build_parlay_leg_pool(plays, max_per_game, max_per_market, min_pool_size=largest_tier)

    out = []
    for size, label in sizes:
        if len(pool) < size:
            continue
        legs = pool[:size]
        combined_prob = combined_parlay_prob(legs)
        out.append({
            "tier": label, "size": size, "legs": legs,
            "combined_prob": round(combined_prob, 4),
            "combined_fair_decimal": prob_to_decimal(combined_prob),
            "combined_fair_american": prob_to_american(combined_prob),
        })
    return out
