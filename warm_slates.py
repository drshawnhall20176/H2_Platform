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
    boards(day)
    return 0


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
            plays, meta, _ = BBD.load_generic_best_bets_board(key, day, BBD.O.DEFAULT_BOOK)
            saved = (TB.load_props(key, day) or {}).get("rows") or []
            print(f"{key} board: {len(plays)} plays, {len(saved)} on Today's best, {time.time() - t0:.0f}s")
        except Exception as exc:                                # noqa: BLE001
            print(f"{key} board failed ({type(exc).__name__}: {exc})")


if __name__ == "__main__":
    sys.exit(main())
