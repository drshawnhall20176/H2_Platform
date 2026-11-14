"""Nov 14 morning check: close parlay #670 (Fritz leg void, Musetti won -> paid at Musetti's -197); look for
Andreeva v Muchova (Nov 13) in the tennis results."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS
bets = B.list_bets()
for s in B.ticket_settlements(bets):
    print("ticket settles", s)
h = next(b for b in bets if b["id"] == 670)
if not h.get("result"):
    B.update_bet(670, result="win", entry_odds=-197,
                 notes=((h.get("notes") or "") + " | Fritz leg void (Rune walkover); paid as Musetti single at -197").strip(" |"))
    print("670 ->", {k: v for k, v in next(b for b in B.list_bets() if b["id"] == 670).items() if k in ("result", "entry_odds", "stake", "notes")})
hist = MS.load_results("TENNIS")
hits = [m for m in hist if "Andreeva" in str(m.get("p1")) + str(m.get("p2")) or "Muchova" in str(m.get("p1")) + str(m.get("p2"))]
for m in sorted(hits, key=lambda x: str(x.get("date")))[-4:]:
    print("RESULT", {k: m.get(k) for k in ("date", "p1", "p2", "winner", "status", "games1", "games2", "full_sets")})
print("latest results date:", max(str(m.get("date")) for m in hist))
import tennis_model as T
try:
    import intl_hoops as I
    for tour in ("wta",):
        data = I._http(f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard", {"dates": "20261113"})
        for e in (data or {}).get("events") or []:
            for g in e.get("groupings") or []:
                for c in g.get("competitions") or []:
                    names = [x.get("athlete", {}).get("displayName") for x in c.get("competitors") or []]
                    if any("Andreeva" in str(n) or "Muchova" in str(n) for n in names):
                        print("ESPN", names, c.get("status", {}).get("type", {}).get("name"), c.get("date"))
except Exception as e:
    print("espn err", e)
