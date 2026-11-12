"""Nov 12: the live football read on past games (NFL + FBS college). Pre-game line = ESPN pick center (the books);
score, clock and the drive in progress from ESPN play-by-play. Checkpoints: 25/50/75% played, 5 and 2 minutes left.
Scores the win chance (Brier), and how often the final margin / total land inside one sd -- with and without the
drive-in-progress term, and with the spreads scaled x0.8 / x1.2. Free, read-only."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I                                           # noqa: E402
import live_games as LG                                          # noqa: E402
import live_model as LM                                          # noqa: E402


def clock_min(txt):
    try:
        mm, ss = str(txt).split(":")[:2]
        return int(mm) + float(ss) / 60
    except (ValueError, TypeError):
        return None


def game_states(league, ev_id):
    s = I._http(f"https://site.api.espn.com/apis/site/v2/sports/{LG.ESPN_PATH[league]}/summary", {"event": ev_id}) or {}
    pre = None
    for pc in s.get("pickcenter") or []:
        sp, ou = I._num(pc.get("spread")), I._num(pc.get("overUnder"))
        if sp is not None and ou is not None:
            pre = (-sp, ou)
            break
    comp = ((s.get("header") or {}).get("competitions") or [{}])[0]
    home_id = next((str(t.get("id")) for t in comp.get("competitors") or [] if t.get("homeAway") == "home"), None)
    fin = {t.get("homeAway"): I._num(t.get("score")) for t in comp.get("competitors") or []}
    if not pre or home_id is None or fin.get("home") is None:
        return None
    out = []
    for d in (s.get("drives") or {}).get("previous") or []:
        tid = str((d.get("team") or {}).get("id") or "")
        for p in d.get("plays") or []:
            per = (p.get("period") or {}).get("number")
            cl = clock_min((p.get("clock") or {}).get("displayValue"))
            if per is None or cl is None or p.get("homeScore") is None:
                continue
            ytg = I._num((p.get("start") or {}).get("yardsToEndzone"))
            out.append((LM.elapsed(league, per, cl), per, cl, float(p["homeScore"]), float(p["awayScore"]),
                        "home" if tid == home_id else "away", ytg))
    return {"pre": pre, "states": sorted(out), "fh": fin["home"], "fa": fin["away"]}


def events(league, start, end):
    ids = []
    d = start
    while d <= end:
        params = {"dates": d.strftime("%Y%m%d"), "limit": 500}
        if league == "NCAAF":
            params["groups"] = 80
        data = I._http(LG.ESPN_URL[league], params) or {}
        for ev in data.get("events") or []:
            st = ((ev.get("competitions") or [{}])[0].get("status") or {}).get("type") or {}
            if st.get("completed"):
                ids.append(ev["id"])
        d += timedelta(days=1)
    return list(dict.fromkeys(ids))


rows = []
for league, n_max in (("NFL", 200), ("NCAAF", 400)):
    ids = events(league, date(2026, 9, 25), date(2026, 11, 10))[-n_max:]
    with ThreadPoolExecutor(8) as ex:
        gs = [g for g in ex.map(lambda e: game_states(league, e), ids) if g and g["states"]]
    print(f"FB {league}: {len(ids)} games, {len(gs)} with a line and play-by-play")
    L = LM.game_minutes(league)
    for g in gs:
        for name, t in (("25%", 0.25 * L), ("50%", 0.5 * L), ("75%", 0.75 * L), ("5 left", L - 5), ("2 left", L - 2)):
            b = [s for s in g["states"] if s[0] <= t]
            if b:
                rows.append({"league": league, "cp": name, "s": b[-1], "pre": g["pre"], "fh": g["fh"], "fa": g["fa"]})


def ev(rs, mult=1.0, use_ep=True):
    br = cm = ct = 0.0
    for r in rs:
        c = LM.cfg(r["league"])
        keep = (c["sd"], c["total_sd"])
        c["sd"], c["total_sd"] = c["sd"] * mult, c["total_sd"] * mult
        e, per, cl, h, a, poss, ytg = r["s"]
        rd = LM.project(r["league"], r["pre"][0], r["pre"][1], h, a, per, cl,
                        possession=poss if use_ep else None, yards_to_go=ytg)
        c["sd"], c["total_sd"] = keep
        y = 1.0 if r["fh"] > r["fa"] else 0.0 if r["fh"] < r["fa"] else 0.5
        br += (rd["win_home"] - y) ** 2
        cm += abs((r["fh"] - r["fa"]) - rd["margin"]) <= rd["margin_sd"]
        ct += abs((r["fh"] + r["fa"]) - rd["total"]) <= rd["total_sd"]
    n = max(len(rs), 1)
    return br / n, cm / n, ct / n


for league in ("NFL", "NCAAF"):
    rs = [r for r in rows if r["league"] == league]
    if not rs:
        continue
    print(f"\nFB ===== {league}: {len(rs)} checkpoints")
    for label, kw in (("as built", {}), ("no drive term", {"use_ep": False}), ("spreads x0.8", {"mult": 0.8}),
                      ("spreads x1.2", {"mult": 1.2})):
        b, m, t = ev(rs, **kw)
        print(f"FB {label:>14}: brier {b:.4f}  within 1sd margin {m:.0%} total {t:.0%} (want ~68%)")
    for cp in ("25%", "50%", "75%", "5 left", "2 left"):
        sub = [r for r in rs if r["cp"] == cp]
        b, m, t = ev(sub)
        b0, _, _ = ev(sub, use_ep=False)
        print(f"FB   at {cp:>6}: n={len(sub)} brier {b:.4f} (no drive term {b0:.4f}) cov margin {m:.0%} total {t:.0%}")
