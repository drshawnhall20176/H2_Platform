"""
Nov 12: does live_model.py's in-game read hold up on past games? For every graded Game Lab pick (pre-game margin /
total saved before tip-off) in NBA, NCAAMB, NHL and EuroLeague, rebuild the score at checkpoints from the play-by-play
(25% / 50% / 75% of the game played, 6 and 2 minutes left) and score the live read against the final:
  * win chance: Brier, log loss, calibration by band -- with the game-spread as set and scaled x0.8 / x1.2
  * total: mean absolute error of the projected final for several pace weights (PACE_K), and how often the final
    lands within one projected sd (should be ~68%)
  * margin: same coverage check
Free (ESPN / EuroLeague feeds), read-only.
"""
import math
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I                                           # noqa: E402
import live_model as LM                                          # noqa: E402
import model_store as MS                                         # noqa: E402

ESPN = {"NBA": ("basketball/nba", I.ESPN_LEAGUE_URL["NBA"]),
        "NCAAMB": ("basketball/mens-college-basketball", I.NCAAMB_URL),
        "NHL": ("hockey/nhl", I.ESPN_LEAGUE_URL["NHL"])}
MAX_GAMES = {"NBA": 250, "NCAAMB": 300, "NHL": 250, "EUROLEAGUE": 150}


def clock_min(txt):
    try:
        if ":" in str(txt):
            mm, ss = str(txt).split(":")[:2]
            return int(mm) + float(ss) / 60
        return float(txt) / 60                                  # "34.5" seconds
    except (TypeError, ValueError):
        return None


