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

AMPLIFICATION_CAP = 2.5   # a real, stated bound (not empirically fit) on how much any single
                         # market's low ceiling can amplify the edge portion above 1.0 -- found
                         # necessary via a real, reported case: H-R-R's Under side (ceiling
                         # ~2.63, since its 0.62 reference sits far closer to a coin flip than
                         # HR's 0.11 does) would otherwise amplify by ~4.96x, letting a real but
                         # genuinely modest edge (1.408x raw -- a real ~15-percentage-point edge,
                         # nowhere close to exceptional) reach "A" purely because that market's
                         # own ceiling is structurally compressed, not because the play itself
                         # was rare or outstanding. Verified by hand against the motivating case
                         # for ceiling normalization in the first place (a genuinely exceptional
                         # near-50%-reference play, e.g. a 90% ModelProb on a ref=0.5 market)
                         # still reaches A at this cap, while a merely modest edge on the same
                         # kind of market (a 60% ModelProb) stays well below it.


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
    a capped REFERENCE_CEILING / ceiling ratio, see AMPLIFICATION_CAP below) BEFORE comparing to
    GRADE_THRESHOLDS, so a market with a genuinely lower ceiling than HR's isn't structurally
    locked out of ever reaching a high grade, and a market with a HIGHER ceiling than HR's
    (Stolen Bases, whose rarity gives it even more headroom than HR) gets appropriately
    compressed rather than dominating every ranking for reasons that have nothing to do with how
    good the actual play is. When ceiling is None (a play with no such info, or an older caller
    not yet passing it), falls back to comparing the RAW conviction directly -- stays backward
    compatible rather than silently reinterpreting a caller's numbers it wasn't given enough
    context to normalize correctly.

    SPORT-AGNOSTIC BY DESIGN: takes a plain Conviction number (and optional ceiling), not a
    sport-specific row shape -- works identically whether the play came from MLB, WNBA, NBA, NFL,
    or NCAAMB's own build_best_bets, since Conviction and ceiling mean the same thing (ModelProb
    / a market-typical reference rate; 1 / that reference rate) in every one of them.

    Returns None for anything below the lowest real threshold (1.2x on the NORMALIZED value,
    matching Best Bets' own established "worth showing at all" floor) -- a play that isn't
    notable shouldn't get a grade that implies it is.

    The returned dict also includes "rank_value" -- the internal, ceiling-normalized number used
    to pick the letter, exposed directly (not just used internally) for a real, confirmed reason:
    a caller sorting plays by raw Conviction alone (e.g. an "across every market" leaderboard)
    can produce a genuine INVERSION against this function's own letter grades -- a raw 2.5x on
    HR (ceiling ~9.09, only a "B") can outrank a raw 1.8x on a near-50%-reference market (ceiling
    ~2.0, a genuine "A") purely because HR's raw numbers run bigger, even though the SECOND play
    is the actually stronger one by this function's own grading logic. Any ranking across
    multiple markets should sort by "rank_value", never by the bare Conviction number alone."""
    if conviction is None:
        return None
    graded_value = conviction
    if ceiling and ceiling > 1.0:
        # A REAL, CONFIRMED FIX to the normalization itself, not the original design intent --
        # anchored at 1.0 (the universal "no real edge at all" baseline every market shares),
        # scaling only the EDGE ABOVE 1.0 by how much headroom this market's own ceiling has
        # relative to HR's, not the whole raw number. The original version (conviction * ratio)
        # scaled the 1.0 baseline itself along with the real edge, which meant a market with a
        # low ceiling (H-R-R's Under side, ceiling ~2.63) could turn a TRIVIAL, barely-above-
        # breakeven raw conviction (1.03x -- essentially no real edge) into a normalized value
        # over 3.5, reaching "A" purely from the ratio, not from the play actually being good.
        # Confirmed directly: this fix drops that exact case back below the D-grade floor, while
        # leaving HR's own grades byte-identical (ceiling == REFERENCE_CEILING makes this
        # formula reduce to graded_value == conviction exactly) and still letting a genuinely
        # good low-ceiling play (a real, large edge above 1.0, not a token one) reach A.
        #
        # A SECOND, REAL FIX ON TOP OF THAT ONE -- confirmed via a real, reported follow-up:
        # even with the anchor above, a market whose reference probability sits close to 0.5
        # (H-R-R at 0.62, far closer to a coin flip than HR's 0.11) has a structurally
        # COMPRESSED ceiling (2.63, vs HR's 9.09) -- meaning real players cluster tightly in a
        # narrow raw-conviction band near that low ceiling, so even a MODEST, unremarkable edge
        # (a real 15-percentage-point edge, 1.408x raw, nowhere close to exceptional) sits a
        # LARGE fraction of the way to that market's own small ceiling, and the anchor formula
        # above -- while mathematically consistent -- amplifies that fraction the same as it
        # would for a genuinely rare, exceptional edge on HR. AMPLIFICATION_CAP bounds how much
        # any single market's low ceiling can amplify the edge portion, so a proportionally
        # "far along" but absolutely modest edge doesn't get treated as equivalent to a truly
        # rare one just because its own market happens to have less room to begin with.
        amplification = min((REFERENCE_CEILING - 1.0) / (ceiling - 1.0), AMPLIFICATION_CAP)
        graded_value = 1.0 + (conviction - 1.0) * amplification
    for threshold, letter, tier in GRADE_THRESHOLDS:
        if graded_value >= threshold:
            return {"letter": letter, "tier": tier, "conviction": conviction,
                    "rank_value": round(graded_value, 4)}
    return None


def filter_min_probability(plays: List[Dict], min_prob: float) -> List[Dict]:
    """Keep only plays whose own real ModelProb clears min_prob (0.0-1.0) -- a raw, absolute
    probability floor, added directly on request after a real, reported gap: a real, sharp
    trader's own manual process wanted "show me only plays at least 70% likely to hit," and
    the platform's existing floors (grade letters like C/B/A, or Best Bets' own Conviction
    slider) don't answer that directly -- both are RELATIVE to a market's own typical reference
    rate, not an absolute probability cutoff. Two plays can carry the same letter grade, or the
    same Conviction ratio, at very different raw ModelProb levels (a market with a low reference
    rate needs less raw probability to clear the same relative bar than one with a high
    reference rate) -- this filters on the one number that means the same thing regardless of
    which market a play is in.

    Shared, sport-agnostic, and deliberately simple: every play on this platform already carries
    a real "ModelProb" field (attached at the exact same place Conviction and Fair are, in every
    sport's own build_best_bets), so this is one small, testable filter reused across Best Bets,
    Graded Picks, Suggested Parlays, and Speculative Basket rather than four near-duplicate
    inline filters drifting apart over time.

    min_prob <= 0 returns every play completely unfiltered (the default, "no floor" state) --
    deliberately not even touching plays with a missing/None ModelProb in that case, so a caller
    that never sets a floor sees byte-identical behavior to before this function existed. Once a
    real floor is set (min_prob > 0), a play with no ModelProb at all is excluded, not treated as
    passing an unknown threshold."""
    if min_prob <= 0:
        return list(plays)
    return [p for p in plays if p.get("ModelProb") is not None and p["ModelProb"] >= min_prob]


def rank_flat_plays(plays: List[Dict], key: str = "rank_value") -> List[Dict]:
    """Attach an explicit, 1-indexed "_rank" to a flat list of plays, sorted by the given key --
    shared, testable logic behind the ranking shown on Graded Picks (once a specific game is
    selected), Suggested Parlays (within each tier), and Speculative Basket, added directly on
    request: multiple plays can share the same letter grade while still having meaningfully
    different real numbers behind them, and an explicit rank helps someone pick among several
    same-grade options rather than treating them as interchangeable.

    key: "rank_value" (default) reads each play's own "_grade" dict, matching the SAME ceiling-
    normalized ordering that determines the letter grades themselves -- the right choice for
    Graded Picks specifically, since that page's entire identity IS its letter grades, and a
    ranking that disagreed with them would reintroduce the exact cross-market inversion problem
    just fixed in organize_graded_picks and Command Center. "ModelProb" reads the play's own raw
    probability directly instead -- the right choice for Suggested Parlays/Speculative Basket,
    which are explicitly framed around "which of these is more likely to actually hit," a
    genuinely different question than "which has the better edge relative to typical."

    Plays missing the requested key (e.g. no "_grade" attached, for the "rank_value" case) sort
    last, never crash -- a defensive floor, not a claim that they're actually the weakest."""
    def _sort_key(p: Dict) -> float:
        if key == "rank_value":
            grade = p.get("_grade")
            return grade["rank_value"] if grade else float("-inf")
        return p.get(key, float("-inf"))

    ranked = sorted(plays, key=_sort_key, reverse=True)
    for i, p in enumerate(ranked, start=1):
        p["_rank"] = i
    return ranked


def build_top_leans(plays: List[Dict], per_market: int = 2) -> List[Dict]:
    """Grade every play, then pick the best `per_market` from EACH market, all sorted by real
    probability of hitting (ModelProb) -- the actual, testable logic behind Command Center's
    "Tonight's top leans" widget, pulled out of the view layer for the same reason every other
    piece of real logic on this platform lives here: so it's genuinely unit tested, not just
    trusted by eye in the browser.

    A REAL, CONFIRMED FIX to the original design, not a style choice: ranking by rank_value
    (this platform's own ceiling-normalized Conviction metric) sounds reasonable but produces
    the wrong answer for what "leans" actually means to a real person. Confirmed directly with a
    real, reported example: a genuine longshot Triples play (an actual 11% chance of happening,
    an 89% chance it doesn't) can carry a raw Conviction of 4.44x purely because Triples' own
    reference rate is so low (~2.5%) that even a modest real probability looks enormous relative
    to it. rank_value would still call this a real, valid grade -- and it is, as an EDGE -- but
    "leans" colloquially means "I lean toward this happening," a probability question, not an
    edge-relative-to-typical one. This is the exact same distinction already built into Suggested
    Parlays' Safer/Steady tiers (_tier_sort_key("safety") ranks by raw ModelProb for precisely
    this reason) -- this widget just never got the same treatment until now.

    Graded Picks itself stays rank_value-sorted ON PURPOSE (see organize_graded_picks' own
    docstring) -- its entire identity IS the letter-grade system, so ranking any other way there
    would reintroduce the cross-market inversion that was fixed for it directly. This widget's
    own name and purpose are different: someone glancing at "Tonight's top leans" is asking
    "what's likely to hit," not "what has the biggest edge relative to a market-typical rate."

    Still only draws from plays that clear conviction_to_grade's own real floor (a play must
    already have SOME real, validated edge to be graded at all) -- this isn't "any probability,
    no matter how thin the edge," it's "the most likely to hit, among plays that already have
    real edge behind them."

    per_market caps how many of the SAME market can appear, so one especially safe-looking
    market (e.g. a high-probability, low-edge one) can't fill the entire list by itself -- the
    real reason "Best two leans from each market" exists as a design choice, not just this
    function's own default.

    Returns a flat list, already sorted by ModelProb descending, with each play carrying its own
    "_grade" (from conviction_to_grade) attached."""
    graded = []
    for p in plays:
        g = conviction_to_grade(p.get("Conviction"), p.get("_ceiling"))
        if g:
            graded.append({**p, "_grade": g})
    graded.sort(key=lambda p: p.get("ModelProb", 0.0), reverse=True)

    picks: List[Dict] = []
    seen: Dict[str, int] = {}
    for p in graded:
        m = p.get("Market")
        if seen.get(m, 0) < per_market:
            picks.append(p)
            seen[m] = seen.get(m, 0) + 1
    return sorted(picks, key=lambda p: p.get("ModelProb", 0.0), reverse=True)


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

    SORT ORDER, at all three levels -- games, players within a game, and each player's own
    plays -- is by rank_value (the ceiling-normalized number conviction_to_grade already exposes
    for exactly this reason), NOT raw Conviction. A REAL, CONFIRMED FIX, not the original design:
    sorting by raw Conviction can genuinely invert against this function's own letter grades --
    a raw 2.5x on HR (ceiling ~9.09, a "B") can rank above a raw 1.8x on a near-50%-reference
    market (ceiling ~2.0, a genuine "A") purely because HR's own raw numbers run bigger, even
    though the SECOND play is the stronger one by conviction_to_grade's own logic. This page's
    entire identity is its letter grades, so "most interesting first" has to mean "highest real
    grade first," not "biggest raw number from whichever market happens to have the most
    headroom first."

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

    game_order = sorted(games.keys(), key=lambda g: max(p["_grade"]["rank_value"] for p in games[g]), reverse=True)

    out = []
    for game_label in game_order:
        game_plays = games[game_label]
        by_player: Dict[str, List[Dict]] = {}
        for pl in game_plays:
            by_player.setdefault(pl["Player"], []).append(pl)
        player_order = sorted(by_player.keys(),
                              key=lambda pn: max(p["_grade"]["rank_value"] for p in by_player[pn]),
                              reverse=True)
        players = []
        for player in player_order:
            player_plays = sorted(by_player[player], key=lambda p: p["_grade"]["rank_value"], reverse=True)
            players.append({"player": player, "team": player_plays[0].get("Team", ""),
                           "plays": player_plays})
        out.append({"game": game_label, "players": players})
    return out


def top_picks_by_grade(organized: List[Dict[str, Any]], letters=("A", "B", "C"),
                       top_n: int = 5) -> List[Dict[str, Any]]:
    """A curated "look here first" summary, added directly on request for Graded Picks --
    flattens organize_graded_picks' own nested game/player/plays output back into a single list
    (every play there already carries its own real "_grade" from that same function, no
    re-grading here), then returns the top `top_n` per letter grade, sorted by real ModelProb --
    probability of actually hitting, not raw Conviction or rank_value. Same real fix already
    made to Best Bets and Command Center's own Top Leans: Conviction is relative to a market's
    own typical reference rate, not an absolute likelihood, and "what's actually worth a look"
    should lead with "how likely is this," not "how much better than typical is this market's
    own reference rate."

    NOT a replacement for the game-by-game board this same function's caller already builds --
    this is a curated SUMMARY sitting above it, not instead of it; the full board underneath
    still shows every game and every grade exactly as it always has. See organize_graded_picks'
    own docstring for why a flat ranked list was deliberately avoided as the page's ONLY view in
    the first place -- that reasoning doesn't disappear just because a summary now also exists.

    letters: which grades to include, and in what order -- defaults to A/B/C, deliberately
    excluding D. D is this platform's own explicit "still worth a look, proceed with real
    caution" floor (the lowest grade conviction_to_grade's own threshold allows at all) -- a
    curated "look here first" summary featuring D picks with the same visual weight as A's and
    B's would undercut the entire reason the letter grade exists. A REAL, VISIBLE, ADJUSTABLE
    floor, not a hardcoded rule baked into this function -- a caller can pass letters=("A", "B",
    "C", "D") to include D too, exposed as a real, visible UI control, not a silent default a
    person can't see or change.

    Returns a list of {"letter": str, "picks": [play, ...]}, one entry per letter in `letters`
    that has at least one real graded play -- a letter with zero plays right now is simply
    absent from the output, not included as a misleading empty section."""
    flat: List[Dict[str, Any]] = [pl for entry in organized for player_entry in entry["players"]
                                  for pl in player_entry["plays"]]

    by_letter: Dict[str, List[Dict[str, Any]]] = {}
    for pl in flat:
        by_letter.setdefault(pl["_grade"]["letter"], []).append(pl)

    out = []
    for letter in letters:
        picks = by_letter.get(letter, [])
        if not picks:
            continue
        picks_sorted = sorted(picks, key=lambda p: p.get("ModelProb", 0.0), reverse=True)
        out.append({"letter": letter, "picks": picks_sorted[:top_n]})
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


def hit_miss_by_market(graded_plays: List[Dict], min_grade_letter: str = "C") -> List[Dict]:
    """Takes ALREADY-GRADED plays (retro.grade_slate's own output -- each carrying "Hit":
    True/False/None, "Market", "Side", "Conviction", and "_ceiling") and buckets settled,
    real-graded plays into per-(market, side) hit/miss counts -- added directly on request for
    a dashboard showing "how did the tool's actual recommendations do last night, broken down
    by market."

    Groups by (market, side) TOGETHER, not market alone -- a REAL, CONFIRMED FIX, not a
    preemptive one: grouping by market alone was found to pool Over and Under picks for the
    same market into one bucket, even though they have genuinely different reference rates
    (e.g. Batter Total Hits Over is ~65% typical, Under is ~35%) and therefore different
    grading ceilings. A "C" grade means a different real confidence level on each side, so
    pooling them muddies the letter-grade signal -- confirmed directly against a real slate
    where Batter Total Hits' C and D grades converged to nearly identical hit rates (58% vs
    58%), which is exactly the symptom two differently-calibrated populations averaged together
    would produce, not a sign the grading itself was wrong.

    min_grade_letter: the SAME letter-grade floor Suggested Parlays/Graded Picks already use
    to mean "a real recommendation" (default "C", matching Suggested Parlays' own default) --
    "C or better" here means A, B, or C, using GRADE_THRESHOLDS' own ordering, not a separately
    invented cutoff. This is a deliberate choice, not an oversight: without it, a market's pie
    chart would be diluted by every candidate play the model ever considered, most of which were
    never real picks anyone would have acted on -- undersells what the model's actual
    recommendations did. D-grade and ungraded (None) plays are excluded entirely.

    Only SETTLED plays (Hit is not None) count toward hits/misses -- an unsettled or ungradeable
    play is silently excluded, never counted as a miss.

    Returns one entry per (market, side) that has at least one real, settled, C-or-better play:
    [{"market", "side", "label", "hits", "misses"}, ...], sorted by total plays descending
    (busiest first). "side" is None (and "label" is just the market name) for plays that never
    carried a Side field at all -- graceful, not an error, since not every market necessarily
    has a distinct Over/Under framing. A (market, side) pair with zero qualifying plays is
    simply absent -- never a fabricated 0-0."""
    letters_in_order = [letter for _, letter, _ in GRADE_THRESHOLDS]
    if min_grade_letter not in letters_in_order:
        min_grade_letter = "C"
    cutoff_idx = letters_in_order.index(min_grade_letter)
    allowed_letters = set(letters_in_order[:cutoff_idx + 1])

    settled = [g for g in graded_plays if g.get("Hit") is not None]
    by_bucket: Dict[tuple, Dict] = {}
    for g in settled:
        grade = conviction_to_grade(g.get("Conviction"), g.get("_ceiling"))
        if not grade or grade["letter"] not in allowed_letters:
            continue
        mkt = g.get("Market")
        if mkt is None:
            continue
        side = g.get("Side")
        key = (mkt, side)
        label = f"{mkt} — {side}" if side else mkt
        rec = by_bucket.setdefault(key, {"market": mkt, "side": side, "label": label,
                                        "hits": 0, "misses": 0})
        if g["Hit"]:
            rec["hits"] += 1
        else:
            rec["misses"] += 1
    return sorted(by_bucket.values(), key=lambda r: -(r["hits"] + r["misses"]))



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
    (2, "Safer", "safety", None),
    (3, "Steady", "safety", None),
    (4, "Balanced", "conviction", None),
    (5, "Bold", "payout", "C"),
    (6, "Longshot", "payout", "C"),
]   # A REAL, SECOND REDESIGN, not the original approach: the first version (non-overlapping
   # slices of ONE ranked-by-conviction list) fixed leg reuse, but every tier was still
   # optimizing for the exact same thing -- just handing out consecutive chunks of the same
   # queue. Real feedback was that this could still read as mechanical, not genuinely
   # differentiated: a sharp person could notice Longshot's legs were simply Safer's leftovers,
   # not picks chosen FOR being longshots. Each tier now has its OWN real objective (see
   # _tier_sort_key below for exactly what each one optimizes for), so "Safer" actually means
   # "ranked by real probability of hitting" and "Longshot" actually means "ranked by real
   # payout size, among plays that still clear the grading floor" -- not just "fewer vs more of
   # the identical ranking." Leg/player uniqueness across tiers is still a hard rule (see
   # build_suggested_parlays), unchanged from the first redesign -- that part was never the
   # problem, only "every tier ranks the same way" was.
   #
   # The 4th element (min_grade) is a REAL, second fix, found via a real reported example: with
   # only Batter HR selected, "payout" tiers were picking the WORST, barely-D-grade HR legs
   # specifically because they had the longest odds, with zero regard for whether the play had
   # any real edge at all -- chaining several genuinely bad, barely-qualifying longshots produced
   # combined odds no real book would offer and no real person would bet (seven-figure American
   # odds). "Payout-conscious" was always meant to mean "real, validated picks that happen to
   # have bigger prices," not "the worst plays that still technically clear the floor" -- Bold/
   # Longshot now require at least a real "C" grade before a play is even eligible for the
   # payout ranking, so the biggest-payout search happens within a pool of genuinely
   # well-graded plays, not the bottom of the barrel.
