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


def conviction_to_grade(conviction: Optional[float]) -> Optional[Dict[str, Any]]:
    """Map a play's Conviction number to a letter grade + tier label for quick visual scanning --
    NOT a fabricated 0-100 "score" that doesn't map to anything real. The raw Conviction number
    (e.g. "3.2x") is a genuinely interpretable value on its own -- "this play's real probability
    is 3.2x the market-typical rate for this prop" -- so the grade is presented ALONGSIDE it, not
    instead of it, honest about what's actually driving the label rather than hiding it behind an
    opaque score.

    A REAL, DELIBERATE NAMING CHOICE: labels here ("Top Lean" / "Strong Lean" / "Lean" / "Watch")
    are this platform's own wording, chosen specifically to describe the SAME underlying concept
    (a tiered conviction label) without reusing another product's specific badge text -- avoiding
    exactly the "duplicating someone else's badges" concern raised directly during scoping, not
    just applied to the genuinely unclear proprietary terms ("Blast Match" etc, deliberately left
    out entirely) but to the clearer ones too.

    SPORT-AGNOSTIC BY DESIGN: takes a plain Conviction number, not a sport-specific row shape --
    works identically whether the play came from MLB, WNBA, NBA, NFL, or NCAAMB's own build_best_
    bets, since Conviction means the same thing (ModelProb / a market-typical reference rate) in
    every one of them.

    Returns None for anything below the lowest real threshold (1.2x, matching Best Bets' own
    established "worth showing at all" floor) -- a play that isn't notable shouldn't get a grade
    that implies it is."""
    if conviction is None:
        return None
    for threshold, letter, tier in GRADE_THRESHOLDS:
        if conviction >= threshold:
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
        grade = conviction_to_grade(pl.get("Conviction"))
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
        grade = conviction_to_grade(g.get("Conviction"))
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
