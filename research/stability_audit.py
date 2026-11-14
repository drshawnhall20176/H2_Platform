"""Nov 14 -- regression audit, step 1: how much of each stat is skill (repeats) vs luck (doesn't)?
Split-half reliability: for every player with 2N+ games, the average of his odd games vs his even games, correlated
across players. r = how much an N-game average is signal. Spearman-Brown gives the stabilization point K (games
until signal = noise, r = 0.5): the right amount to pull an n-game average toward the group average is K/(n+K).
Counts per game (volume) and per-opportunity rates (efficiency). Nothing in the model changes."""
import math, os, sys
from collections import defaultdict
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

def num(x):
    try:
        v = float(x); return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None

def by_player(pg, ok=lambda q: True):
    d = defaultdict(list)
    for q in pg:
        if ok(q): d[(q.get("season"), q["pid"])].append(q)
    for v in d.values(): v.sort(key=lambda q: str(q["order"]))
    return d

def rel(players, N, f_num, f_den=None, min_den=0.0):
    """split-half (odd/even of the first 2N games) correlation across players; returns r, K, n_players, mean."""
    a, b = [], []
    for games in players.values():
        if len(games) < 2 * N: continue
        g = games[:2 * N]
        halves = (g[0::2], g[1::2])
        vals = []
        for h in halves:
            nums = [f_num(q) for q in h]
            if any(x is None for x in nums): vals = None; break
            if f_den is None:
                vals.append(sum(nums) / len(nums))
            else:
                dens = [f_den(q) for q in h]
                if any(x is None for x in dens): vals = None; break
                D = sum(dens)
                if D <= min_den: vals = None; break
                vals.append(sum(nums) / D)
        if vals: a.append(vals[0]); b.append(vals[1])
    if len(a) < 30: return None
    r = float(np.corrcoef(a, b)[0, 1])
    K = N * (1 - r) / r if r > 0 else float("inf")
    return r, K, len(a), float(np.mean(a + b))

def report(sport, players, N, items, unit="games"):
    print(f"\n=== {sport}: odd vs even of each player's first {2*N} {unit} ({sum(len(v) >= 2*N for v in players.values())} players)")
    print(f"STAB {'stat':38} {'r(' + str(N) + ')':>7} {'K':>7} {'trust10':>8} {'players':>8} {'mean':>8}")
    out = []
    for name, fn, fd, md in items:
        res = rel(players, N, fn, fd, md)
        if not res: continue
        r, K, n, m = res
        t10 = 10 / (10 + K) if K != float("inf") else 0.0
        out.append((name, r, K, t10, n, m))
    for name, r, K, t10, n, m in sorted(out, key=lambda x: -x[1]):
        print(f"STAB {name:38} {r:7.2f} {K:7.1f} {t10:8.0%} {n:8d} {m:8.3f}")

S = lambda k: (lambda q: num((q.get("stats") or {}).get(k)))
SUM = lambda *ks: (lambda q: (lambda v: None if any(x is None for x in v) else sum(v))([num((q.get("stats") or {}).get(k)) for k in ks]))

# ---------------------------------------------------------------- NBA
try:
    import position_data as PD
    smp = PD.nba_league_props_sample(date.today().isoformat())
    pg = []
    for tag in ("prior", "cur"):
        for q in smp.get(tag) or []:
            q = dict(q); q["season"] = tag; pg.append(q)
    keys = sorted({k for q in pg[:500] for k in (q.get("stats") or {})})
    print("NBA stat keys", keys)
    pl = by_player(pg, lambda q: (num((q.get("stats") or {}).get("min")) or 0) >= 10)
    items = [(f"{k} per game", S(k), None, 0) for k in keys]
    for k in keys:
        if k != "min": items.append((f"{k} per minute", S(k), S("min"), 50))
    pairs = [("fg3m", "fg3a"), ("fgm", "fga"), ("ftm", "fta"), ("fg3a", "fga")]
    for n_, d_ in pairs:
        if n_ in keys and d_ in keys: items.append((f"{n_}/{d_} (pct)", S(n_), S(d_), 5))
    report("NBA", pl, 10, items)
