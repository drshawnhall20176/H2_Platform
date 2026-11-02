"""
research/backtest_td.py — Anytime TD: does knowing WHO gets the ball near the goal line beat the current model?

For every QB/RB/WR/TE game in the test weeks, each model projects the player's touchdowns from his previous games
ONLY (no leakage), and is scored on whether he scored a rushing or receiving TD (log loss, Brier, calibration).
Volume = recency-weighted means over his last FORM_N games, the way football_props does it; no spread / matchup
/ total (identical across models), so the comparison isolates the TD-rate question.

  M0  current: TD per touch (carries + targets), shrunk toward the position's league rate (k touches of trust).
  GL  goal-line: carries inside the 5, other carries, targets inside the 10, other targets -- each at the league
      TD rate for that kind of touch (position-specific), with the player's own rate per kind shrunk toward it.
"""
from __future__ import annotations

import math
import sys
from collections import defaultdict

import nflreadpy as nfl
import pandas as pd

FORM_N = 8
SEASONS = (2024, 2025, 2026)
TEST = {2025: range(4, 19), 2026: range(3, 10)}
POS = {"QB", "RB", "FB", "WR", "TE"}


def recency_weights(n, half=4.0):
    return [0.5 ** (i / half) for i in range(n)]


def load():
    pbp = nfl.load_pbp(list(SEASONS)).to_pandas()
    pbp = pbp[pbp["season_type"] == "REG"] if "season_type" in pbp.columns else pbp
    ws = nfl.load_player_stats(list(SEASONS)).to_pandas()
    pos = ws.dropna(subset=["player_id"]).drop_duplicates("player_id", keep="last").set_index("player_id")["position"].to_dict()
    return pbp, pos


def player_games(pbp):
    """(season, week, team, player) -> dict of carries / gl_carries / targets / rz_targets / rush_td / rec_td."""
    g = defaultdict(lambda: defaultdict(float))
    rush = pbp[(pbp["play_type"] == "run") & (pbp["qb_kneel"] != 1) & pbp["rusher_player_id"].notna()]
    for r in rush[["season", "week", "posteam", "rusher_player_id", "yardline_100", "rush_touchdown"]].itertuples(index=False):
        k = (r.season, r.week, r.posteam, r.rusher_player_id)
        g[k]["car"] += 1
        g[k]["gl"] += 1 if (r.yardline_100 or 99) <= 5 else 0
        g[k]["rtd"] += 1 if r.rush_touchdown == 1 else 0
    pas = pbp[(pbp["play_type"] == "pass") & pbp["receiver_player_id"].notna()]
    for r in pas[["season", "week", "posteam", "receiver_player_id", "yardline_100", "pass_touchdown"]].itertuples(index=False):
        k = (r.season, r.week, r.posteam, r.receiver_player_id)
        g[k]["tgt"] += 1
        g[k]["rz"] += 1 if (r.yardline_100 or 99) <= 10 else 0
        g[k]["ctd"] += 1 if r.pass_touchdown == 1 else 0
    return g


