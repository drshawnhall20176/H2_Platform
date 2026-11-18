"""Nov 18: does the college basketball board now read every posted line through the props model? (no snapshot writes)"""
import os, sys, time
from collections import Counter
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, model_store as MS, slate_store as SS
MS.save_reads = lambda *a, **k: 0                      # dry run: don't write today's snapshots from here
day = SS._today_et()
t0 = time.time()
api = BBD.get_odds_api_key()
offers = BBD.fetch_generic_offers("NCAAMB", day, api)
import sports
rows, meta = BBD._big_slate_props_games(sports.get("NCAAMB"), "NCAAMB", day, api)
print("META games", len(meta), "offers", len(offers), f"{time.time()-t0:.0f}s")
reads = BBD.slate_reads_for("NCAAMB", day, meta, offers, BBD.O.DEFAULT_BOOK)
print("READS", 0 if not reads else len(reads), f"{time.time()-t0:.0f}s")
if reads:
    withline = [r for r in reads.values() if r.get("line") is not None]
    print("WITH LINE", len(withline), Counter(r.get("market") for r in withline).most_common())
    tags = Counter()
    for r in withline:
        rec = MS.snapshot_record("NCAAMB", day, r.get("game") or "", r, r.get("market") or "")
        if rec: tags[rec["use_tag"]] += 1
    print("TAGS", dict(tags))
    for r in list(withline)[:8]:
        print("EX", r.get("player"), r.get("market"), r.get("line"), round(r.get("projection") or 0, 1), r.get("side"), r.get("p_final"))
posted = {(o.get("player") or o.get("description"), o.get("market")) for o in offers}
print("POSTED player-market lines", len(posted))