def espn_states(league, pick):
    """[(elapsed, home, away)] from ESPN play-by-play, plus the final, for one graded pick."""
    path, url = ESPN[league]
    day = datetime.fromisoformat(pick["kickoff"]).astimezone(I_ET).date()
    params = {"dates": day.strftime("%Y%m%d"), "limit": 500}
    if league == "NCAAMB":
        params["groups"] = 50
    data = I._http(url, params) or {}
    ev = None
    for e in data.get("events") or []:
        c = (e.get("competitions") or [{}])[0]
        side = {t.get("homeAway"): (t.get("team") or {}).get("displayName") for t in c.get("competitors") or []}
        if I.same_team(side.get("home"), pick["home"]) and I.same_team(side.get("away"), pick["away"]):
            ev = e
            break
    if not ev:
        return None
    summ = I._http(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary", {"event": ev["id"]}) or {}
    out = []
    for p in summ.get("plays") or []:
        per = (p.get("period") or {}).get("number")
        cl = clock_min((p.get("clock") or {}).get("displayValue"))
        if league == "NHL" and cl is not None and per is not None:   # ESPN hockey play-by-play counts time UP
            cl = (5.0 if per > 3 else 20.0) - cl
        if per is None or cl is None or p.get("homeScore") is None:
            continue
        out.append((LM.elapsed(league, per, cl), per, cl, float(p["homeScore"]), float(p["awayScore"])))
    return out


def el_states(pick):
    code = "E" + I.season_of("EUROLEAGUE", pick["kickoff"][:10])
    games = (I._http(I.EL_URL.format(comp="E", code=code)) or {}).get("data") or []
    g = next((x for x in games if I.same_team(((x.get("local") or {}).get("club") or {}).get("name"), pick["home"])
              and I.same_team(((x.get("road") or {}).get("club") or {}).get("name"), pick["away"])
              and str(x.get("utcDate", ""))[:10] == pick["kickoff"][:10]), None)
    if not g:
        return None
    pbp = I._http("https://live.euroleague.net/api/PlaybyPlay", {"gamecode": g["gameCode"], "seasoncode": code}) or {}
    out, h, a = [], 0.0, 0.0
    for q, key in enumerate(("FirstQuarter", "SecondQuarter", "ThirdQuarter", "ForthQuarter"), start=1):
        for p in pbp.get(key) or []:
            if p.get("POINTS_A") is not None:
                h, a = float(p["POINTS_A"]), float(p["POINTS_B"])
            cl = clock_min(p.get("MARKERTIME"))
            if cl is None:
                continue
            out.append((LM.elapsed("EUROLEAGUE", q, cl), q, cl, h, a))
    return out


import pytz                                                      # noqa: E402
I_ET = pytz.timezone("US/Eastern")


def states_for(league, pick):
    try:
        return el_states(pick) if league == "EUROLEAGUE" else espn_states(league, pick)
    except Exception:                                           # noqa: BLE001
        return None


rows = []          # one per checkpoint
for league in ("NBA", "NCAAMB", "NHL", "EUROLEAGUE"):
    picks = [p for p in MS.load_game_picks(league) if p.get("final_home") is not None
             and p.get("model_margin") is not None and p.get("model_total") is not None]
    picks = picks[-MAX_GAMES[league]:]
    with ThreadPoolExecutor(8) as ex:
        sts = list(ex.map(lambda p: states_for(league, p), picks))
    L = LM.game_minutes(league)
    got = 0
    for p, st in zip(picks, sts):
        if not st:
            continue
        got += 1
        fh, fa = float(p["final_home"]), float(p["final_away"])
        st.sort(key=lambda s: s[0])
        for name, t in (("25%", 0.25 * L), ("50%", 0.5 * L), ("75%", 0.75 * L), ("6 left", L - 6), ("2 left", L - 2)):
            before = [s for s in st if s[0] <= t]
            if not before:
                continue
            e, per, cl, h, a = before[-1]
            rows.append({"league": league, "cp": name, "p": p, "per": per, "cl": cl, "h": h, "a": a,
                         "fh": fh, "fa": fa})
    print(f"LB {league}: {len(picks)} graded picks, {got} with play-by-play")


def evaluate(rs, sd_mult=1.0, pace_k=None):
    old_k = LM.PACE_K
    if pace_k is not None:
        LM.PACE_K = pace_k
    briers, lls, maes, cov_t, cov_m, cal = [], [], [], [], [], defaultdict(lambda: [0, 0.0, 0])
    for r in rs:
        c = LM.cfg(r["league"])
        keep = (c["sd"], c["total_sd"])
        c["sd"], c["total_sd"] = c["sd"] * sd_mult, c["total_sd"] * sd_mult
        try:
            rd = LM.project(r["league"], float(r["p"]["model_margin"]), float(r["p"]["model_total"]), r["h"], r["a"],
                            r["per"], r["cl"])
        finally:
            c["sd"], c["total_sd"] = keep
        y = 1.0 if r["fh"] > r["fa"] else 0.0 if r["fh"] < r["fa"] else 0.5
        pw = min(max(rd["win_home"], 1e-4), 1 - 1e-4)
        briers.append((pw - y) ** 2)
        lls.append(-(y * math.log(pw) + (1 - y) * math.log(1 - pw)))
        b = min(int(pw * 10), 9)
        cal[b][0] += 1
        cal[b][1] += pw
        cal[b][2] += y
        ft = r["fh"] + r["fa"]
        maes.append(abs(ft - rd["total"]))
        if rd["total_sd"] > 0.5:
            cov_t.append(abs(ft - rd["total"]) <= rd["total_sd"])
        if rd["margin_sd"] > 0.5:
            cov_m.append(abs((r["fh"] - r["fa"]) - rd["margin"]) <= rd["margin_sd"])
    LM.PACE_K = old_k
    n = len(rs) or 1
    return {"n": len(rs), "brier": sum(briers) / n, "ll": sum(lls) / n, "mae_total": sum(maes) / n,
            "cov_total": sum(cov_t) / max(len(cov_t), 1), "cov_margin": sum(cov_m) / max(len(cov_m), 1), "cal": cal}


for league in ("NBA", "NCAAMB", "NHL", "EUROLEAGUE"):
    rs = [r for r in rows if r["league"] == league]
    if not rs:
        continue
    print(f"\nLB ===== {league}: {len(rs)} checkpoints")
    base = evaluate(rs)
    print(f"LB as built: brier {base['brier']:.4f} logloss {base['ll']:.4f} total MAE {base['mae_total']:.2f} "
          f"within 1sd: total {base['cov_total']:.0%} margin {base['cov_margin']:.0%} (want ~68%)")
    for mult in (0.8, 1.2):
        e = evaluate(rs, sd_mult=mult)
        print(f"LB   spreads x{mult}: brier {e['brier']:.4f} logloss {e['ll']:.4f} within 1sd total {e['cov_total']:.0%} "
              f"margin {e['cov_margin']:.0%}")
    if league != "NHL":
        for k in (0.25, 0.5, 1.0, 2.0, 1000.0):
            e = evaluate(rs, pace_k=k)
            print(f"LB   pace weight K={k:g}: total MAE {e['mae_total']:.2f}")
    print("LB   win-chance calibration (band: n, said, happened):")
    for b in sorted(base["cal"]):
        n, s, y = base["cal"][b]
        if n >= 10:
            print(f"LB     {b * 10:2d}-{b * 10 + 10}%: n={n:4d} said {s / n:.0%} happened {y / n:.0%}")
    for cp in ("25%", "50%", "75%", "6 left", "2 left"):
        e = evaluate([r for r in rs if r["cp"] == cp])
        if e["n"]:
            print(f"LB   at {cp:>6}: n={e['n']:4d} brier {e['brier']:.4f} total MAE {e['mae_total']:.2f} "
                  f"cov total {e['cov_total']:.0%} margin {e['cov_margin']:.0%}")