GRADE_RANK = {letter: len(GRADE_THRESHOLDS) - i for i, (_, letter, _) in enumerate(GRADE_THRESHOLDS)}
# {"A": 4, "B": 3, "C": 2, "D": 1} -- higher is better, derived directly from GRADE_THRESHOLDS'
# own real order rather than a second, separately-maintained ranking that could drift out of sync.


def _tier_sort_key(objective: str):
    """Returns a sort key function for one tier's real objective, all oriented so LARGER key
    value sorts FIRST under sort(..., reverse=True) -- a consistent convention across all three
    objectives, not three different sort directions to keep straight.

    "safety": raw ModelProb descending -- the actual probability of the leg hitting, NOT
    Conviction. This is a real, deliberate distinction: Conviction measures edge relative to a
    market-typical reference rate, not how likely a play is in absolute terms. A rare-market prop
    with huge relative edge (say a 25% HR chance vs an ~11% typical rate) can carry real
    Conviction while still being a genuinely risky, likely-to-lose single leg -- exactly wrong for
    a tier that's supposed to mean "safe." Ranking by raw ModelProb instead means Safer/Steady
    actually surface the plays most likely to simply happen, which is what "safer" should mean.

    "payout": raw ModelProb ASCENDING (achieved by negating it, so the sort stays reverse=True
    throughout) -- among plays that still cleared the real grading floor (a real edge, not a
    fabricated one), favor the ones with the LOWEST probability, since lower probability means a
    bigger real payout. This is deliberately different from "worst available play with no edge
    at all" -- every candidate here already passed conviction_to_grade, so this chases genuine
    upside within real, validated picks, the way a person actually building a longshot parlay
    would: real analytical backing, bigger number attached.

    "conviction": the ORIGINAL metric (edge relative to reference, ceiling-normalized into a real
    letter grade) -- Balanced sits in the middle, a genuine blend of "likely to hit" and "real
    value," not leaning hard toward either end the way Safer/Longshot now deliberately do."""
    if objective == "safety":
        return lambda p: p.get("ModelProb", 0.0)
    if objective == "payout":
        return lambda p: -p.get("ModelProb", 1.0)
    return lambda p: p.get("Conviction", 0.0)   # "conviction" / any unrecognized objective