except Exception as exc:
    print("NBA failed", type(exc).__name__, exc)

# ---------------------------------------------------------------- NFL
try:
    import sports
    eng = sports.get("NFL").engine
    season = eng._infer_season(date.today().isoformat())
    pg = []
    for s_ in (season - 2, season - 1):
        for q in PD.stack_nfl_pgames(eng.load_season_weekly_stats(s_), s_, None):
            q = dict(q); q["season"] = s_; pg.append(q)
    keys = sorted({k for q in pg[:2000] for k in (q.get("stats") or {})})
    print("\nNFL stat keys", keys)
    def football_items(keys, opp):
        it = [(f"{k} per game", S(k), None, 0) for k in keys]
        for n_, d_ in opp:
            if n_ in keys and d_ in keys: it.append((f"{n_} per {d_}", S(n_), S(d_), 10))
        return it
    nfl_opp = [("rec_yds", "targets"), ("rec", "targets"), ("rec_td", "targets"), ("rec_yds", "rec"),
               ("rush_yds", "rush_att"), ("rush_td", "rush_att"), ("pass_yds", "pass_att"), ("pass_td", "pass_att"),
               ("pass_int", "pass_att"), ("interceptions", "attempts"), ("passing_yards", "attempts"),
               ("receiving_yards", "targets"), ("receptions", "targets"), ("rushing_yards", "carries")]
    for pos in (("QB",), ("RB",), ("WR", "TE")):
        pl = by_player(pg, lambda q, pos=pos: str(q.get("pos") or "").upper() in pos)
        report(f"NFL {'/'.join(pos)}", pl, 5, football_items(keys, nfl_opp))
except Exception as exc:
    print("NFL failed", type(exc).__name__, exc)

# ---------------------------------------------------------------- NCAAF
try:
    import ncaaf_data as ND
    roster = ND.load_rosters(); rows = ND.load_player_game_stats()
    pos = {str(p.get("id")): p.get("position") for p in roster if p.get("id") is not None}
    pg = []
    for s_ in (2025,):
        for q in PD.ncaaf_pgames(rows, s_, 999, pos):
            q = dict(q); q["season"] = s_; pg.append(q)
    keys = sorted({k for q in pg[:2000] for k in (q.get("stats") or {})})
    opp = [("rec_yds", "rec"), ("rush_yds", "rush_att"), ("rush_td", "rush_att"), ("pass_yds", "pass_att"),
           ("pass_td", "pass_att"), ("pass_int", "pass_att"), ("rec_td", "rec")]
    for p_ in (("QB",), ("RB", "FB", "HB"), ("WR", "TE")):
        pl = by_player(pg, lambda q, p_=p_: str(q.get("pos") or "").upper() in p_)
        report(f"NCAAF {'/'.join(p_)}", pl, 5, football_items(keys, opp))
except Exception as exc:
    print("NCAAF failed", type(exc).__name__, exc)

