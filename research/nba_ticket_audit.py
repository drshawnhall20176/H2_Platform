"""Nov 7 7:30pm: full audit for tonight's remaining NBA games -- live prices (every book), Desk angles, injury news,
game scripts, Use tags -- then a principled search over 4-5 leg tickets."""
import itertools
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytz
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyst as A                  # noqa: E402
import analyst_publisher as AP       # noqa: E402
import best_bets_data as BBD         # noqa: E402
import components as C               # noqa: E402
import line_history as LH            # noqa: E402
import props_engine as PE            # noqa: E402
import script_effects as SE          # noqa: E402
import sports                        # noqa: E402

ET = pytz.timezone("US/Eastern")
D = datetime.now(ET).strftime("%Y-%m-%d")
cut = datetime.now(timezone.utc) + timedelta(minutes=10)
SE.refresh("NBA")
deps = AP.default_deps()
key = deps["api_key"]()
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", D, BBD.O.DEFAULT_BOOK)
pp = [p for p in plays if p.get("Model") == "player-props" and p.get("Side") in ("Over", "Under")
      and p.get("Line") is not None and p.get("ModelProb") is not None and p.get("LineSource") != "default"
      and (C._kick_dt(p.get("GameDate")) or cut) > cut]
print("AU plays", len(pp), "games", sorted({p['Game'] for p in pp}))

# ---- live prices, every book
offers = deps["fetch_offers"]("NBA", D, key) or []
omap = sports.get("NBA").market_map
idx = A.index_offers(offers)
print("AU offers", len(offers), "| sample offer", offers[0] if offers else None)
print("AU idx sample key", next(iter(idx), None), "| value", (next(iter(idx.values()), None) or [None])[:2])

# ---- Desk angles (same inputs as the page, evidence on)
game_env, _ = deps["game_env"]("NBA", D, meta, key)
matchups, _ = deps["matchups"]("NBA", D)
lidx = LH.sport_index("NBA", (datetime.now(ET) - timedelta(days=14)).strftime("%Y-%m-%d"))
hist = A.history_lookup(lidx, omap)
calls = A.scan(pp, "NBA", D, offers=offers, odds_map=omap, history_fn=hist, expect_book_lines=True, book="draftkings",
               game_env=game_env, matchups=matchups, history_limit=len(pp))
angles = {}
print("AU calls", len(calls), "| sample call keys", sorted(calls[0].keys())[:40] if calls else None)
for c in calls:
    angles[(PE.norm_name(c.get("Player") or ""), c.get("Market"), c.get("Side"))] = A.angle_names(c)

# ---- injuries (ESPN, all teams)
inj = {}
try:
    j = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries", timeout=20,
                     headers={"User-Agent": "Mozilla/5.0"}).json()
    for t in j.get("injuries") or []:
        for it in t.get("injuries") or []:
            nm = ((it.get("athlete") or {}).get("displayName") or "")
            inj[PE.norm_name(nm)] = (it.get("status") or "", (t.get("displayName") or ""), (it.get("shortComment") or "")[:90])
except Exception as e:
    print("AU injuries failed", e)
teams_tonight = {p.get("Team") for p in pp}
print("AU injury report for tonight's teams:")
for nm, (st, tm, cm) in sorted(inj.items(), key=lambda x: x[1][1]):
    if any(tm and tm in (t or "") or (t or "") in tm for t in teams_tonight):
        print("AU   INJ", tm, "|", nm, "|", st, "|", cm)