def build_parlay_leg_pool(plays: List[Dict], max_per_game: int = 2, max_per_market: int = 2,
                          min_pool_size: int = 0, sort_key=None,
                          exclude_players: Optional[set] = None,
                          min_grade_letter: Optional[str] = None) -> List[Dict]:
    """Rank graded plays (by sort_key, defaulting to Conviction descending), then walk them
    building a pool that's actually SAFE to combine into parlays: at most ONE leg per player (a
    hard constraint -- see this section's own module-level comment for why this is the single
    most important rule here, not a minor detail), at most max_per_game legs sharing a game (a
    real but weaker correlation concern -- two different hitters on opposing teams in the same
    game can share some game-script/weather correlation, but nowhere near as severe as a
    same-player pairing), and at most max_per_market legs sharing a market (keeps a parlay from
    reading as six home-run bets in a trenchcoat -- default tightened from 3 to 2 after a real,
    concrete example: Stolen Bases is a genuinely high-variance market, so an elite base
    stealer's conviction ratio can run well above an elite slugger's HR conviction for a similar
    raw probability, not because either model is wrong, but because SB really is a more skewed
    market than HR. Left unconstrained, that skew let three different burners' SB legs alone fill
    an entire tier before any other market appeared, reading as far less realistic than what a
    person would actually build themselves).

    sort_key: how to rank candidates before applying the diversity caps -- defaults to Conviction
    descending (the original behavior) when not supplied. A caller building several tiers with
    genuinely different RISK OBJECTIVES (not just different sizes) passes its own sort_key here
    -- see _tier_sort_key for the real objectives this platform actually uses (safety/payout/
    conviction). Always used with reverse=True, so a sort_key should orient its own values so
    LARGER means "should be picked first" for whatever this tier is optimizing for.

    exclude_players: an optional set of (Player, Team) tuples to skip entirely -- e.g. players
    already used by an earlier-built tier. Lets a caller build several DISTINCT, non-overlapping
    tiers (each with its own objective) without this function needing to know anything about
    "tiers" itself; it just excludes whatever it's told to.

    min_pool_size: a REAL, reported bug this parameter fixes -- fixed caps alone silently strand
    a person who deliberately narrows Suggested Parlays down to one market (or a thin slate with
    few games): with max_per_market=2, selecting ONLY "Pitcher Strikeouts" caps the whole pool at
    2 legs total, even if 6 different real, graded pitchers exist that night, because the cap was
    designed to force diversity ACROSS markets, not to punish someone who already chose to narrow
    to one. When min_pool_size > 0, max_per_game and/or max_per_market are LOOSENED (never
    tightened) just enough to make a pool of that size achievable, given how many DISTINCT games
    and markets are actually present among the CANDIDATE plays (after exclude_players has already
    been applied, so this reflects what's genuinely still available to this specific tier, not
    the whole board). If there are genuinely enough distinct games/markets already, the original
    caps are used unchanged.

    Returns a FLAT, ranked list -- not grouped by game the way organize_graded_picks is, since
    parlay legs are chosen across the WHOLE board at once, not within one game.

    Player uniqueness is keyed on (Player, Team), not Player alone -- two genuinely different
    people can share a common name across different teams, and keying on name alone could
    wrongly treat them as the same person and drop one for no real reason.

    min_grade_letter: a REAL, second fix found via a real reported example -- restricts the
    candidate pool to plays graded at or above this letter (A/B/C/D) BEFORE any sort_key ranking
    happens. Without this, a "payout" objective ranking purely by lowest probability would pick
    the WORST, barely-qualifying plays specifically because they have the longest odds, with zero
    regard for whether they have any real edge -- on a narrow market selection (e.g. only Batter
    HR), this produced parlays built entirely from barely-D-grade legs and seven-figure American
    odds no real book would offer. See PARLAY_TIER_SIZES' own comment for the full story."""
    graded = []
    for pl in plays:
        grade = conviction_to_grade(pl.get("Conviction"), pl.get("_ceiling"))
        if grade:
            graded.append({**pl, "_grade": grade})

    if min_grade_letter:
        min_rank = GRADE_RANK.get(min_grade_letter, 0)
        graded = [p for p in graded if GRADE_RANK.get(p["_grade"]["letter"], 0) >= min_rank]

    exclude_players = exclude_players or set()
    graded = [p for p in graded if (p.get("Player"), p.get("Team")) not in exclude_players]

    key_fn = sort_key if sort_key is not None else (lambda p: p.get("Conviction", 0.0))
    graded.sort(key=key_fn, reverse=True)

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


