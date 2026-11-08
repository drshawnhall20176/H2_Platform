"""Nov 7: Game Script read for Knicks @ Cavaliers -- every prop under each script, and the best 4-5 leg tickets."""
import itertools
import os
import sys
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD     # noqa: E402
import props_engine as PE        # noqa: E402
import script_effects as SE      # noqa: E402

D = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
SE.refresh("NBA")
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", D, BBD.O.DEFAULT_BOOK)
gp = [p for p in plays if "Knicks" in str(p.get("Game")) and "Cavaliers" in str(p.get("Game"))
      and p.get("Side") in ("Over", "Under") and p.get("Line") is not None and p.get("ModelProb") is not None
      and p.get("LineSource") != "default"]
print("KC game", gp[0]["Game"] if gp else None, "props", len(gp))
teams = sorted({p.get("Team") for p in gp})
call = SE.scenario_call("NBA", teams + ["New York Knicks", "Cleveland Cavaliers"], D)
lines = SE.fetch_lines("NBA", [D.replace("-", "")])
g = SE.game_for(["New York Knicks", "Cleveland Cavaliers"], lines)
fav = g["teams"][g["fav"]]["display"] if g else (call or {}).get("fav")
sh = dict(call["p"]) if call else SE.scenario_probs("NBA", g["strength"] if g else None)[0]
print("KC line", g and g["strength"], "fav", fav, "source", (call or {}).get("source"), "scripts", {k: round(v, 3) for k, v in sh.items()})
FN = SE.fav_names(g) if g else {SE.norm(fav)}
rows = []
for p in gp:
    r = SE.from_play(p)
    grp = SE.group("NBA", r["market"], r.get("mins"))
    is_fav = SE.team_matches(r.get("team"), FN)
    by = SE.over_by_script(r["p_over"], grp, is_fav, sh, "NBA")
    mins = SE.minutes_by_script("NBA", r.get("mins"), is_fav, sh)
    for side in ("Over", "Under"):
        price = p.get("RealPrice") if side == p["Side"] else None
        ch = SE.side_chance(by, side)
        overall = sum(sh[s] * ch[s] for s in SE.SCRIPTS)
        rows.append({"player": r["player"], "team": (r.get("team") or "").split()[-1], "fav": is_fav, "grp": grp,
                     "mins": r.get("mins"), "market": r["market"], "line": r["line"], "side": side, "price": price,
                     "ch": ch, "overall": overall, "use": p.get("Use") if side == p["Side"] else "", "minby": mins,
                     "proj": r.get("projection")})
print("\nKC TOP SIDES (overall >= 55%):")
for x in sorted([x for x in rows if x["overall"] >= 0.55], key=lambda x: -x["overall"])[:40]:
    print("KC", f"{x['player']:24s} {x['team']:9s} {str(x['grp']):18s} min {x['mins'] or 0:4.1f} {x['market']:12s} {x['side']:5s} {x['line']:5.1f}"
          f" | all {x['overall']:.0%} close {x['ch']['close']:.0%} mid {x['ch']['middle']:.0%} favBO {x['ch']['fav_blowout']:.0%} dogBO {x['ch']['dog_blowout']:.0%}"
          f" | price {x['price']} | proj {x['proj']} | {x['use']}")
# tickets: priced legs only (the side the board prices), one leg per player, 4-5 legs
cands = [x for x in rows if x["price"] is not None and x["overall"] >= 0.55]
cands.sort(key=lambda x: -x["overall"])
cands = cands[:16]
best = []
for k in (4, 5):
    for combo in itertools.combinations(cands, k):
        if len({c["player"] for c in combo}) < k:
            continue
        legs = [c["ch"] for c in combo]
        scripted, plain, per = SE.ticket(legs, sh)
        dec = 1.0
        for c in combo:
            dec *= PE.decimal(c["price"])
        best.append((scripted, plain, per, combo, dec))
best.sort(key=lambda t: -t[0])
print("\nKC BEST TICKETS (chance counting scripts):")
for scripted, plain, per, combo, dec in best[:8]:
    print("KC TICKET", len(combo), "legs | scripted", f"{scripted:.1%}", "plain", f"{plain:.1%}", "| fair", SE.fair_american(scripted),
          "| book-price product", f"+{(dec - 1) * 100:.0f}", "| per script", {s: f"{v:.0%}" for s, v in per.items()})
    for c in combo:
        print("KC    ", c["player"], c["market"], c["side"], c["line"], c["price"], f"{c['overall']:.0%}", c["use"])
