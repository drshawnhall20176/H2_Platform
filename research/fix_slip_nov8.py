"""Nov 8: correct the 1 PM NFL slip to the owner's actual DraftKings bets."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
bets = B.list_bets()
sgp = [b for b in bets if B._ticket(b) == "CLE@NO SGP 11-08" or (b["id"] == 599)]
for b in sgp:
    B.delete_bet(b["id"]); print("FX deleted", b["id"], b.get("player"), b.get("market"))
hdr = next(b for b in bets if b["id"] == 602)
B.update_bet(602, stake=15.0, entry_odds=2048.0, notes=((hdr.get("notes") or "") + ",dk-boost-30pct").strip(","))
print("FX parlay 602 -> $15 @ +2048 (30% boost)")
have = {(b.get("player"), b.get("market"), b.get("side")) for b in bets if b.get("slate_date") == "2026-11-08" and not B._ticket(b)}
for pl, mk, sd, ln, od in (("Quinshon Judkins", "Receptions", "Over", 1.5, 100.0), ("Jordyn Tyson", "Receptions", "Under", 2.5, -126.0)):
    if (pl, mk, sd) in have:
        print("FX already", pl); continue
    i = B.add_bet(slate_date="2026-11-08", sport="NFL", game="CLE @ NO", player=pl, market=mk, side=sd, line=ln,
                  entry_odds=od, entry_odds_source="book", stake=5.0, book="draftkings", is_real_bet=True,
                  category=B.default_category("NFL", from_model=False), notes="user-slip")
    print("FX single", i, pl, mk, sd, ln, od)
for b in B.list_bets():
    if b.get("slate_date") == "2026-11-08" and b.get("sport") == "NFL" and b.get("is_real_bet"):
        print("FX NOW", b["id"], B._ticket(b) or "single", b.get("player") or b.get("market"), b.get("side"), b.get("line"), b.get("entry_odds"), b.get("stake"), b.get("model_prob"))
