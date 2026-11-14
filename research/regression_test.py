"""Nov 14 -- regression audit, step 2: does pulling each player's efficiency toward his position's average predict the
next game better than the model's current own-rate-only projection? Walk-forward (only games before each one).
projection = opportunity (recency-weighted, as the model does) x rate; rate = his own (current model, K=0) or pulled
toward the position's rate by K games of opportunity: (own*n + pos*K*avg_opp) / (n + K*avg_opp). The K that predicts
best = the regression the data asks for."""
import math, os, sys, time
from collections import defaultdict
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import props_engine as PE

KS = [0, 2, 5, 10, 20, 40, 80]

def num(x):
    try:
        v = float(x); return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None

def test(label, pg, stat, opp, window, min_prior=3, opp_floor=0.0):
    st = lambda q, k: num((q.get("stats") or {}).get(k))
    rows = [q for q in pg if st(q, stat) is not None and st(q, opp) is not None]
    by = defaultdict(list)
    for q in rows: by[(q.get("season"), q["pid"])].append(q)
    tot_v = sum(st(q, stat) for q in rows if st(q, opp) > opp_floor)
    tot_o = sum(st(q, opp) for q in rows if st(q, opp) > opp_floor)
    pos_rate = tot_v / tot_o if tot_o else 0
    avg_opp = tot_o / max(1, sum(1 for q in rows if st(q, opp) > opp_floor))
    err = {k: [] for k in KS}
    for games in by.values():
        games.sort(key=lambda q: str(q["order"]))
        for i in range(min_prior, len(games)):
            prev = [g for g in games[max(0, i - window):i] if st(g, opp) > opp_floor][::-1]   # newest first
            if len(prev) < min_prior: continue
            cur = games[i]
            if st(cur, opp) <= opp_floor: continue
            w = PE.recency_weights(len(prev))
            vals = [st(g, stat) for g in prev]; opps = [st(g, opp) for g in prev]
            n = sum(x * o for x, o in zip(w, opps)) / max(w)            # weighted opportunity in newest-game units
            own = sum(x * v for x, v in zip(w, vals)) / sum(x * o for x, o in zip(w, opps))
            o_hat = sum(x * o for x, o in zip(w, opps)) / sum(w)
            actual = st(cur, stat)
            for k in KS:
                kk = k * avg_opp
                r = (own * n + pos_rate * kk) / (n + kk) if n + kk else own
                err[k].append((o_hat * r - actual) ** 2)
    if not err[0]:
        return
    base = math.sqrt(np.mean(err[0]))
    res = {k: math.sqrt(np.mean(v)) for k, v in err.items()}
    best = min(res, key=res.get)
    cells = "  ".join(f"K{k}:{(res[k] / base - 1) * 100:+.1f}%" for k in KS[1:])
    print(f"REG {label:34} n={len(err[0]):6d} rmse(now) {base:7.2f}  best K={best:>2} ({(res[best] / base - 1) * 100:+.1f}%)  | {cells}")

def retry(fn, tries=3):
    for t in range(tries):
        try:
            out = fn()
            if out: return out
        except Exception as exc:
            print("retry", t, type(exc).__name__, exc)
        time.sleep(20)
    return None

import position_data as PD, sports

# NBA (rate per minute, the model's 10-game window)
smp = retry(lambda: (lambda s: s if (s.get("cur") or s.get("prior")) else None)(PD.nba_league_props_sample(date.today().isoformat())))
if smp:
    pg = []
    for tag in ("prior", "cur"):
        for q in smp.get(tag) or []:
            q = dict(q); q["season"] = tag; pg.append(q)
    print("NBA pgames", len(pg))
    for s_ in ("pts", "reb", "ast", "fg3m", "stl", "blk", "tov"):
        test(f"NBA {s_} per minute", pg, s_, "min", 10, opp_floor=5)
else:
    print("NBA data unavailable")

