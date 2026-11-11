"""
Nov 10: are teammates' alternate lines underpriced in the morning when a rotation player ends up sitting?
(Fears' 8+ assists went +1840 -> +457 during the day.) A "late scratch" = a player the books posted a line for
(so he wasn't ruled out early -- usually questionable) who then didn't play: his saved model read grades "void".
Uses only saved data (no credits): the 11am / 3pm / 5:30pm / tip-off DraftKings alternate prices saved for 10 nights.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import long_shots as LS                                          # noqa: E402
import model_store as MS                                         # noqa: E402
import postgame as PG                                            # noqa: E402
import props_engine as PE                                        # noqa: E402
import sports                                                    # noqa: E402

ARCH = {"am": ["long_shots_alt_am"], "t15": ["long_shots_alt_t15"], "t1730": ["long_shots_alt_t1730"],
        "close": ["long_shots_alt"]}


def price_map(quotes):
    d = {}
    for q in quotes or []:
        main = LS.ALT_TO_MAIN.get(q.get("market"))
        if main and str(q.get("name")).lower() == "over" and q.get("point") is not None:
            d[(PE.norm_name(q.get("description") or ""), main, float(q["point"]) + 0.5)] = float(q["price"])
    return d


def dec(p):
    return 1 + (p / 100 if p > 0 else 100 / -p)


rows, scratches = [], []
dates = [d for d in MS.snapshot_dates("NBA") if "2026-10-21" <= d <= "2026-11-09"]
for day in sorted(dates):
    _r, meta = sports.get("NBA").engine.build_slate(day)
    by_label = {m["label"]: m for m in meta}
    snaps = MS.load_snapshots("NBA", [day])
    graded = PG.grade(snaps, PG.fetch_results("NBA", day, sorted({(s["team"], s["opp"]) for s in snaps})))
    # late scratches: a line was posted, he didn't play, and he was expected to play real minutes
    out_by_team = defaultdict(list)
    for s in graded:
        if s["result"] == "void" and (s.get("proj_opp") or 0) >= 20 and s.get("market") == "Points":
            out_by_team[(s["game"], s["team"])].append((s["player"], s.get("proj_opp"), s.get("projection")))
    for k, v in out_by_team.items():
        for p in v:
            scratches.append((day, k[0], k[1], p))
    for lab, m in by_label.items():
        maps = {mo: price_map((MS.load_odds("NBA", day, m["home_name"], m["away_name"], key) or {}).get("offers"))
                for mo, key in ARCH.items()}
        if not maps["am"]:
            continue
        game = [s for s in graded if s.get("game") == lab and s["result"] != "void"]
        for r in LS.lookback(game, [], PE.norm_name):
            if r["Hit"] is None:
                continue
            k = (PE.norm_name(r["Player"]), LS._MAIN_KEY.get(r["Market"]), float(r["_n"]))
            pr = {mo: maps[mo].get(k) for mo in ARCH}
            if pr["am"] is None:
                continue
            team = next((s["team"] for s in game if s["player"] == r["Player"]), None)
            outs = out_by_team.get((lab, team)) or []
            rows.append(dict(r, night=day, team=team, n_out=len(outs), out_min=sum(o[1] or 0 for o in outs),
                             **{f"p_{mo}": v for mo, v in pr.items()}))

print(f"late scratches found: {len(scratches)}")
for s in scratches:
    print("   ", s)
print(f"rungs with an 11am price: {len(rows)}; on teams with a late scratch: {sum(r['n_out'] > 0 for r in rows)}")


def report(name, picks, moment):
    picks = [r for r in picks if r.get(f"p_{moment}")]
    if not picks:
        print(f"  {name} @ {moment}: none")
        return
    pl = sum((dec(r[f"p_{moment}"]) - 1) if r["Hit"] == "✅" else -1 for r in picks)
    hits = sum(r["Hit"] == "✅" for r in picks)
    print(f"  {name} @ {moment}: n={len(picks)} hit {hits} (book implied "
          f"{sum(LS.implied(r[f'p_{moment}']) for r in picks):.1f}, honest {sum(r['Honest chance'] for r in picks):.1f})"
          f" ROI {pl / len(picks):+.1%}")


for mo in ARCH:
    print(f"\n== bet at {mo}")
    report("no teammate scratched (baseline)", [r for r in rows if r["n_out"] == 0], mo)
    report("teammate scratched late", [r for r in rows if r["n_out"] > 0], mo)
    report("  ...25+ projected minutes scratched", [r for r in rows if r["out_min"] >= 25], mo)
    for mk in ("Assists", "Points", "Rebounds", "Threes Made", "PRA"):
        report(f"  ...{mk}", [r for r in rows if r["n_out"] > 0 and r["Market"] == mk], mo)
    report("  ...and the page called it value (EV>0 at 11am)", [r for r in rows if r["n_out"] > 0 and
                                                               r["Honest chance"] * dec(r["p_am"]) > 1], mo)

# how much did teammates' prices move from 11am to tip-off, scratch vs not?
for name, sel in (("scratch", lambda r: r["n_out"] > 0), ("no scratch", lambda r: r["n_out"] == 0)):
    pairs = [r for r in rows if sel(r) and r.get("p_close")]
    if pairs:
        up = sum(LS.implied(r["p_close"]) > LS.implied(r["p_am"]) * 1.15 for r in pairs)
        print(f"\n{name}: price shortened 15%+ from 11am to tip-off on {up}/{len(pairs)} ({up / len(pairs):.0%})")
