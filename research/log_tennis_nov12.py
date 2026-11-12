"""Nov 12: log the owner's DraftKings tennis slips (six $1 singles + a 2-leg parlay), linked to the Tennis Lab's
records so they settle themselves when the matches are graded. Skips anything already logged."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B           # noqa: E402
import intl_hoops as I       # noqa: E402
import intl_picks as IP      # noqa: E402
import model_store as MS     # noqa: E402

picks = [p for p in MS.load_game_picks("TENNIS") if str(p.get("kickoff", ""))[:10] in ("2026-11-12", "2026-11-13")]


def find(player):
    for p in picks:
        for side in ("home", "away"):
            if I.same_team(p[side], player) and len(I.tokens(p[side]) & I.tokens(player)) >= 2:
                return p, side
    return None, None


existing = B.list_bets()
have = {(str(b.get("notes")), b.get("entry_odds"), float(b.get("stake") or 0)) for b in existing}
singles = [("Alex Michelsen", -267), ("Coco Gauff", -296), ("Jessica Pegula", -101), ("Alice Tubello", -247),
           ("Bianca Andreescu", -535), ("Andrea Lazaro Garcia", -143)]
for name, odds in singles:
    p, side = find(name)
    if not p:
        print("LT no Tennis Lab record for", name)
        continue
    q = float(p["model_p"]) if side == "home" else 1 - float(p["model_p"])
    f = IP.bet_fields(p, "Moneyline", side, None, odds, 1.0, True, model_prob=round(q, 4))
    f["book"] = "draftkings"
    f["slate_date"] = "2026-11-12"
    if (f["notes"], float(odds), 1.0) in have:
        print("LT already logged", name)
        continue
    bid = B.add_bet(**f)
    print("LT single", bid, name, odds, f["game"], f["notes"])

legs = []
for name, odds in (("Taylor Fritz", -229), ("Lorenzo Musetti", -197)):
    p, side = find(name)
    if not p:
        print("LT no record for parlay leg", name)
        continue
    q = float(p["model_p"]) if side == "home" else 1 - float(p["model_p"])
    legs.append({"player": p[side], "market": "Moneyline", "side": p[side], "line": None,
                 "game": f"{p['away']} @ {p['home']}", "model_prob": round(q, 4), "price": odds,
                 "note": f"{IP.TAG}:TENNIS:{p['game_id']}"})
ticket = "DK tennis 2-leg Nov 12 (DK639300989842276350)"
if any(b.get("ticket") == ticket for b in existing):
    print("LT parlay already logged")
elif len(legs) == 2:
    r = B.log_parlay_ticket(ticket, legs, -196, 3.67, "2026-11-12", "TENNIS", book="draftkings")
    print("LT parlay", r)
