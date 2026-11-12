"""Nov 12: log the owner's 6-leg DraftKings tennis parlay ($4 at +936), legs linked to the Tennis Lab records."""
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
            if len(I.tokens(p[side]) & I.tokens(player)) >= 2:
                return p, side
    return None, None


ticket = "DK tennis 6-leg Nov 12 (DK639300852972994975)"
if any(b.get("ticket") == ticket for b in B.list_bets()):
    print("LP already logged")
else:
    legs = []
    for name, odds in (("Alex Michelsen", -267), ("Coco Gauff", -296), ("Jessica Pegula", -101),
                       ("Alice Tubello", -247), ("Bianca Andreescu", -535), ("Andrea Lazaro Garcia", -143)):
        p, side = find(name)
        q = None if not p else (float(p["model_p"]) if side == "home" else 1 - float(p["model_p"]))
        legs.append({"player": p[side] if p else name, "market": "Moneyline", "side": p[side] if p else name,
                     "line": None, "game": f"{p['away']} @ {p['home']}" if p else None,
                     "model_prob": None if q is None else round(q, 4), "price": odds,
                     "note": f"{IP.TAG}:TENNIS:{p['game_id']}" if p else None})
        print("LP leg", name, "linked" if p else "NOT linked")
    print("LP", B.log_parlay_ticket(ticket, legs, 936, 4.0, "2026-11-12", "TENNIS", book="draftkings"))
