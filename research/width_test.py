"""Nov 14 -- is the model's RANGE of outcomes right? The NBA points backtest's calibration slope was 0.30: the chances
are far too sure of themselves, which points at the spread of outcomes being too narrow (minutes swing; scoring is
lumpier than a bell curve). Walk-forward backtests (no peeking), every market: widen the spread by a multiplier and
score the chances (Brier, log loss, calibration slope; 1.00 = honest)."""
import math, os, sys
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import props_backtest as BT, props_engine as PE, position_data as PD, sports

MULTS = [0.8, 1.0, 1.2, 1.4, 1.7, 2.0, 2.5]
cap = []
_orig = PE.read_line
def spy(model, vals, line, dist, *a, **k):
    cap.append((model, list(vals), dist, (k.get("sd_floor_frac", 0.25), k.get("sd_floor_abs", 1.0))))
    return _orig(model, vals, line, dist, *a, **k)
PE.read_line = spy

def p_mult(model, vals, line, dist, floor, m):
    if dist == "count":
        n = len(vals); sample = PE.wvar(vals); typical = model * 1.25
        var = typical if sample is None else (sample * n + typical * 5) / (n + 5)
        var = max(var, model) * m * m
        p = PE.count_sf(max(model, 0.0), max(var, model * 1.0001), PE.k_needed(line))
    else:
        sd = math.sqrt(PE.wvar(vals) or 0.0)
        sd = max(sd, floor[0] * max(model, 1.0), floor[1]) * m
        p = PE.normal_sf(model, sd, PE.threshold(line))
    return max(0.01, min(0.99, p))

def run(label, fn):
    cap.clear(); got = []
    orig = BT.summarize
    BT.summarize = lambda cases: (got.extend(cases), orig(cases))[1]
    try:
        fn()
    finally:
        BT.summarize = orig
    if len(cap) != len(got) or not got:
        print(f"W {label}: capture mismatch {len(cap)} vs {len(got)}"); return
    res = {}
    for m in MULTS:
        ps = [(p_mult(mo, v, c["line"], d, fl, m), c["actual"] > PE.threshold(c["line"])) for (mo, v, d, fl), c in zip(cap, got) if mo is not None]
        br = sum((p - y) ** 2 for p, y in ps) / len(ps)
        ll = -sum(math.log(p if y else 1 - p) for p, y in ps) / len(ps)
        res[m] = (br, ll, PE.fitted_slope(ps) or 0)
    best = min(res, key=lambda m: res[m][1])
    print(f"W {label:28} n={len(got):5d} " + "  ".join(f"x{m}: {res[m][1]:.4f}/s{res[m][2]:.2f}" for m in MULTS) + f"  -> best x{best}")

smp = PD.nba_league_props_sample(date.today().isoformat())
pg = (smp.get("cur") or []) + (smp.get("prior") or [])
for mk in ("Points", "Rebounds", "Assists", "Threes Made", "PRA", "PA", "PR", "Steals", "Blocks"):
    run(f"NBA {mk}", lambda mk=mk: BT.backtest_basketball(pg, "NBA", mk, max_cases=4000))
eng = sports.get("NFL").engine
season = eng._infer_season(date.today().isoformat())
pg = []
for s_ in (season - 1, season):
    pg += PD.stack_nfl_pgames(eng.load_season_weekly_stats(s_), s_, None)
for mk in ("Receiving Yards", "Rush Yards", "Pass Yards", "Receptions", "Rush + Rec Yards", "Passing TDs", "Interceptions", "Pass Attempts", "Pass Completions"):
    run(f"NFL {mk}", lambda mk=mk: BT.backtest_football(pg, "NFL", mk, max_cases=6000))
import ncaaf_data as ND
roster = ND.load_rosters(); rows = ND.load_player_game_stats()
pos = {str(p.get("id")): p.get("position") for p in roster if p.get("id") is not None}
pg = []
for s_ in (2025, 2026):
    sub = PD.ncaaf_pgames(rows, s_, 999, pos)
    for q in sub: q["order"] = (s_ - 2000) * 100 + q["order"]
    pg += sub
for mk in ("Receiving Yards", "Rush Yards", "Pass Yards", "Receptions", "Rush + Rec Yards", "Passing TDs"):
    run(f"NCAAF {mk}", lambda mk=mk: BT.backtest_football(pg, "NCAAF", mk, max_cases=6000))
import hockey_props as HP
eng = sports.get("NHL").engine
today = date.today().isoformat()
teams = set()
for back in range(0, 21, 3):
    _r, meta = eng.build_slate((date.today() - timedelta(days=back)).isoformat())
    for m in meta or []: teams |= {m.get("home_id"), m.get("away_id")}
teams.discard(None)
games, names = {}, {}
for tid in teams:
    for g in eng.get_team_recent_game_ids(tid, today, 45) or []:
        at_home = g.get("home_away") != "away"; o = g.get("opp_id")
        games.setdefault(str(g.get("gameId")), {"date": (g.get("date") or "")[:10], "home": tid if at_home else o, "away": o if at_home else tid})
    for p in eng.get_team_roster(tid) or []:
        names[p.get("id")] = {"name": p.get("name"), "pos": "G" if p.get("is_goalie") else p.get("pos")}
with ThreadPoolExecutor(8) as ex:
    recs = list(ex.map(lambda gid: eng.get_game(gid), list(games)))
for gid, rec in zip(list(games), recs): games[gid]["rec"] = rec
pg = HP.pgames_from_games({g: v for g, v in games.items() if v.get("rec")}, names)
for mk in ("Shots on Goal", "Points", "Goals", "Assists", "Blocked Shots", "Saves"):
    run(f"NHL {mk}", lambda mk=mk: BT.backtest_hockey(pg, mk, max_cases=6000))
PE.read_line = _orig
