"""
research/backtest_tennis.py — does surface Elo beat the tennis betting market? (Nov 3)

1. Crawl every ATP / WTA singles match from ESPN since 2023 (Elo warms up on 2023-24).
2. Walk the matches in order: each gets its pre-match Elo chance.
3. For each 2025-26 tournament The Odds API prices, pull a historical snapshot the evening before each match day and
   match its events to ESPN's matches by the players' names.
4. Report: log loss (Elo vs the market's no-vig chance vs a blend), betting the side Elo likes at the best price by
   edge, and set/game handicaps and total games against the posted lines. Read-only.
"""
from __future__ import annotations

import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests  # noqa: E402

import hist_odds as H  # noqa: E402
import tennis_model as T  # noqa: E402

ODDS_FROM = date(2025, 1, 1)
STOP = {"open", "masters", "singles", "champ", "championships", "club", "atp", "wta", "tennis", "grand", "prix", "the"}
ALIAS = {"aus": ["australian open"], "french": ["roland garros", "french open"], "us_open": ["us open"],
         "indian": ["indian wells", "bnp paribas open"], "italian": ["internazionali", "italian", "rome"],
         "monte": ["monte"], "canadian": ["canadian", "national bank", "omnium"], "paris": ["paris"],
         "china": ["china open", "beijing"], "japan": ["japan", "tokyo"], "qatar": ["qatar", "doha"],
         "queens": ["queen"], "munich": ["munich", "bmw open"], "swiss": ["swiss indoors", "basel"],
         "vienna": ["vienna", "erste"], "washington": ["washington", "citi open", "mubadala"],
         "charleston": ["charleston", "credit one"], "german": ["berlin", "german"], "dubai": ["dubai"]}


def aliases(key: str):
    tour = "atp" if "_atp_" in key else ("wta" if "_wta_" in key else None)
    rest = key.split("_", 2)[2] if tour else key
    out = [w for w in rest.split("_") if len(w) > 3 and w not in STOP]
    for k, v in ALIAS.items():
        if k in rest:
            out += v
    if rest.startswith("us_open"):
        out = ["us open"]
    return tour, sorted(set(out))


