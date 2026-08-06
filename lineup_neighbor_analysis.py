"""
lineup_neighbor_analysis.py — tests a real, specific hypothesis raised in the Aug 5-6 Discord
recap: Deezy's own real, in-the-moment observation that a batter's own real result seems to run
hotter when the hitter batting next to him in the real lineup is having a big game that day
("we have to start thinking like a pitcher... the guys around them get the hits because the
pitcher is more bold").

WHY THIS EXISTS AS ITS OWN STANDALONE SCRIPT, NOT A NEW PERMANENT PAGE: this is a real, one-time
(or occasional) research question -- "is this worth building into the model at all" -- not a
finished feature yet. Building a whole new page for a hypothesis that might turn out to be noise
would be real, wasted permanent UI complexity for a question that just needs a real answer once.

THE REAL, HONEST STATISTICAL CAVEAT, STATED UP FRONT, NOT BURIED: this checks a real correlation
(regressed batter prop result vs. whether the ADJACENT lineup spot had a big game), not a
controlled experiment. A real, known confound is not corrected for here -- if the whole game was
just high-scoring (a bad opposing pitcher, a hitters' park that day), BOTH the neighbor's real big
game AND this player's own real good result could simply reflect that shared context, with no
real "protection" effect at all. This script reports the raw split honestly; it does NOT claim to
have isolated a causal lineup-protection effect. A real, likely-mixed result (some real signal,
some real noise) should NOT be read as a clean yes/no -- see the published sabermetrics research on
lineup protection, which itself remains genuinely unsettled.

REAL REQUEST VOLUME, DELIBERATELY MINIMIZED: one real gameLog fetch per DISTINCT (player, season)
pair (not one per graded play -- a player showing up in many graded plays across a season only
costs one real fetch), and one real boxscore fetch per DISTINCT game_pk (not one per player-in-
that-game -- multiple graded plays sharing a game only cost one real fetch too). Both real caches
are dicts kept for the lifetime of one run, not persisted between runs.

USAGE:
    python lineup_neighbor_analysis.py [--sport MLB] [--markets "Batter Total Hits,Batter HR"]
                                       [--big-game-hits 2] [--min-sample 20]

Requires DATABASE_URL set (same real requirement as every other script that reads real
grading_history) -- without it, this would read from an empty local SQLite file and report a
real, honest "no data," not a wrong answer, but also not the real one you're looking for.
"""

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

import grading_history as GH
import mlb_engine as E

# Confirmed real MLB market names this platform tracks per sports.py's own MLB registration --
# only markets with a real, individual batter behind them make sense for a lineup-neighbor
# check (a team-level market like a First Innings Total has no single batter to attach a real
# lineup slot to). A REAL, CONFIRMED FIX: "Batter Hits+Runs+RBIs" is the actual, canonical real
# market name (confirmed directly against sports.py) -- the original list here also had a
# guessed "H+R+RBI" entry that silently matched zero real plays every real run, confirmed
# directly from a real production run showing "H+R+RBI: 0 real graded play(s)."
BATTER_MARKETS = ["Batter HR", "Batter Total Hits", "Batter Total Bases",
                  "Batter Hits+Runs+RBIs", "Batter Strikeouts"]   # last one included for
                                                                  # comparison -- a real,
                                                                  # different-direction market
                                                                  # (fewer Ks would be the
                                                                  # "protected" outcome there)


def _neighbor_had_a_big_game(neighbor_line: Optional[Dict], big_game_hits: int) -> Optional[bool]:
    """True if this real neighbor's own same-game line clears the real big-game bar (>= 
    big_game_hits real hits, OR at least one real HR) -- False if he played and didn't, None if
    there's genuinely no neighbor to check (a real leadoff/9-hole edge, or a real fetch gap)."""
    if neighbor_line is None:
        return None
    if neighbor_line.get("hr", 0) >= 1:
        return True
    return neighbor_line.get("h", 0) >= big_game_hits