# ===========================================================================
# SPECULATIVE BASKET -- a real, deliberate DIFFERENT product from Suggested Parlays, not a
# variation on it. A parlay requires every single leg to hit simultaneously -- real, punishing
# "AND" logic that multiplies several real risks together. That's not how a trader actually
# deploys speculative capital in penny stocks or crypto: nobody buys several speculative
# positions and needs ALL of them to pay off on the same day to call it a win. The real strategy
# is several small, INDEPENDENT, high-upside positions, sized small, where hitting even ONE
# makes the whole basket worthwhile -- diversifying across real risk, not multiplying it.
#
# Reuses the EXACT SAME leg-selection mechanism already proven for Suggested Parlays' own Bold/
# Longshot tiers (the "payout" objective from _tier_sort_key, ranking by lowest real probability
# among plays that still clear a real grade floor) -- same real, validated picks Bold/Longshot
# already surface, just presented as their own independent things instead of chained together.
def basket_prob_at_least_one_wins(legs: List[Dict]) -> float:
    """P(at least one leg hits), ASSUMING INDEPENDENCE -- the actual "basket" analog of a
    parlay's combined_parlay_prob, but for the opposite question: not "did everything hit"
    (an AND of every leg), but "did ANYTHING hit" (an OR across every leg) -- the real question
    that matters for a basket of independent positions, where a single winner makes the whole
    basket worthwhile. P(at least one) = 1 - P(none hit) = 1 - product(1 - p_i for each leg).

    Same independence caveat as combined_parlay_prob: build_parlay_leg_pool's own same-player
    exclusion removes the worst, most severe correlation violation before this math runs, but
    same-game-different-player legs can still share weaker correlation this doesn't capture."""
    prob_none_hit = 1.0
    for leg in legs:
        prob_none_hit *= (1.0 - leg.get("ModelProb", 0.0))
    return 1.0 - prob_none_hit