def ll(p, y):
    p = min(1 - 1e-6, max(1e-6, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def same_player(a, b):
    ta, tb = set(T.norm(a).split()), set(T.norm(b).split())
    return bool(ta and tb and ta & tb and (T.norm(a).split()[-1] in tb or T.norm(b).split()[-1] in ta))


def main() -> int:
    t0 = datetime.now()
    end = date.today() - timedelta(days=1)
    matches = T.crawl(date(2023, 1, 1), end, step_days=2)
    print(f"crawled {len(matches)} completed singles matches 2023 → {end} in {(datetime.now() - t0).seconds}s")
    by_tour = defaultdict(int)
    for m in matches:
        by_tour[(m["tour"], m["date"][:4])] += 1
    print("by tour/year:", dict(sorted(by_tour.items())))
    elo, rows = T.run(matches)
    fit = T.fit_games([r for r in rows if r["date"] < "2025-01-01"])
    print("games fit:", {k: {kk: (round(vv, 2) if isinstance(vv, float) else [round(x, 2) for x in vv])
                             for kk, vv in v.items()} for k, v in fit.items()})

    # baseline: Elo log loss / accuracy on 2025-26 (all matches)
    test = [r for r in rows if r["date"] >= ODDS_FROM.isoformat() and r["status"] == "final"]
    acc = sum(1 for r in test if (r["p"] > 0.5) == (r["winner"] == 1)) / max(1, len(test))
    print(f"Elo on {len(test)} 2025-26 matches: accuracy {acc:.1%}, log loss "
          f"{sum(ll(r['p'], 1 if r['winner'] == 1 else 0) for r in test) / max(1, len(test)):.4f}")

    api = os.environ.get("ODDS_API_KEY")
    keys = [s["key"] for s in requests.get("https://api.the-odds-api.com/v4/sports",
                                           params={"apiKey": api, "all": "true"}, timeout=30).json()
            if s.get("group") == "Tennis" and ("_atp_" in s["key"] or "_wta_" in s["key"])]
    days_for = defaultdict(set)          # key -> match days
    tour_events = defaultdict(set)
    for r in test:
        tour_events[(r["tour"], r["tournament"])].add(r["date"])
    mapped = 0
    for k in keys:
        tour, al = aliases(k)
        for (tr, tn), ds in tour_events.items():
            if tr == tour and any(a in T.norm(tn) for a in al):
                days_for[k] |= ds
                mapped += 1
    print(f"{len(keys)} tennis odds keys; {mapped} key-tournament matches; "
          f"{sum(len(v) for v in days_for.values())} key-days to fetch")

    by_day = defaultdict(list)
    for r in test:
        by_day[r["date"]].append(r)
    priced = []
    for k, ds in sorted(days_for.items()):
        for d in sorted(ds):
            iso = (date.fromisoformat(d) - timedelta(days=1)).isoformat() + "T21:00:00Z"
            for ev in H.snapshot(k, iso):
                cd = str(ev.get("commence_time"))[:10]
                cand = by_day.get(cd, []) + by_day.get(d, [])
                hit = next((r for r in cand if (same_player(r["p1"], ev["home_team"]) and same_player(r["p2"], ev["away_team"]))
                            or (same_player(r["p1"], ev["away_team"]) and same_player(r["p2"], ev["home_team"]))), None)
                if not hit:
                    continue
                p1_name = ev["home_team"] if same_player(hit["p1"], ev["home_team"]) else ev["away_team"]
                p2_name = ev["away_team"] if p1_name == ev["home_team"] else ev["home_team"]
                o1, o2 = H.h2h(ev, p1_name), H.h2h(ev, p2_name)
                if o1["fair"] is None:
                    continue
                priced.append(dict(hit, mkt=o1["fair"], best1=o1["best"], best2=o2["best"], dk1=o1["dk"], dk2=o2["dk"],
                                   sp1=H.line(ev, "spreads", p1_name), tot_o=H.line(ev, "totals", "Over"),
                                   tot_u=H.line(ev, "totals", "Under")))
    seen = {}
    for r in priced:
        seen[r["id"]] = r
    priced = list(seen.values())
    print(f"\n{H.usage()}; {len(priced)} 2025-26 matches with a pre-match price\n")
    if not priced:
        return 0

    def report(rows, label):
        n = len(rows)
        if not n:
            return
        y = [1 if r["winner"] == 1 else 0 for r in rows]
        le = sum(ll(r["p"], yy) for r, yy in zip(rows, y)) / n
        lm = sum(ll(r["mkt"], yy) for r, yy in zip(rows, y)) / n
        lb = sum(ll(0.3 * r["p"] + 0.7 * r["mkt"], yy) for r, yy in zip(rows, y)) / n
        print(f"{label:38s} n={n:5d}  log loss: Elo {le:.4f} | market {lm:.4f} | 30/70 blend {lb:.4f}")

    print("```")
    report(priced, "all priced matches")
    report([r for r in priced if r["tour"] == "atp"], "ATP")
    report([r for r in priced if r["tour"] == "wta"], "WTA")
    report([r for r in priced if min(r["n1"], r["n2"]) >= 30], "both players 30+ rated matches")
    for s in T.SURFACES:
        report([r for r in priced if r["surface"] == s], f"surface {s}")

    print("\n-- betting the side Elo likes, best price across books (both players 30+ matches) --")
    for edge in (0.03, 0.05, 0.08, 0.12):
        for blend in (1.0, 0.5):
            bets = []
            for r in priced:
                if min(r["n1"], r["n2"]) < 30:
                    continue
                p = blend * r["p"] + (1 - blend) * r["mkt"]
                for side, pp, mk, price in ((1, p, r["mkt"], r["best1"]), (2, 1 - p, 1 - r["mkt"], r["best2"])):
                    if price is None or pp - mk < edge:
                        continue
                    win = r["winner"] == side
                    bets.append((H.decimal(price) - 1) if win else -1)
            if bets:
                print(f"edge >= {edge:.0%} (model weight {blend:.1f}): n={len(bets):4d}  hit "
                      f"{sum(1 for b in bets if b > 0) / len(bets):.1%}  profit/$1 {sum(bets) / len(bets):+.1%}")
        dk = []
        for r in priced:
            if min(r["n1"], r["n2"]) < 30:
                continue
            for side, pp, mk, price in ((1, r["p"], r["mkt"], r["dk1"]), (2, 1 - r["p"], 1 - r["mkt"], r["dk2"])):
                if price is None or pp - mk < edge:
                    continue
                dk.append((H.decimal(price) - 1) if r["winner"] == side else -1)
        if dk:
            print(f"   ... at DraftKings' price only: n={len(dk)}  profit/$1 {sum(dk) / len(dk):+.1%}")

    print("\n-- game handicaps and total games vs the posted lines --")
    for thr in (0.05, 0.10, 0.15):
        sp, tt = [], []
        for r in priced:
            g = T.games(fit, r["p"], r["best_of"])
            if not g or r["status"] != "final":
                continue
            if r.get("sp1"):
                pc = T.p_over(g["margin"], g["mar_sd"], -r["sp1"]["point"])   # P(p1 game margin + point > 0)
                actual = r["games1"] - r["games2"] + r["sp1"]["point"]
                if abs(pc - 0.5) >= thr and actual != 0:
                    sp.append((pc > 0.5) == (actual > 0))
            if r.get("tot_o"):
                po = T.p_over(g["total"], g["tot_sd"], r["tot_o"]["point"])
                actual = r["games1"] + r["games2"] - r["tot_o"]["point"]
                if abs(po - 0.5) >= thr and actual != 0:
                    tt.append((po > 0.5) == (actual > 0))
        print(f"model chance {thr:.0%}+ from 50%: game handicap {sum(sp)}/{len(sp)} "
              f"({(sum(sp) / len(sp)) if sp else 0:.1%}) · total games {sum(tt)}/{len(tt)} "
              f"({(sum(tt) / len(tt)) if tt else 0:.1%})  [need ~52.4% at -110]")
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