def main():
    pbp, pos = load()
    g = player_games(pbp)
    by_player = defaultdict(list)
    for (s, w, t, p), st in g.items():
        by_player[p].append((s * 100 + w, s, w, t, st))
    for p in by_player:
        by_player[p].sort(key=lambda x: x[0])
    # league rates by position per touch kind, from ALL games strictly before each test week (computed per week)
    orders = sorted({s * 100 + w for (s, w, _t, _p) in g})
    cum = defaultdict(lambda: defaultdict(float))
    league_at = {}
    acc = defaultdict(lambda: defaultdict(float))
    by_order = defaultdict(list)
    for (s, w, t, p), st in g.items():
        by_order[s * 100 + w].append((p, st))
    for o in orders:
        league_at[o] = {grp: dict(v) for grp, v in acc.items()}
        for p, st in by_order[o]:
            grp = "RB" if pos.get(p) in ("RB", "FB") else pos.get(p)
            a = acc[grp]
            for kk in ("car", "gl", "rtd", "tgt", "rz", "ctd"):
                a[kk] += st.get(kk, 0)
            # TDs by touch kind: inside-5 carries vs other; red-zone targets vs other
    # TD splits need per-play attribution: recompute TDs by kind
    rush = pbp[(pbp["play_type"] == "run") & (pbp["qb_kneel"] != 1) & pbp["rusher_player_id"].notna()]
    pas = pbp[(pbp["play_type"] == "pass") & pbp["receiver_player_id"].notna()]
    gtd = defaultdict(lambda: defaultdict(float))
    for r in rush[["season", "week", "rusher_player_id", "yardline_100", "rush_touchdown"]].itertuples(index=False):
        if r.rush_touchdown == 1:
            gtd[(r.season, r.week, r.rusher_player_id)]["gl_td" if (r.yardline_100 or 99) <= 5 else "oc_td"] += 1
    for r in pas[["season", "week", "receiver_player_id", "yardline_100", "pass_touchdown"]].itertuples(index=False):
        if r.pass_touchdown == 1:
            gtd[(r.season, r.week, r.receiver_player_id)]["rz_td" if (r.yardline_100 or 99) <= 10 else "ot_td"] += 1
    for p, lst in by_player.items():
        for o, s, w, t, st in lst:
            for kk, v in gtd.get((s, w, p), {}).items():
                st[kk] = v
    # league per-kind rates before each order
    acc2 = defaultdict(lambda: defaultdict(float))
    lk = {}
    for o in orders:
        lk[o] = {grp: dict(v) for grp, v in acc2.items()}
        for p, st in by_order[o]:
            grp = "RB" if pos.get(p) in ("RB", "FB") else pos.get(p)
            a = acc2[grp]
            for kk in ("car", "gl", "tgt", "rz", "gl_td", "oc_td", "rz_td", "ot_td", "rtd", "ctd"):
                a[kk] += st.get(kk, 0)

    def rate(num, den, d):
        return d.get(num, 0) / d[den] if d.get(den) else 0.0

    results = defaultdict(list)       # model -> [(p, y, grp)]
    K = [25, 50, 100, 200, 400]
    for p, lst in by_player.items():
        grp = "RB" if pos.get(p) in ("RB", "FB") else pos.get(p)
        if grp not in ("QB", "RB", "WR", "TE"):
            continue
        for i, (o, s, w, t, st) in enumerate(lst):
            if s not in TEST or w not in TEST[s]:
                continue
            hist = [x[4] for x in reversed(lst[:i]) if x[0] < o][:FORM_N]
            if len(hist) < 2:
                continue
            wts = recency_weights(len(hist))
            tw = sum(wts)
            mean = lambda kk: sum(h.get(kk, 0) * x for h, x in zip(hist, wts)) / tw
            car, gl, tgt, rz = mean("car"), mean("gl"), mean("tgt"), mean("rz")
            if car + tgt < 1:
                continue
            L = lk[o].get(grp) or {}
            y = 1 if (st.get("rtd", 0) + st.get("ctd", 0)) >= 1 else 0
            # M0: pooled per touch, weighted rate over the window
            touches = [h.get("car", 0) + h.get("tgt", 0) for h in hist]
            tds = [h.get("rtd", 0) + h.get("ctd", 0) for h in hist]
            tot_o = sum(x * o_ for x, o_ in zip(wts, touches))
            own = (sum(x * v for x, v in zip(wts, tds)) / tot_o) if tot_o else None
            n_opp = sum(touches)
            prior = (L.get("rtd", 0) + L.get("ctd", 0)) / max(L.get("car", 0) + L.get("tgt", 0), 1)
            for k in K:
                r_ = prior if own is None else (own * n_opp + prior * k) / (n_opp + k)
                results[f"M0 k={k}"].append((1 - math.exp(-r_ * (car + tgt)), y, grp))
            # GL: league per-kind rates x per-kind volume, optional player shrink on the inside-5 / rz kinds
            r_gl, r_oc = rate("gl_td", "gl", L), (L.get("oc_td", 0) / max(L.get("car", 0) - L.get("gl", 0), 1))
            r_rz, r_ot = rate("rz_td", "rz", L), (L.get("ot_td", 0) / max(L.get("tgt", 0) - L.get("rz", 0), 1))
            lam = gl * r_gl + max(car - gl, 0) * r_oc + rz * r_rz + max(tgt - rz, 0) * r_ot
            results["GL league rates"].append((1 - math.exp(-lam), y, grp))
            r200 = prior if own is None else (own * n_opp + prior * 200) / (n_opp + 200)
            lam0 = r200 * (car + tgt)
            for wgl in (0.3, 0.5):
                results[f"blend M0k200 + GL (w={wgl})"].append((1 - math.exp(-((1 - wgl) * lam0 + wgl * lam)), y, grp))
            # goal-line share inside M0: own rate shrunk toward a GL-expected rate instead of the flat position rate
            exp_rate = lam / (car + tgt) if car + tgt else prior
            for k in (100, 200):
                r_ = exp_rate if own is None else (own * n_opp + exp_rate * k) / (n_opp + k)
                results[f"M0 prior=GL-expected k={k}"].append((1 - math.exp(-r_ * (car + tgt)), y, grp))
            # GL + own efficiency (all kinds pooled), shrunk hard
            exp_hist = sum(x * (h.get("gl", 0) * r_gl + max(h.get("car", 0) - h.get("gl", 0), 0) * r_oc
                                + h.get("rz", 0) * r_rz + max(h.get("tgt", 0) - h.get("rz", 0), 0) * r_ot)
                           for h, x in zip(hist, wts))
            act_hist = sum(x * v for x, v in zip(wts, tds))
            for k2 in (2.0, 5.0):
                eff = (act_hist + k2) / (exp_hist + k2) if exp_hist + k2 > 0 else 1.0
                results[f"GL x own eff (k={k2:g} TDs)"].append((1 - math.exp(-lam * eff), y, grp))
    print(f"{'model':32s} {'n':>6s} {'logloss':>8s} {'brier':>7s}   by position (logloss)")
    for m, rs in results.items():
        ll = -sum(y * math.log(max(p, 1e-6)) + (1 - y) * math.log(max(1 - p, 1e-6)) for p, y, _ in rs) / len(rs)
        br = sum((p - y) ** 2 for p, y, _ in rs) / len(rs)
        pg = {}
        for gname in ("QB", "RB", "WR", "TE"):
            sub = [(p, y) for p, y, gg in rs if gg == gname]
            if sub:
                pg[gname] = -sum(y * math.log(max(p, 1e-6)) + (1 - y) * math.log(max(1 - p, 1e-6)) for p, y in sub) / len(sub)
        print(f"{m:32s} {len(rs):6d} {ll:8.4f} {br:7.4f}   " + "  ".join(f"{k}:{v:.4f}" for k, v in pg.items()))
    for m in ("M0 k=50", "M0 k=200", "M0 prior=GL-expected k=200"):
        rs = results[m]
        bins = defaultdict(lambda: [0, 0, 0.0])
        for p, y, _ in rs:
            b = min(int(p * 10), 9)
            bins[b][0] += 1
            bins[b][1] += y
            bins[b][2] += p
        print(f"\ncalibration {m}: " + "  ".join(f"{b*10}%:{v[1]/v[0]:.0%}/{v[2]/v[0]:.0%}(n{v[0]})" for b, v in sorted(bins.items())))


if __name__ == "__main__":
    sys.exit(main())