def basket_win_count_distribution(legs: List[Dict]) -> List[float]:
    """Full probability distribution over how many legs in this basket win -- exact Poisson-
    binomial, not just the mean. "Expected winners" is this distribution's own mean (sum(k *
    P(k))) with the per-leg detail already thrown away; "P(at least one wins)" is just 1 - P(0).
    Both existing basket numbers are summaries of this richer thing, not independent facts --
    this is the actual object those two numbers are computed FROM, exposed directly so a caller
    can show the real shape (e.g. "2 or 3 winners together" can be a much more informative,
    honest answer than a single expected-value point estimate).

    Same independence assumption as every other basket/parlay probability function in this
    module -- see basket_prob_at_least_one_wins's own docstring for the honest caveat that
    still applies here.

    DP recursion: dp[k] after processing i legs = P(exactly k of the first i legs won). Starts
    at dp = [1.0] (0 legs processed, exactly 0 wins with certainty) and grows by one slot per
    leg -- each leg either misses (k stays put, weight 1-p) or hits (k moves up one, weight p).
    O(n^2), fine at real basket sizes (a handful up to ~15 legs); not built for anything larger.

    Returns a list of length len(legs)+1 where index k = P(exactly k legs win), summing to 1.0
    up to floating-point error. Empty legs returns [1.0] (P(0 wins) = 1, trivially true of an
    empty basket)."""
    dp = [1.0]
    for leg in legs:
        p = leg.get("ModelProb", 0.0)
        new_dp = [0.0] * (len(dp) + 1)
        for k, mass in enumerate(dp):
            new_dp[k] += mass * (1.0 - p)
            new_dp[k + 1] += mass * p
        dp = new_dp
    return dp