# NFL (the model's 8-week window; opportunity per market as football_props does)
eng = sports.get("NFL").engine
season = eng._infer_season(date.today().isoformat())
pg = []
for s_ in (season - 2, season - 1, season):
    try:
        for q in PD.stack_nfl_pgames(eng.load_season_weekly_stats(s_), s_, None):
            q = dict(q); q["season"] = s_; pg.append(q)
    except Exception as exc:
        print("NFL season", s_, exc)
qb = [q for q in pg if str(q.get("pos") or "").upper() == "QB"]
rb = [q for q in pg if str(q.get("pos") or "").upper() in ("RB", "FB", "HB")]
wr = [q for q in pg if str(q.get("pos") or "").upper() in ("WR", "TE")]
print("NFL pgames", len(pg))
for lab, sub, s_, o_ in (("NFL QB pass yds per att", qb, "pass_yds", "pass_att"), ("NFL QB pass TD per att", qb, "pass_td", "pass_att"),
                         ("NFL QB INT per att", qb, "pass_int", "pass_att"), ("NFL QB completions per att", qb, "pass_cmp", "pass_att"),
                         ("NFL QB rush yds per carry", qb, "rush_yds", "rush_att"),
                         ("NFL RB rush yds per carry", rb, "rush_yds", "rush_att"), ("NFL RB rush TD per carry", rb, "rush_td", "rush_att"),
                         ("NFL RB rec yds per target", rb, "rec_yds", "tgt"), ("NFL RB catches per target", rb, "rec", "tgt"),
                         ("NFL WR/TE rec yds per target", wr, "rec_yds", "tgt"), ("NFL WR/TE catches per target", wr, "rec", "tgt"),
                         ("NFL WR/TE rec TD per target", wr, "rec_td", "tgt")):
    test(lab, sub, s_, o_, 8, opp_floor=0.5)

# NCAAF
try:
    import ncaaf_data as ND
    roster = ND.load_rosters(); rows = ND.load_player_game_stats()
    pos = {str(p.get("id")): p.get("position") for p in roster if p.get("id") is not None}
    pg = []
    for s_ in (2025, 2026):
        for q in PD.ncaaf_pgames(rows, s_, 999, pos):
            q = dict(q); q["season"] = s_; pg.append(q)
    qb = [q for q in pg if str(q.get("pos") or "").upper() == "QB"]
    rb = [q for q in pg if str(q.get("pos") or "").upper() in ("RB", "FB", "HB")]
    wr = [q for q in pg if str(q.get("pos") or "").upper() in ("WR", "TE")]
    print("NCAAF pgames", len(pg))
    for lab, sub, s_, o_ in (("NCAAF QB pass yds per att", qb, "pass_yds", "pass_att"), ("NCAAF QB pass TD per att", qb, "pass_td", "pass_att"),
                             ("NCAAF QB INT per att", qb, "pass_int", "pass_att"), ("NCAAF QB rush yds per carry", qb, "rush_yds", "rush_att"),
                             ("NCAAF RB rush yds per carry", rb, "rush_yds", "rush_att"), ("NCAAF RB rush TD per carry", rb, "rush_td", "rush_att"),
                             ("NCAAF WR/TE yds per catch", wr, "rec_yds", "rec"), ("NCAAF RB yds per catch", rb, "rec_yds", "rec")):
        test(lab, sub, s_, o_, 8, opp_floor=0.5)
except Exception as exc:
    print("NCAAF failed", exc)

# NHL (the model already shrinks skaters: g 360, a/pts/blk 240, sog 180 minutes -- K here in games of TOI)
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
    pg = [dict(q, season=2026) for q in HP.pgames_from_games({g: v for g, v in games.items() if v.get("rec")}, names)
          if (q.get("stats") or {}).get("g") is not None]
    print("NHL skater games", len(pg), "(model shrink in games of 17 min: g 21, a/pts/blk 14, sog 11)")
    for s_ in ("g", "a", "pts", "sog", "blk"):
        test(f"NHL {s_} per minute", pg, s_, "toi", 10, opp_floor=3)
except Exception as exc:
    print("NHL failed", exc)
