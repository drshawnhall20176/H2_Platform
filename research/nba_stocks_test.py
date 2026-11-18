"""Nov 18: dry run -- NBA board with steals / blocks on the props model (nothing written)."""
import os, sys, time
from collections import Counter
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, model_store as MS, slate_store as SS, sports
MS.save_reads = lambda *a, **k: 0
day = SS._today_et()
api = BBD.get_odds_api_key()
offers = BBD.fetch_generic_offers("NBA", day, api)
rows, meta = sports.get("NBA").engine.build_slate(day)
t0 = time.time()
reads = BBD.slate_reads_for("NBA", day, meta, offers, BBD.O.DEFAULT_BOOK) or {}
print("READS", len(reads), f"{time.time()-t0:.0f}s")
c = Counter(); tags = Counter(); ex = []
for (pid, mk), r in reads.items():
    if mk not in ("player_steals", "player_blocks", "player_blocks_steals") or r.get("line") is None: continue
    c[mk] += 1
    rec = MS.snapshot_record("NBA", day, r.get("game") or "", r, {"player_steals": "Steals", "player_blocks": "Blocks", "player_blocks_steals": "Blocks+Steals"}[mk])
    if rec: tags[(mk, rec["use_tag"])] += 1
    if len(ex) < 8: ex.append((r.get("player"), mk, r.get("line"), round(r.get("projection") or 0, 2), r.get("side"), round(r.get("p_final") or 0, 3), r.get("p_market")))
posted = Counter(o.get("market") for o in offers if o.get("market") in ("player_steals", "player_blocks", "player_blocks_steals"))
print("WITH LINE", dict(c), "| posted offers", dict(posted))
print("TAGS", dict(tags))
for e in ex: print("EX", e)