# ---------------------------------------------------------------- NHL
try:
    import hockey_props as HP
    eng = sports.get("NHL").engine
    today = date.today().isoformat()
    teams = set()
    for back in range(0, 21, 3):
        _r, meta = eng.build_slate((date.today() - timedelta(days=back)).isoformat())
        for m in meta or []:
            teams |= {m.get("home_id"), m.get("away_id")}
    teams.discard(None)
    games, names = {}, {}
    for tid in teams:
        for g in eng.get_team_recent_game_ids(tid, today, 60) or []:
            at_home = g.get("home_away") != "away"; o = g.get("opp_id")
            games.setdefault(str(g.get("gameId")), {"date": (g.get("date") or "")[:10], "home": tid if at_home else o,
                                                   "away": o if at_home else tid})
        for p in eng.get_team_roster(tid) or []:
            names[p.get("id")] = {"name": p.get("name"), "pos": "G" if p.get("is_goalie") else p.get("pos")}
    with ThreadPoolExecutor(8) as ex:
        recs = list(ex.map(lambda gid: eng.get_game(gid), list(games)))
    for gid, rec in zip(list(games), recs): games[gid]["rec"] = rec
    pg = HP.pgames_from_games({g: v for g, v in games.items() if v.get("rec")}, names)
    for q in pg: q["season"] = 2026
    sk = by_player(pg, lambda q: (q.get("stats") or {}).get("g") is not None)
    report("NHL skaters", sk, 6, [("goals per game", S("g"), None, 0), ("assists per game", S("a"), None, 0),
                                   ("points per game", S("pts"), None, 0), ("shots per game", S("sog"), None, 0),
                                   ("blocks per game", S("blk"), None, 0), ("toi per game", S("toi"), None, 0),
                                   ("goals per shot (sh%)", S("g"), S("sog"), 5), ("shots per toi", S("sog"), S("toi"), 30),
                                   ("points per toi", S("pts"), S("toi"), 30)])
    gk = by_player(pg, lambda q: (q.get("stats") or {}).get("saves") is not None and (q.get("stats") or {}).get("gs"))
    report("NHL goalies (starts)", gk, 5, [("saves per start", S("saves"), None, 0), ("shots against per start", S("sa"), None, 0),
                                           ("save %", S("saves"), S("sa"), 30)])
except Exception as exc:
    print("NHL failed", type(exc).__name__, exc)

# ---------------------------------------------------------------- Soccer (cached ESPN match summaries)
try:
    import model_store as MS
    pg = []
    for lg in ("SOCCER_EPL", "SOCCER_LALIGA", "SOCCER_SERIEA", "SOCCER_BUNDESLIGA", "SOCCER_LIGUE1", "SOCCER_MLS"):
        for m in MS.load_results(f"SOCCERP_{lg}"):
            for r in m.get("rows") or []:
                if r.get("started"):
                    pg.append({"pid": r["player"], "season": lg, "order": str(m["id"]).zfill(12),
                               "stats": {"goals": r.get("goals"), "shots": r.get("shots"), "sot": r.get("sot")}})
    print("\nSoccer starts on file", len(pg))
    pl = by_player(pg)
    report("Soccer starters", pl, 4, [("goals per start", S("goals"), None, 0), ("shots per start", S("shots"), None, 0),
                                       ("shots on target per start", S("sot"), None, 0),
                                       ("goals per shot", S("goals"), S("shots"), 3)], unit="starts")
except Exception as exc:
    print("Soccer failed", type(exc).__name__, exc)

# ---------------------------------------------------------------- Team level: college football
try:
    import pandas as pd
    sch = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ncaaf_schedule.csv"))
    sch = sch[(sch["completed"] == True) & (sch["season"] == 2025)]  # noqa: E712
    tg = []
    for r in sch.itertuples():
        for t, us, them in ((r.home_team, r.home_points, r.away_points), (r.away_team, r.away_points, r.home_points)):
            m = us - them
            tg.append({"pid": t, "season": 2025, "order": f"{int(r.week):03d}",
                       "stats": {"margin": m, "win": 1.0 if m > 0 else 0.0, "pts_for": us, "pts_against": them,
                                 "close_win": (1.0 if m > 0 else 0.0) if abs(m) <= 8 else None}})
    pl = by_player(tg)
    report("NCAAF teams (2025)", pl, 5, [("point margin", S("margin"), None, 0), ("win %", S("win"), None, 0),
                                         ("points for", S("pts_for"), None, 0), ("points against", S("pts_against"), None, 0)])
except Exception as exc:
    print("Teams failed", type(exc).__name__, exc)
