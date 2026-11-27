"""
warm_slates.py — rebuild today's slates and save them (slate_store.py), so the app finds a fresh copy instead of
building one from hundreds of ESPN requests when a page opens (Nov 4). Run hourly by the warm-slates workflow.

    python warm_slates.py [NBA,NHL,...] [YYYY-MM-DD]
"""
from __future__ import annotations

import sys
import time

import slate_store as SS

DEFAULT = ("NBA", "NHL", "NFL", "WNBA", "NCAAF", "NCAAMB")   # biggest last: college opening week is hundreds of games


def main(argv=None) -> int:
    import sports
    argv = argv if argv is not None else sys.argv[1:]
    which = [s for s in (argv[0].split(",") if argv and argv[0] else DEFAULT)]
    day = argv[1] if len(argv) > 1 else SS._today_et()
    enabled = {s.key for s in sports.enabled_sports()}
    seen = {}                                                   # Nov 26: games per sport, for Today's sport bar
    for key in which:
        if key not in enabled:
            print(f"{key}: not enabled, skipped")
            continue
        build = getattr(sports.get(key).engine.build_slate, "uncached", None)
        if build is None:
            print(f"{key}: no saved-slate support, skipped")
            continue
        t0 = time.time()
        try:
            rows, meta = build(day)
        except Exception as exc:                                # noqa: BLE001 -- one sport failing never stops the rest
            print(f"{key}: build failed ({type(exc).__name__}: {exc})")
            continue
        seen[key] = len(meta or [])
        if rows:
            SS.save(key, day, (rows, meta))
        print(f"{key} {day}: {len(rows)} players, {len(meta)} games, {time.time() - t0:.0f}s"
              + (" -> saved" if rows else " (nothing to save)"))
        if key == "NBA" and rows:                               # the props model's league sample (finished box scores)
            t0 = time.time()
            try:
                import position_data as PD
                smp = PD.nba_league_props_sample(day)
                print(f"NBA league sample: {len(smp.get('cur') or [])} + {len(smp.get('prior') or [])} player-games, "
                      f"{time.time() - t0:.0f}s")
            except Exception as exc:                            # noqa: BLE001
                print(f"NBA league sample failed ({type(exc).__name__}: {exc})")
    seen.update(other_sports_games(day, set(seen)))
    save_games_on(day, seen)
    boards(day)
    grade_live_signals(day)
    try:                                                        # Nov 27: Today's 30-day game-line records, saved
        import pick_records as PR
        print(f"lean records saved: {PR.save_lean_records(('NBA', 'NCAAMB', 'NHL', 'NFL', 'NCAAF', 'WNBA'))}")
    except Exception as exc:                                    # noqa: BLE001
        print(f"lean records not saved ({type(exc).__name__})")
    return 0


def grade_live_signals(day: str) -> int:
    """Nov 27: grade the live edges the Live page kept (live_signals.py) whose games have ended -- today's and
    yesterday's, so a game nobody had open at the final whistle still gets its result."""
    from datetime import date, timedelta
    try:
        import intl_hoops as I
        import live_games as LG
        import live_signals as LS
        d = date.fromisoformat(day)

        def summary(lg, event_id):
            if lg not in LG.ESPN_PATH or not event_id:
                return {}
            return I._http(f"https://site.api.espn.com/apis/site/v2/sports/{LG.ESPN_PATH[lg]}/summary",
                           {"event": event_id}) or {}
        n = LS.grade_pending([(d - timedelta(days=1)).isoformat(), day], LG.games, summary)
        print(f"live edges graded: {n}")
        return n
    except Exception as exc:                                    # noqa: BLE001
        print(f"live edges grading failed ({type(exc).__name__}: {exc})")
        return 0


GAMES_KEY = "games_on:{day}"


def other_sports_games(day: str, done: set, check=None) -> dict:
    """Nov 27 (owner: speed): the sports this build doesn't make a board for (soccer, tennis, INTL, UFC, the off-season
    leagues) -- checked here, side by side, so Today never asks their feeds on a member's load. 1 = games, 0 = none;
    a sport whose check fails is left out (Today then asks it itself)."""
    try:
        import sports
        keys = [s.key for s in sports.enabled_sports() if s.key not in done]
        if check is None:
            import customer_today as CT
            check = lambda ks: CT.has_games_many(ks, day, saved={})
        got = check(keys) if keys else {}
        return {k: int(bool(v)) for k, v in got.items() if v is not None}
    except Exception as exc:                                    # noqa: BLE001
        print(f"other sports' schedules failed ({type(exc).__name__}: {exc})")
        return {}


def save_games_on(day: str, seen: dict, save=None, get=None) -> None:
    """Nov 26 (owner: speed): how many games each sport has on the day, as this hourly build found them -- Today's
    sport bar reads this one record instead of asking every schedule feed (the NBA's can hang 5 s). Merged with the
    day's earlier record so a sport skipped this run keeps its count."""
    if not seen:
        return
    try:
        from datetime import datetime, timezone
        import model_store as MS
        save, get = save or MS.save_setting, get or MS.get_setting
        prev = (get(GAMES_KEY.format(day=day), None) or {}).get("n") or {}
        save(GAMES_KEY.format(day=day), {"at": datetime.now(timezone.utc).isoformat(), "n": dict(prev, **seen)})
        print(f"games on {day}: {seen}")
    except Exception as exc:                                    # noqa: BLE001
        print(f"games-on record failed ({type(exc).__name__}: {exc})")


BOARD_SPORTS = ("NBA", "NFL", "NHL", "NCAAF", "NCAAMB")   # Nov 12: college basketball's board too


def boards(day: str) -> None:
    """Nov 6: build each in-season props sport's Best Bets board, so Home's "Today's best" is filled without anyone
    opening a page (building a board saves its top-tagged picks: todays_best.save_props). About 130-300 Odds API
    credits a board; hourly across four sports is a small share of the plan."""
    import best_bets_data as BBD
    import sports
    import todays_best as TB
    for key in BOARD_SPORTS:
        if not sports.in_season(key):
            continue
        t0 = time.time()
        try:
            plays, meta, _ = BBD.build_generic_board(key, day, BBD.O.DEFAULT_BOOK)   # Nov 20: built + saved whole
            saved = (TB.load_props(key, day) or {}).get("rows") or []
            print(f"{key} board: {len(plays)} plays, {len(saved)} on Today's best, {time.time() - t0:.0f}s")
        except Exception as exc:                                # noqa: BLE001
            print(f"{key} board failed ({type(exc).__name__}: {exc})")
    for _wsp in ("NFL", "NCAAF"):                               # Nov 21: football weather, saved for the app
        try:
            import football_weather as FW
            print(f"{_wsp} weather: {len(FW.slate(_wsp, day))} games")
        except Exception as exc:                                # noqa: BLE001
            print(f"{_wsp} weather failed ({type(exc).__name__}: {exc})")
    try:                                                        # Nov 21: the game-line 💰 as shown (pick_ledger.py)
        import money_score as MSC
        import pick_ledger as PL
        print(f"game 💰 ledger: {PL.record_games(day, TB.winner_rows(day, leagues=list(MSC.MONEY_LEAGUES)))} new")
    except Exception as exc:                                    # noqa: BLE001
        print(f"game 💰 ledger failed ({type(exc).__name__}: {exc})")


if __name__ == "__main__":
    sys.exit(main())
