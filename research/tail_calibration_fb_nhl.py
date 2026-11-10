"""Nov 10: the NBA long-shot (tail) test, for NFL and NHL. Walk-forward replays (props_backtest, no peeking): for
every player-game, the model's chance of N+ at the three rungs above his projection vs how often N+ happened.
Prints a ratio table (happened / said) per market and band, the same shape as long_shots.TAIL."""
import math
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import position_data as PD                                      # noqa: E402
import props_backtest as BT                                      # noqa: E402
import props_engine as PE                                        # noqa: E402
import sports                                                    # noqa: E402

BINS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.55), (0.55, 1.01)]
cap = []
_orig = PE.read_line


def spy(model, vals, line, dist, *a, **k):
    floor = (k.get("sd_floor_frac", 0.25), k.get("sd_floor_abs", 1.0))
    cap.append((model, list(vals), dist, floor))
    return _orig(model, vals, line, dist, *a, **k)


PE.read_line = spy


def run(label, fn, market):
    cap.clear()
    got = []
    orig = BT.summarize
    BT.summarize = lambda cases: (got.extend(cases), orig(cases))[1]
    try:
        fn()
    finally:
        BT.summarize = orig
    if len(cap) != len(got):
        print(f"TC {label} {market}: capture mismatch {len(cap)} vs {len(got)}; skipped")
        return
    cell = defaultdict(lambda: [0, 0, 0.0])
    for (model, vals, dist, floor), c in zip(cap, got):
        if model is None or model <= 0:
            continue
        step = PE.ladder_step(market, model)
        base = math.floor(model / step) * step
        for k in (1, 2, 3):
            n = base + k * step
            p = PE.prob_over(model, vals, n - 0.5, dist, *floor)
            if p is None:
                continue
            for lo, hi in BINS:
                if lo <= p < hi:
                    x = cell[(lo, hi)]
                    x[0] += 1
                    x[1] += c["actual"] >= n
                    x[2] += p
    ratios = []
    print(f"TC {label} {market}: cases {len(got)}")
    for lo, hi in BINS:
        n, h, ps = cell[(lo, hi)]
        ratios.append(round(h / ps, 2) if n >= 30 and ps else None)
        if n >= 30:
            print(f"TC    model {lo:.0%}-{hi:.0%}: n={n:5d} said {ps / n:5.1%} happened {h / n:5.1%}  ratio {h / ps:.2f}")
    print(f"TC  TAIL[{market!r}] = {ratios}")


# ---------------------------------------------------------------- NFL (this season + last, league-wide)
today = date.today().isoformat()
try:
    eng = sports.get("NFL").engine
    season = eng._infer_season(today)
    pg = []
    for s_ in (season - 1, season):
        pg += PD.stack_nfl_pgames(eng.load_season_weekly_stats(s_), s_, None)
    print("TC NFL pgames", len(pg))
    for mk in ("Receiving Yards", "Rush Yards", "Pass Yards", "Receptions", "Rush + Rec Yards", "Passing TDs"):
        run("NFL", lambda mk=mk: BT.backtest_football(pg, "NFL", mk, max_cases=8000), mk)
except Exception as exc:                                       # noqa: BLE001
    print("TC NFL failed", type(exc).__name__, exc)

# ---------------------------------------------------------------- NHL (every team's last ~30 games)
try:
    import hockey_props as HP
    eng = sports.get("NHL").engine
    teams = set()
    for back in range(0, 21, 3):
        _r, meta = eng.build_slate((date.today() - timedelta(days=back)).isoformat())
        for m in meta or []:
            teams |= {m.get("home_id"), m.get("away_id")}
    teams.discard(None)
    games, names = {}, {}
    for tid in teams:
        for g in eng.get_team_recent_game_ids(tid, today, 30) or []:
            at_home = g.get("home_away") != "away"
            opp = g.get("opp_id")
            games.setdefault(str(g.get("gameId")), {"date": (g.get("date") or "")[:10],
                                                    "home": tid if at_home else opp, "away": opp if at_home else tid})
        for p in eng.get_team_roster(tid) or []:
            names[p.get("id")] = {"name": p.get("name"), "pos": "G" if p.get("is_goalie") else p.get("pos")}
    with ThreadPoolExecutor(8) as ex:
        recs = list(ex.map(lambda gid: eng.get_game(gid), list(games)))
    for gid, rec in zip(list(games), recs):
        games[gid]["rec"] = rec
    pg = HP.pgames_from_games({g: v for g, v in games.items() if v.get("rec")}, names)
    print("TC NHL teams", len(teams), "games", len(games), "pgames", len(pg))
    for mk in ("Shots on Goal", "Points", "Goals", "Assists", "Blocked Shots", "Saves"):
        run("NHL", lambda mk=mk: BT.backtest_hockey(pg, mk, max_cases=8000), mk)
except Exception as exc:                                       # noqa: BLE001
    print("TC NHL failed", type(exc).__name__, exc)
PE.read_line = _orig