def build_game_coverage_picks(plays: List[Dict], market: str = "Batter Total Hits",
                              side: str = "Over") -> List[Dict]:
    """For EACH distinct game in `plays`, pick the SINGLE highest-ModelProb play matching the
    given market/side -- "who is the safest hitter to get at least one hit, in each game,"
    added directly on request after a real, reported gap: a real strategy (one safe hit pick
    per game, within a time window, confirmed against actual placed bets at real book prices --
    -175 to -329, 64-77% real implied probability) produced picks that mostly didn't clear
    conviction_to_grade's own floor at all, or barely registered as a "D." Half of those real
    picks graded None outright.

    A REAL, DELIBERATE DEPARTURE from every other selection function in this module: this does
    NOT require clearing conviction_to_grade's own floor, and does not use "whichever side is
    favored" the way build_best_bets and everything downstream of it does. That floor and that
    side-selection both measure REAL EDGE relative to a market-typical reference -- but "given
    I'm making one pick per game regardless, who's the safest option available" is a genuinely
    different question the edge-based grading system was never built to answer. Total Hits'
    own reference (0.65) is already high, so even a real, good 70-77% pick barely beats
    "typical" -- it can be a perfectly sound, safe pick and still show almost no edge, since edge
    is the only thing conviction_to_grade measures.

    Still attaches "_grade" (from conviction_to_grade, honestly None when a pick doesn't clear
    the real floor) so a caller can show it -- "this is the safest option in this specific game,
    even though it doesn't carry a validated edge by this platform's own definition" is an
    honest, useful thing to display, not something to hide.

    Filters to the EXACT specified market/side, not the play's own favored side, since a
    coverage strategy specifically wants the Over side on a hits-type market for every game, not
    whichever side happens to carry more edge in each individual matchup. A game with no play at
    all for the given market/side is simply absent from the result -- never a fabricated pick.

    Returns one play per game, sorted by ModelProb descending (highest-probability coverage
    picks first), each carrying "_grade" (possibly None)."""
    best_by_game: Dict[str, Dict] = {}
    for pl in plays:
        if pl.get("Market") != market or pl.get("Side") != side:
            continue
        g = pl.get("Game")
        if g is None:
            continue
        current_best = best_by_game.get(g)
        if current_best is None or pl.get("ModelProb", 0.0) > current_best.get("ModelProb", 0.0):
            best_by_game[g] = pl

    picks = []
    for pl in best_by_game.values():
        grade = conviction_to_grade(pl.get("Conviction"), pl.get("_ceiling"))
        picks.append({**pl, "_grade": grade})
    return sorted(picks, key=lambda p: p.get("ModelProb", 0.0), reverse=True)


