"""
analyst_publisher.py — the scheduled, headless Analyst Desk: lock the day's calls, post the card, post the recap.

WHY: a reputation is built on showing up every day, and the Desk only posts when the owner opens the page and
presses a button. This is the same work done on a timer (a GitHub Action, see analyst-publish.yml), with the
same rules as the page:

  * only calls the chosen sportsbook really posts, at the model's own line, are locked or posted;
  * a call is locked only for a game that hasn't started (analyst_ledger.record_calls);
  * earlier days are graded first (settle_day), the same way the page does it;
  * the picks card carries the record fingerprint, the brand and the responsible-gambling line
    (analyst_tools.discord_picks_text), and the calls in it are stamped "published";
  * the recap covers the calls that were actually PUBLISHED, and its running record counts only those.

EACH MESSAGE GOES OUT ONCE. A post is claimed in the ledger (analyst_ledger.claim_post) before it is sent, so
overlapping runs and re-runs cannot post the same card twice; if the send fails the claim is given back and the
next run tries again. One card per sport per day: calls that only become available after it went out are on the
Desk but are not added to a second post.

SAFE BY DEFAULT: without --post nothing is written or sent — it prints what it would have posted. With --post
and no DISCORD_WEBHOOK_URL it refuses rather than locking calls it can't publish.

    python analyst_publisher.py                         # dry run, every enabled sport
    python analyst_publisher.py --post                  # lock, grade, post
    python analyst_publisher.py --post --sports NBA NFL --book fanduel

The page (views/39_Analyst_Desk.py) and this module build calls the same way (A.scan over the same board, offers,
game environment and matchups); test_analyst_publisher.py pins the shared behaviour.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Callable, Dict, List, Optional

import pytz

import analyst as A
import analyst_context as AC
import analyst_ledger as AL
import analyst_tools as AT
import odds_api as O
import sports

EASTERN = pytz.timezone("US/Eastern")
SETTLE_PER_RUN = 6          # earlier open days graded per sport per run (a backlog clears over a few runs)


def today_eastern() -> str:
    return datetime.now(EASTERN).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Dependencies (injected in tests; real modules by default)
# ---------------------------------------------------------------------------
def default_deps() -> Dict[str, Callable]:
    import best_bets_data as BBD
    import line_history

    def load_board(sport_key: str, d: str, book: str):
        if sport_key == "MLB":
            return BBD.load_mlb_best_bets_board(d, sports.get("MLB").engine.FIP_CONSTANT_DEFAULT, book, None, None)
        return BBD.load_generic_best_bets_board(sport_key, d, book)

    def fetch_offers(sport_key: str, d: str, key: str):
        return BBD.fetch_mlb_offers(d, key) if sport_key == "MLB" else BBD.fetch_generic_offers(sport_key, d, key)

    return {
        "api_key": BBD.get_odds_api_key,
        "load_board": load_board,
        "fetch_offers": fetch_offers,
        "game_env": lambda sport_key, d, meta, key: AC.load_game_env(sport_key, d, meta, key, sports.get(sport_key).odds_sport_key),
        "matchups": lambda sport_key, d: AC.load_matchups(sport_key, d, sports.get(sport_key).engine, sports.get(sport_key).projections),
        "history_fn": line_history.line_series,
        "results": lambda sport_key, d: sports.get(sport_key).engine.get_player_results(d),
    }


# ---------------------------------------------------------------------------
# Building the day's calls (the page's scan, headless)
# ---------------------------------------------------------------------------
def build_calls(sport_key: str, date_str: str, book: str, deps: Dict[str, Callable], evidence: bool = True) -> Dict:
    """{'calls': [...], 'notes': [...], 'n_games': int}. Never raises for a missing source: a source that fails
    only removes the angles that depend on it, and says so in `notes`."""
    notes: List[str] = []
    plays, meta, _books = deps["load_board"](sport_key, date_str, book)
    if sport_key in sports.WEEKLY_SLATE_SPORTS:                # the Desk's default scope is the picked date's games
        meta = sports.scope_filter(meta, lambda m: m.get("game_date"), date_str, sports.SCOPE_DATE)
        labels = {m.get("label") for m in meta}
        plays = [p for p in plays if p.get("Game") in labels]
    if not plays:
        return {"calls": [], "notes": ["no plays on the slate"], "n_games": 0}
    key = deps["api_key"]()
    offers = None
    if not key:
        notes.append("no Odds API key is configured, so book lines can't be checked")
    else:
        try:
            offers = deps["fetch_offers"](sport_key, date_str, key)
        except Exception as exc:                               # noqa: BLE001
            notes.append(f"the odds fetch failed ({str(exc)[:90]})")
    times = A.game_times(meta)
    for p in plays:
        times.setdefault(p.get("Game"), A.time_info(p.get("GameDate")))
    game_env, matchups = {}, {}
    if evidence:                                               # the heavy reads (a request per game; every opponent's games)
        try:
            game_env, n1 = deps["game_env"](sport_key, date_str, meta, key)
            matchups, n2 = deps["matchups"](sport_key, date_str)
            notes += [n for n in (n1, n2) if n]
        except Exception as exc:                               # noqa: BLE001
            notes.append(f"the extra evidence couldn't be loaded ({str(exc)[:90]})")
    weights = A.learned_weights(AL.fetch_calls(sport=sport_key, settled_only=True))
    calls = A.scan(plays, sport_key, date_str, offers=offers, odds_map=sports.get(sport_key).market_map,
                   history_fn=deps["history_fn"], weights=weights, expect_book_lines=bool(offers), times=times,
                   book=book, game_env=game_env, matchups=matchups)
    return {"calls": calls, "notes": notes, "n_games": len(meta)}


# ---------------------------------------------------------------------------
# One sport
# ---------------------------------------------------------------------------
def _published_recap_rows(sport_key: str, today_str: str) -> Optional[str]:
    """The latest day before today with at least one published call and every published call graded."""
    rows = [r for r in AL.fetch_calls(sport=sport_key) if r.get("published_at") and r["date"] < today_str]
    by_day: Dict[str, List[Dict]] = {}
    for r in rows:
        by_day.setdefault(r["date"], []).append(r)
    days = [d for d, rs in by_day.items() if all(r.get("settled_at") for r in rs)]
    return max(days) if days else None


def publish_sport(sport_key: str, date_str: str, today_str: str, deps: Dict[str, Callable], *, book: str,
                  webhook: Optional[str], post: bool, send: Optional[Callable] = None) -> Dict:
    """Run one sport end to end. Returns {sport, locked, picks: 'posted'|'already posted'|'nothing to post'|
    'dry run'|'failed: …', recap: …, graded, notes, text}. With post=False nothing is written or sent."""
    short = sports.get(sport_key).label.split(" — ")[0]
    book_name = O.book_label(book)
    out: Dict = {"sport": sport_key, "locked": 0, "graded": 0, "picks": "nothing to post", "recap": "nothing to post",
                 "notes": [], "text": {}}
    if post:
        res = AL.settle_open_days(sport_key, AL.unsettled_dates(sport_key, today_str),
                                  lambda d: deps["results"](sport_key, d), max_days=SETTLE_PER_RUN)
        out["graded"] += res["settled"]

    # Once the card is out the angles can't change what was posted; a later run only needs the book's current lines (for
    # the closing-line marks), so it skips the heavy evidence reads and the credits they cost.
    built = build_calls(sport_key, date_str, book, deps, evidence=not (post and AL.posted("picks", sport_key, date_str)))
    out["notes"] = built["notes"]
    cards = [c for c in built["calls"] if c["book_state"] == A.STATE_POSTED and AL.loggable(c, today_str)]
    if post and cards:
        out["locked"] = AL.record_calls(cards, today_str)
        try:
            AL.mark_calls(cards, today_str)
        except Exception:                                      # noqa: BLE001 — marking is best effort
            pass

    # --- the picks card --------------------------------------------------------------
    if cards:
        fp = AT.fingerprint_line(AL.fetch_calls())
        text = AT.discord_picks_text(cards, sport_label=short, date_str=date_str, book_label=book_name, extra_line=fp)
        out["text"]["picks"] = text
        if not post:
            out["picks"] = "dry run"
        elif AL.claim_post("picks", sport_key, date_str):
            try:
                AT.post_to_discord(webhook, text, post=send)
            except RuntimeError as exc:
                AL.release_post("picks", sport_key, date_str)
                out["picks"] = f"failed: {exc}"
            else:
                try:
                    AL.mark_published(AT.published_in_text(cards, text))
                except Exception:                              # noqa: BLE001 — the post went out; the stamp is best effort
                    pass
                out["picks"] = "posted"
        else:
            out["picks"] = "already posted"

    # --- the recap of the latest fully graded published day ----------------------------
    day = _published_recap_rows(sport_key, today_str)
    if day:
        rows = [r for r in AL.fetch_calls(sport=sport_key) if r["date"] == day and r.get("published_at")]
        board = A.scoreboard([r for r in AL.fetch_calls(sport=sport_key, settled_only=True) if r.get("published_at")])
        text = AT.discord_recap_text(rows, sport_label=short, date_str=day, board=board,
                                     extra_line=AT.fingerprint_line(AL.fetch_calls()))
        if text:
            out["text"]["recap"] = text
            if not post:
                out["recap"] = "dry run"
            elif AL.claim_post("recap", sport_key, day):
                try:
                    AT.post_to_discord(webhook, text, post=send)
                except RuntimeError as exc:
                    AL.release_post("recap", sport_key, day)
                    out["recap"] = f"failed: {exc}"
                else:
                    out["recap"] = "posted"
            else:
                out["recap"] = "already posted"
    return out


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def default_sports() -> List[str]:
    return [s.key for s in sports.enabled_sports() if s.has_projections]


def run(sport_keys: List[str], *, date_str: Optional[str] = None, book: Optional[str] = None, post: bool = False,
        webhook: Optional[str] = None, deps: Optional[Dict[str, Callable]] = None, send: Optional[Callable] = None,
        out=print, require_shared_db: bool = True) -> int:
    """Run every sport; returns a process exit code (1 when any sport errored or a post failed)."""
    today = today_eastern()
    date_str = date_str or today
    book = book or os.environ.get("ANALYST_BOOK") or O.DEFAULT_BOOK
    if post and not (webhook or "").strip():
        out("Refusing to run with --post: DISCORD_WEBHOOK_URL is not set, so calls would be locked that can't be published.")
        return 1
    if post and require_shared_db and not AL.USING_POSTGRES:
        out("Refusing to run with --post: DATABASE_URL is not set. Without the shared database the record and the "
            "'already posted' claims live in a file that disappears when this job ends, so the same card would be "
            "posted again on every run and the public record would not see these calls.")
        return 1
    deps = deps or default_deps()
    bad = 0
    for key in sport_keys:
        try:
            r = publish_sport(key, date_str, today, deps, book=book, webhook=webhook, post=post, send=send)
        except Exception as exc:                               # noqa: BLE001 — one sport never stops the others
            out(f"{key}: ERROR {type(exc).__name__}: {str(exc)[:160]}")
            bad += 1
            continue
        out(f"{key}: locked {r['locked']}, graded {r['graded']}, picks: {r['picks']}, recap: {r['recap']}"
            + (f" · {'; '.join(r['notes'])}" if r["notes"] else ""))
        if r["picks"].startswith("failed") or r["recap"].startswith("failed"):
            bad += 1
        if not post:
            for kind, text in r["text"].items():
                out(f"--- {key} {kind} (dry run) ---\n{text}\n")
    return 1 if bad else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Lock, grade and post the Analyst Desk's daily card and recap.")
    ap.add_argument("--post", action="store_true", help="write the record and post to Discord (default: dry run)")
    ap.add_argument("--sports", nargs="*", help="sport keys (default: every enabled sport with projections)")
    ap.add_argument("--date", help="slate date YYYY-MM-DD (default: today, US/Eastern)")
    ap.add_argument("--book", help="sportsbook key (default: ANALYST_BOOK or the platform default)")
    args = ap.parse_args(argv)
    keys = [k.upper() for k in (args.sports or os.environ.get("ANALYST_SPORTS", "").replace(",", " ").split())] or default_sports()
    return run(keys, date_str=args.date, book=args.book, post=args.post,
               webhook=os.environ.get("DISCORD_WEBHOOK_URL"))


if __name__ == "__main__":
    sys.exit(main())
