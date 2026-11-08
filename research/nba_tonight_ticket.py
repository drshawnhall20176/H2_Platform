"""Nov 7: a ticket across tonight's remaining NBA games -- props model only, game scripts counted."""
import itertools
import os
import sys
from datetime import datetime, timezone

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD     # noqa: E402
import components as C           # noqa: E402
import props_engine as PE        # noqa: E402
import script_effects as SE      # noqa: E402

D = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
now = datetime.now(timezone.utc)
SE.refresh("NBA")
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", D, BBD.O.DEFAULT_BOOK)
pp = [p for p in plays if p.get("Model") == "player-props" and p.get("Side") in ("Over", "Under")
      and p.get("Line") is not None and p.get("ModelProb") is not None and p.get("LineSource") != "default"]
lines = SE.fetch_lines("NBA", [D.replace("-", "")])
calls = SE.calls("NBA")
games = {}
for p in pp:
    k = C._kick_dt(p.get("GameDate"))
    if k is None or k.astimezone(timezone.utc) <= now:
        continue
    games.setdefault(p["Game"], []).append(p)
print("NT games left", {g: len(v) for g, v in games.items()})
legs = []
for game, ps in games.items():
    teams = SE.game_teams([SE.from_play(p) for p in ps], game)
    g = SE.game_for(teams, lines)
    call = SE.scenario_call("NBA", teams, D, calls)
    sh = dict(call["p"]) if call else SE.scenario_probs("NBA", g["strength"] if g else None)[0]
    FN = SE.fav_names(g) if g else set()
    print("NT GAME", game, "| line", g and g["strength"], "fav", g and g["teams"][g["fav"]]["display"],
          "|", {k: f"{v:.0%}" for k, v in sh.items()})
    for p in ps:
        r = SE.from_play(p)
        grp = SE.group("NBA", r["market"], r.get("mins"))
        is_fav = bool(FN) and SE.team_matches(r.get("team"), FN)
        by = SE.over_by_script(r["p_over"], grp if FN else None, is_fav, sh, "NBA")
        ch = SE.side_chance(by, r["side"])
        price = p.get("RealPrice")
        if price is None:
            continue
        dec = PE.decimal(price)
        overall = sum(sh[s] * ch[s] for s in SE.SCRIPTS)
        legs.append({"game": game, "sh": sh, "player": r["player"], "market": r["market"], "side": r["side"],
                     "line": r["line"], "price": price, "ch": ch, "p": overall, "ev": overall * dec - 1,
                     "use": p.get("Use") or "", "grp": grp, "fav": is_fav})
PLAY = {PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE}
print("\nNT PLAYABLE / STRONG LEGS")
for x in sorted(legs, key=lambda x: (x["use"] not in PLAY, -x["ev"]))[:30]:
    print("NT LEG", f"{x['game'][:34]:34s} | {x['player']:22s} {x['market']:12s} {x['side']:5s} {x['line']:5.1f} {x['price']:+.0f}"
          f" | p {x['p']:.0%} ev {x['ev']:+.1%} | {x['use']} | {x['grp']}{' fav' if x['fav'] else ''}")
cands = [x for x in legs if x["p"] >= 0.55 and x["ev"] > -0.02]
cands.sort(key=lambda x: (x["use"] not in PLAY, -x["ev"]))
cands = cands[:18]


def ticket_p(combo):
    by_game = {}
    for c in combo:
        by_game.setdefault(c["game"], []).append(c)
    tot = 1.0
    for g, cs in by_game.items():
        sc, _, _ = SE.ticket([c["ch"] for c in cs], cs[0]["sh"])
        tot *= sc
    return tot


best = []
for k in (4, 5):
    for combo in itertools.combinations(cands, k):
        if len({c["player"] for c in combo}) < k:
            continue
        p = ticket_p(combo)
        dec = 1.0
        for c in combo:
            dec *= PE.decimal(c["price"])
        best.append((p * dec - 1, p, dec, combo))
best.sort(key=lambda t: -t[0])
print("\nNT BEST TICKETS by edge")
for ev, p, dec, combo in best[:6]:
    print("NT TICKET", len(combo), f"| chance {p:.1%} fair {SE.fair_american(p)} | price product +{(dec - 1) * 100:.0f} | edge {ev:+.0%}")
    for c in combo:
        print("NT    ", c["game"], "|", c["player"], c["market"], c["side"], c["line"], f"{c['price']:+.0f}", f"{c['p']:.0%}", c["use"])