# ---- every leg: script-adjusted chance, live price, angles, flags
lines = SE.fetch_lines("NBA", [D.replace("-", "")])
callsS = SE.calls("NBA")
legs = []
for p in pp:
    r = SE.from_play(p)
    ps = [q for q in pp if q["Game"] == p["Game"]]
    teams = SE.game_teams([SE.from_play(q) for q in ps], p["Game"])
    g = SE.game_for(teams, lines)
    call = SE.scenario_call("NBA", teams, D, callsS)
    sh = dict(call["p"]) if call else SE.scenario_probs("NBA", g["strength"] if g else None)[0]
    FN = SE.fav_names(g) if g else set()
    grp = SE.group("NBA", r["market"], r.get("mins"))
    is_fav = bool(FN) and SE.team_matches(r.get("team"), FN)
    by = SE.over_by_script(r["p_over"], grp if FN else None, is_fav, sh, "NBA")
    ch = SE.side_chance(by, r["side"])
    pch = sum(sh[s] * ch[s] for s in SE.SCRIPTS)
    o = idx.get((A._norm(r["player"]), omap.get(r["market"]))) or []
    dk = [x for x in o if x.get("book") == "draftkings" and str(x.get("side", "")).lower() == r["side"].lower()]
    same = [x for x in dk if x.get("line") is not None and float(x["line"]) == float(r["line"])]
    live_price = same[0]["price"] if same else None
    live_line = dk[0]["line"] if dk else None
    others = [x["price"] for x in o if x.get("book") != "draftkings" and str(x.get("side", "")).lower() == r["side"].lower()
              and x.get("line") is not None and float(x["line"]) == float(r["line"]) and x.get("price") is not None]
    price = live_price if live_price is not None else None
    ev = pch * PE.decimal(price) - 1 if price is not None else None
    st = inj.get(PE.norm_name(r["player"]))
    team_out = [nm for nm, (s, tm, _) in inj.items() if s.lower() in ("out", "doubtful") and tm and r.get("team") and
                (tm in r["team"] or r["team"] in tm)]
    legs.append({"game": p["Game"], "kick": p.get("GameDate"), "sh": sh, "player": r["player"], "team": r.get("team"),
                 "market": r["market"], "side": r["side"], "line": r["line"], "board_price": p.get("RealPrice"),
                 "price": price, "live_line": live_line, "others": others, "p": pch, "ch": ch, "ev": ev,
                 "use": p.get("Use") or "", "lean": p.get("Lean"), "grp": grp, "fav": is_fav,
                 "angles": angles.get((PE.norm_name(r["player"]), r["market"], r["side"]), []),
                 "inj": st, "team_out": team_out[:4], "proj": r.get("projection"), "cushion": p.get("Cushion")})

PLAY = {PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE}
PARLAY_OK = {PE.USE_BOTH, PE.USE_PARLAY}


def flags(x):
    f = []
    if x["inj"]:
        f.append(f"injury: {x['inj'][0]}")
    if x["price"] is None:
        f.append("no live DK price at this line" + (f" (now {x['live_line']})" if x["live_line"] is not None else ""))
    if x["lean"] == "Check news":
        f.append("check news")
    return f


print("\nAU EVERY PLAYABLE-TAGGED LEG (live)")
for x in sorted([x for x in legs if x["use"] in PLAY], key=lambda x: -(x["ev"] if x["ev"] is not None else -9)):
    print("AU LEG", f"{x['game'][:30]:30s} | {x['player']:22s} {x['market']:12s} {x['side']:5s} {x['line']:5.1f}"
          f" | board {x['board_price']} live {x['price']} others {sorted(x['others'])[:4]} | p {x['p']:.0%}"
          f" ev {('%+.1f%%' % (100 * x['ev'])) if x['ev'] is not None else '—'} | {x['use']} | angles {x['angles']}"
          f" | flags {flags(x)} | teammates out {x['team_out']}")

pool = [x for x in legs if x["use"] in PLAY and not flags(x) and x["ev"] is not None and x["ev"] > 0]
print("\nAU POOL", len(pool))


def tp(combo):
    by = defaultdict(list)
    for c in combo:
        by[c["game"]].append(c)
    out = 1.0
    for cs in by.values():
        out *= SE.ticket([c["ch"] for c in cs], cs[0]["sh"])[0]
    return out


res = []
for k in (4, 5):
    for combo in itertools.combinations(pool, k):
        if len({c["player"] for c in combo}) < k:
            continue
        if max(sum(1 for c in combo if c["game"] == g) for g in {c["game"] for c in combo}) > 2:
            continue
        singles = sum(1 for c in combo if c["use"] not in PARLAY_OK)
        p = tp(combo)
        dec = 1.0
        for c in combo:
            dec *= PE.decimal(c["price"])
        res.append({"k": k, "p": p, "dec": dec, "ev": p * dec - 1, "singles": singles,
                    "angles": sum(len(c["angles"]) for c in combo), "combo": combo})
for rule, f in (("platform-clean (parlay-tagged legs only)", lambda r: r["singles"] == 0),
                ("at most one Single-only leg", lambda r: r["singles"] <= 1)):
    rs = sorted([r for r in res if f(r)], key=lambda r: (-r["ev"]))[:4]
    print(f"\nAU BEST — {rule}: {len(rs)} shown")
    for r in rs:
        print("AU TICKET", r["k"], f"| chance {r['p']:.1%} fair {SE.fair_american(r['p'])} | live price product +{(r['dec'] - 1) * 100:.0f}"
              f" | edge {r['ev']:+.0%} | single-only legs {r['singles']} | angles {r['angles']}")
        for c in r["combo"]:
            print("AU    ", c["game"], "|", c["player"], c["market"], c["side"], c["line"], c["price"], f"{c['p']:.0%}", c["use"], c["angles"])
