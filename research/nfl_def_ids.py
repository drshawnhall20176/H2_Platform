"""Why don't tonight's defender bets get player IDs? Print the model-read rows for them."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, parlay_check as PC
reads = BBD.load_slate_reads("NFL", "2026-11-05", "draftkings") or {}
print("reads:", len(reads))
for pl, mk in (("Roquan Smith", "Tackles + Assists"), ("Foyesade Oluokun", "Tackles + Assists"), ("Marlon Humphrey", "Solo Tackles")):
    row = PC._find(reads, pl, mk)
    print(pl, mk, "->", None if row is None else {k: row.get(k) for k in ("player", "pid", "market", "team_id", "line", "projection")})
    for (pid, k), r in reads.items():
        if pl.split()[-1].lower() in str(r.get("player")).lower():
            print("   key", pid, k, r.get("market"), r.get("pid"))
