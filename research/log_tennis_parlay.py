"""Nov 19: log the owner's DK 3-pick tennis parlay (DK639306916007940223) -- owner asked in chat. Idempotent."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS, intl_hoops as I
TICKET = "DK 3-pick 11/19 tennis"
if any(B._ticket(b) == TICKET for b in B.list_bets()):
    print("LT already logged"); sys.exit(0)
picks = [p for p in MS.load_game_picks("TENNIS") if str(p.get("kickoff"))[:10] in ("2026-11-19", "2026-11-20")]
def link(name):
    for p in picks:
        if I.find_team([p["home"]], name, True) or I.find_team([p["away"]], name, True):
            return p
    return None
legs = [("Ben Shelton", "Rafael Jodar", -428, "live bet, placed in the 1st set"),
        ("Alexander Zverev", "Arthur Fils", -248, ""),
        ("Veronika Erjavec", "Valeriya Strakhova", -394, "")]
common = dict(slate_date="2026-11-19", sport="TENNIS", book="draftkings", ticket=TICKET, is_real_bet=True,
              ts_placed="2026-11-19T13:26:41+00:00")
hid = B.add_bet(game="Multiple games", market="Parlay", side="3-leg parlay", entry_odds=117, stake=5.72,
                entry_odds_source="manual", category="PARLAY",
                notes="DK 3-pick parlay, to pay $12.41, DK639306916007940223", **common)
print("LT header", hid)
for me, opp, odds, note in legs:
    p = link(me)
    game = f"{p['away']} @ {p['home']}" if p else f"{opp} @ {me}"
    tags = ([f"gl:TENNIS:{p['game_id']}"] if p else []) + ([note] if note else [])
    bid = B.add_bet(game=game, market="Moneyline", side=me, line=0.0, entry_odds=odds, stake=0.0,
                    entry_odds_source="book", category="PARLAY", notes=", ".join(tags), **common)
    print("LT leg", bid, me, odds, game, "linked" if p else "NOT LINKED")