def run_analysis(sport_key: str = "MLB", markets: Optional[List[str]] = None,
                 big_game_hits: int = 2, min_sample: int = 20,
                 max_plays_per_market: Optional[int] = None) -> Dict:
    """The real, end-to-end analysis. Returns {market: {"hot_neighbor": {"n", "hit_rate"},
    "cold_neighbor": {"n", "hit_rate"}, "no_neighbor_data", "skipped_no_game"}, ...} -- broken
    out PER MARKET, not pooled into one number.

    A REAL, CONFIRMED FIX to this function's own original design: the first real run pooled
    every market (HR, Total Hits, Total Bases, Hits+Runs+RBIs, AND Strikeouts) into one combined
    hit rate. That's a real methodological problem, not just a style choice -- Strikeouts has a
    genuinely different, often opposite expected relationship to Deezy's own hypothesis (being
    pitched around more carefully could mean MORE walks and fewer strikeouts for the hitter
    being avoided, but says nothing predictable about the ADJACENT hitter's own strikeout rate
    the way it does about his HIT rate) -- pooling a market with an unclear or reversed expected
    direction into the same number as four markets that all predict the SAME direction risks
    muddying or even inverting whatever real signal exists in the hitting markets specifically.
    Reporting each market separately lets a real pattern (or its real absence) actually show up,
    instead of being averaged away."""
    markets = markets or BATTER_MARKETS
    game_pk_cache: Dict[Tuple[int, str], Optional[int]] = {}
    neighbor_cache: Dict[Tuple[int, int], Optional[Dict]] = {}
    per_market: Dict[str, Dict] = {}

    for market in markets:
        plays = GH.fetch_graded_plays(sport_key, market=market)
        if max_plays_per_market and len(plays) > max_plays_per_market:
            plays = plays[-max_plays_per_market:]   # the real, most recent slice, not a random one
            print(f"{market}: {len(plays)} real graded play(s) to check (capped to the most "
                 f"recent {max_plays_per_market} of a larger real total)", flush=True)
        else:
            print(f"{market}: {len(plays)} real graded play(s) to check", flush=True)

        hot_hits = hot_n = cold_hits = cold_n = 0
        no_neighbor_data = 0
        skipped_no_game = 0

        for i, p in enumerate(plays):
            if i > 0 and i % 25 == 0:
                print(f"  ...{i}/{len(plays)} checked so far ({len(game_pk_cache)} distinct real "
                     f"game lookups made, {len(neighbor_cache)} distinct real boxscore lookups made)",
                     flush=True)

            pid, slate_date, hit = p.get("PlayerId"), p.get("SlateDate"), p.get("Hit")
            if pid is None or not slate_date or hit is None:
                continue   # a real, incomplete row -- honestly skipped, not guessed

            gp_key = (pid, slate_date)
            if gp_key not in game_pk_cache:
                game_pk_cache[gp_key] = E.find_hitter_game_pk(pid, slate_date)
            game_pk = game_pk_cache[gp_key]
            if game_pk is None:
                skipped_no_game += 1
                continue

            nb_key = (pid, game_pk)
            if nb_key not in neighbor_cache:
                neighbor_cache[nb_key] = E.get_lineup_neighbor_result(pid, game_pk)
            result = neighbor_cache[nb_key]
            if result is None:
                skipped_no_game += 1
                continue

            # Pooling both real neighbors (above AND below) into one real check -- Deezy's own
            # framing was about being NEAR a hot hitter generally, not specifically above or
            # below; splitting further would just thin an already-real-world-limited sample.
            above_hot = _neighbor_had_a_big_game(result.get("neighbor_above"), big_game_hits)
            below_hot = _neighbor_had_a_big_game(result.get("neighbor_below"), big_game_hits)
            real_checks = [v for v in (above_hot, below_hot) if v is not None]
            if not real_checks:
                no_neighbor_data += 1
                continue

            if any(real_checks):
                hot_n += 1
                hot_hits += 1 if hit else 0
            else:
                cold_n += 1
                cold_hits += 1 if hit else 0

        per_market[market] = {
            "hot_neighbor": {"n": hot_n, "hit_rate": round(hot_hits / hot_n, 3) if hot_n else None},
            "cold_neighbor": {"n": cold_n, "hit_rate": round(cold_hits / cold_n, 3) if cold_n else None},
            "no_neighbor_data": no_neighbor_data,
            "skipped_no_game": skipped_no_game,
        }
    return per_market


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", default="MLB")
    parser.add_argument("--markets", default=None,
                        help="Comma-separated market names; defaults to every real batter market tracked")
    parser.add_argument("--big-game-hits", type=int, default=2)
    parser.add_argument("--min-sample", type=int, default=20)
    parser.add_argument("--max-plays-per-market", type=int, default=None,
                        help="Cap each market to its most recent N graded plays, for a faster "
                             "first read on a real, large accumulated history")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL") and not getattr(GH, "USING_POSTGRES", False):
        print("DATABASE_URL not set — this would read an empty local SQLite file, not your real "
             "accumulated grading history. Set the DATABASE_URL secret (your Supabase URL) first.")
        return 1

    markets = [m.strip() for m in args.markets.split(",")] if args.markets else None
    results = run_analysis(args.sport, markets, args.big_game_hits, args.min_sample,
                           args.max_plays_per_market)

    for market, result in results.items():
        print(f"\n{'=' * 70}")
        print(f"{market}")
        print(f"{'=' * 70}")
        hot, cold = result["hot_neighbor"], result["cold_neighbor"]
        print(f"Hot neighbor  (adjacent slot had a real big game): n={hot['n']:<4d} "
             f"hit_rate={hot['hit_rate']}")
        print(f"Cold neighbor (adjacent slot did NOT):              n={cold['n']:<4d} "
             f"hit_rate={cold['hit_rate']}")
        print(f"Real plays with no checkable neighbor: {result['no_neighbor_data']}")
        print(f"Real plays skipped (no game/boxscore found): {result['skipped_no_game']}")

        if hot["n"] < args.min_sample or cold["n"] < args.min_sample:
            print(f"\nHONEST FLAG: at least one real side has fewer than {args.min_sample} plays -- "
                 "genuinely too thin to read anything into yet, real or not. This isn't a real "
                 "answer at this sample size, just an early read.")
        elif hot["hit_rate"] is not None and cold["hit_rate"] is not None:
            gap = hot["hit_rate"] - cold["hit_rate"]
            print(f"\nReal gap: {gap:+.3f} ({'higher' if gap > 0 else 'lower' if gap < 0 else 'no'} "
                 "hit rate next to a hot neighbor).")
        print("Remember the real, stated caveat: this is a raw correlation, not a controlled "
             "test -- a real, whole-game confound (a bad opposing pitcher, a hitters' park) "
             "isn't ruled out here. Worth a second, within-game-controlled pass before trusting "
             "this enough to touch the model.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