def build_game_coverage_parlay(plays: List[Dict], market: str = "Batter Total Hits",
                               side: str = "Over") -> Dict[str, Any]:
    """Chains build_game_coverage_picks' one-safest-pick-per-game selection into a SINGLE,
    all-must-hit parlay -- added directly on request: Suggested Parlays' own tiers chase either
    safety or payout as an OBJECTIVE among plays that already clear a real edge floor, but a
    real, reported strategy (covering every game with its own safest pick) isn't really chasing
    payout at all, and mostly doesn't clear that floor to begin with -- the same real gap
    Speculative Basket's own Game Coverage mode was built to answer, but chained into one ticket
    instead of shown as independent positions, since Suggested Parlays' whole page is about a
    combined, all-must-hit parlay.

    SAFE to combine this way, unlike the same-player, cross-market case a real reported SGP
    example surfaced (a pitcher's own Strikeouts and Outs combined, which this platform
    deliberately refuses to price since they're not close to independent): build_game_coverage_
    picks already guarantees at most one leg per game, so every leg here comes from a genuinely
    different game -- the same level of independence Suggested Parlays' own tiers already accept
    (see combined_parlay_prob's own docstring for the honest caveat that even different-game
    legs can share weaker correlation this doesn't fully capture, which still applies here).

    Returns the same shape as one entry from build_suggested_parlays' own output --
    {"tier": "Game Coverage", "size": int, "legs": [...], "combined_prob": float,
    "combined_fair_decimal": float, "combined_fair_american": int} -- so Suggested Parlays' own
    view can render this exactly like any other tier, no new display logic needed. "legs" is
    empty (and combined_prob is 0.0) when no game in `plays` has a play matching the requested
    market/side -- never a fabricated parlay."""
    from projections import prob_to_decimal, prob_to_american   # same lazy-import pattern as
                                                                 # build_suggested_parlays, for
                                                                 # the same real circular-import
                                                                 # reason
    legs = build_game_coverage_picks(plays, market=market, side=side)
    combined_prob = combined_parlay_prob(legs) if legs else 0.0
    return {
        "tier": "Game Coverage", "size": len(legs), "legs": legs,
        "combined_prob": round(combined_prob, 4),
        "combined_fair_decimal": prob_to_decimal(combined_prob) if legs else None,
        "combined_fair_american": prob_to_american(combined_prob) if legs else None,
    }


