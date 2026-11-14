"""Nov 14 -- regression audit, step 3: the model's own walk-forward backtest (props_backtest: proxy lines, no peeking),
before vs after the new regression settings, market by market. Adopt only where it doesn't make things worse."""
import os, sys, copy, math
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import props_backtest as BT, player_props as PPR, football_props as FP, hockey_props as HP, position_data as PD, sports

def line(tag, r):
    if not r or not r.get("n"):
        print(f"VAL {tag}: no cases"); return
    lb = r.get("lean_base")
    print(f"VAL {tag:40} n={r['n']:5d} brier {r['brier_model']:.4f} mae {r['mae_model']:.3f} side {r['side_rate'] or 0:.1%} "
          f"leans {r['lean_n']:4d} hit {r['lean_rate'] or 0:.1%} (base {lb or 0:.1%}, edge {((r['lean_rate'] or 0) - (lb or 0)) * 100:+.1f}) slope {r.get('slope') or 0:.2f}")

def ab(label, fn, set_old, set_new):
    set_old(); a = fn()
    set_new(); b = fn()
    line(label + " BEFORE", a); line(label + " AFTER", b)

new_nba = dict(PPR.RATE_SHRINK_MIN)
smp = PD.nba_league_props_sample(date.today().isoformat())
pg = (smp.get("cur") or []) + (smp.get("prior") or [])
print("NBA pgames", len(pg))
for mk in ("Points", "Rebounds", "Assists", "Threes Made", "Steals", "Blocks", "PRA"):
    ab(f"NBA {mk}", lambda mk=mk: BT.backtest_basketball(pg, "NBA", mk, max_cases=4000),
       lambda: PPR.RATE_SHRINK_MIN.update({k: 0.0 for k in new_nba}), lambda: PPR.RATE_SHRINK_MIN.update(new_nba))

new_ms, new_qb = dict(FP.MARKET_SHRINK), FP.QB_RUSH_SHRINK
def old_fb():
    FP.MARKET_SHRINK.clear(); FP.MARKET_SHRINK.update({"Anytime TD": 200.0}); FP.QB_RUSH_SHRINK = 12.0
def new_fb():
    FP.MARKET_SHRINK.clear(); FP.MARKET_SHRINK.update(new_ms); FP.QB_RUSH_SHRINK = new_qb
eng = sports.get("NFL").engine
season = eng._infer_season(date.today().isoformat())
pg = []
for s_ in (season - 1, season):
    pg += PD.stack_nfl_pgames(eng.load_season_weekly_stats(s_), s_, None)
print("NFL pgames", len(pg))
for mk in ("Interceptions", "Passing TDs", "Rush Yards", "Pass Yards"):
    ab(f"NFL {mk}", lambda mk=mk: BT.backtest_football(pg, "NFL", mk, max_cases=6000), old_fb, new_fb)
import ncaaf_data as ND
roster = ND.load_rosters(); rows = ND.load_player_game_stats()
pos = {str(p.get("id")): p.get("position") for p in roster if p.get("id") is not None}
pg = []
for s_ in (2025, 2026):
    sub = PD.ncaaf_pgames(rows, s_, 999, pos)
    for q in sub: q["order"] = (s_ - 2000) * 100 + q["order"]
    pg += sub
print("NCAAF pgames", len(pg))
for mk in ("Interceptions", "Passing TDs", "Rush Yards"):
    ab(f"NCAAF {mk}", lambda mk=mk: BT.backtest_football(pg, "NCAAF", mk, max_cases=6000), old_fb, new_fb)

new_hk = dict(HP.SHRINK_MIN)
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
print("NHL pgames", len(pg))
for mk in ("Shots on Goal", "Points", "Blocked Shots"):
    ab(f"NHL {mk}", lambda mk=mk: BT.backtest_hockey(pg, mk, max_cases=6000),
       lambda: HP.SHRINK_MIN.update({"g": 360.0, "a": 240.0, "pts": 240.0, "sog": 180.0, "blk": 240.0}),
       lambda: HP.SHRINK_MIN.update(new_hk))