def build_speculative_basket(plays: List[Dict], size: int = 8, min_grade_letter: Optional[str] = "C",
                             max_per_game: int = 2, max_per_market: int = 2) -> Dict[str, Any]:
    """Build a basket of INDEPENDENT, single high-upside positions -- not a chained parlay.
    Reuses build_parlay_leg_pool's exact same mechanism already proven for Suggested Parlays'
    own Bold/Longshot tiers: ranks candidates by the "payout" objective (lowest real probability,
    i.e. the biggest real price) among plays that clear min_grade_letter (defaults to "C", the
    same real floor Bold/Longshot use, added specifically after a real reported issue where an
    unconstrained payout search picked the worst, barely-qualifying legs purely for their long
    odds -- see PARLAY_TIER_SIZES' own comment for the full story this floor exists to prevent).

    size: how many independent positions to include -- a real, user-controlled choice (a trader
    decides how many positions to hold), not a fixed tier the way parlay sizes are.

    Returns {"legs": [play, ...], "prob_at_least_one_wins": float, "expected_winners": float}.
    "expected_winners" is the real, honest sum of each leg's own probability (linearity of
    expectation holds regardless of correlation) -- "on average, about this many of these
    positions would settle correctly," a real, useful basket-level number distinct from "at
    least one." Deliberately NOT named "expected_hits" (an earlier version was) -- that name
    reads as "expected baseball hits," which is actively wrong and confusing when the basket
    contains Under legs, non-hits markets like Runs/RBI/H-R-R, or any mix of sides: this number
    is "how many of these bets are expected to WIN," regardless of which side each one favors,
    not a baseball statistic."""
    key_fn = _tier_sort_key("payout")
    pool = build_parlay_leg_pool(plays, max_per_game, max_per_market, min_pool_size=size,
                                 sort_key=key_fn, min_grade_letter=min_grade_letter)
    legs = pool[:size]
    return {
        "legs": legs,
        "prob_at_least_one_wins": round(basket_prob_at_least_one_wins(legs), 4),
        "expected_winners": round(sum(leg.get("ModelProb", 0.0) for leg in legs), 2),
    }


def build_suggested_parlays(plays: List[Dict], tier_sizes: Optional[List] = None,
                            max_per_game: int = 2, max_per_market: int = 2) -> List[Dict]:
    """Build tiered parlay suggestions from a graded plays list -- the actual feature: someone
    who doesn't want to comb through the board themselves gets a few ready-made options instead.

    tier_sizes defaults to PARLAY_TIER_SIZES: (2, "Safer", "safety", None), (3, "Steady",
    "safety", None), (4, "Balanced", "conviction", None), (5, "Bold", "payout", "C"), (6,
    "Longshot", "payout", "C"). Each tier is built as its OWN, independently-ranked pool
    (build_parlay_leg_pool, called once per tier with that tier's own sort key from
    _tier_sort_key and its own min_grade_letter floor) -- not slices of one shared ranking. Legs
    already used by an earlier (smaller) tier are excluded from every later tier's own pool, so
    no leg or player ever appears in more than one tier, but each tier's remaining candidates are
    ranked by what THAT tier actually cares about, not by a single universal metric.

    A REAL, SECOND DELIBERATE REDESIGN, not the original approach: an earlier version made every
    tier a non-overlapping SLICE of one Conviction-ranked list -- a real fix for the previous
    problem (identical picks reappearing across every tier), but every tier was still optimizing
    for the exact same thing, just handing out consecutive chunks of the same queue. That could
    still read as mechanical: a sharp person could notice Longshot's legs were simply whatever was
    left over from Safer, not picks chosen FOR being longshots. Each tier now has a genuinely
    different objective -- Safer/Steady rank by real probability of hitting (raw ModelProb, not
    Conviction, which measures relative edge rather than absolute likelihood), Balanced uses the
    original Conviction metric as a real middle ground, and Bold/Longshot rank by payout size
    (lowest ModelProb, i.e. the biggest real price) AMONG plays that clear a real "C" grade floor
    -- chasing genuine upside within real, validated picks, not just grabbing whatever has the
    longest odds regardless of quality (see PARLAY_TIER_SIZES' own comment for the real reported
    example that made the "C" floor necessary: without it, a narrow market selection could
    produce parlays built entirely from the worst, barely-qualifying legs). See _tier_sort_key's
    own docstring for the full reasoning behind each objective.

    Tiers are still processed smallest-to-largest, and a tier is SKIPPED ENTIRELY, not padded
    with weaker plays, when its own pool (after excluding players already claimed by earlier
    tiers, and after its own min_grade_letter floor) can't reach its size -- but unlike the
    earlier slice-based design, one tier failing does NOT automatically doom every later tier,
    since each has its own independent ranking and might find enough real candidates even if an
    earlier tier's narrower objective didn't.

    Calls build_parlay_leg_pool once per tier with min_pool_size set to that tier's own size (not
    the sum across every tier, since each tier now draws from its own independently-filtered
    pool, not a single shared one) -- still fixes the same real reported bug where selecting a
    narrow set of markets could otherwise silently cap a pool below what's actually achievable.

    Returns a list of {"tier": str, "size": int, "legs": [play, ...], "combined_prob": float,
    "combined_fair_decimal": float, "combined_fair_american": int}, one entry per tier that could
    actually be filled, in ascending size order."""
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
    sizes = sorted(tier_sizes if tier_sizes is not None else PARLAY_TIER_SIZES, key=lambda x: x[0])

    out = []
    used_players: set = set()
    for size, label, objective, min_grade in sizes:
        key_fn = _tier_sort_key(objective)
        candidates = build_parlay_leg_pool(plays, max_per_game, max_per_market,
                                           min_pool_size=size, sort_key=key_fn,
                                           exclude_players=used_players,
                                           min_grade_letter=min_grade)
        if len(candidates) < size:
            continue   # this specific tier can't be honestly filled -- but a LATER tier, with
                      # its own different objective, might still find enough real candidates
        legs = candidates[:size]
        for pl in legs:
            used_players.add((pl.get("Player"), pl.get("Team")))
        combined_prob = combined_parlay_prob(legs)
        out.append({
            "tier": label, "size": size, "legs": legs,
            "combined_prob": round(combined_prob, 4),
            "combined_fair_decimal": prob_to_decimal(combined_prob),
            "combined_fair_american": prob_to_american(combined_prob),
        })
    return out
