"""Nov 18: lines the books posted that the model never read; your bets missing a closing price."""
import os, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, line_history as LH, model_view as MV, betlog as B, props_engine as PE
since = (date.today() - timedelta(days=14)).isoformat()
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    idx = LH.sport_index(sp, since)
    lines = defaultdict(set)            # date -> {(player, market)}
    for (pl, mk), rows in idx.items():
        for r in rows:
            d = str(r.get("captured_at"))[:10]
            lines[d].add((MV.norm_name(pl), MV.market_of(mk) or mk))
    snaps = MS.load_snapshots(sp, sorted(lines)) if lines else []
    reads = defaultdict(set)
    for s in snaps:
        reads[s["slate_date"]].add((MV.norm_name(s.get("player")), MV.market_of(s.get("market")) or s.get("market")))
    tot = miss = 0; mk_miss = Counter(); mk_tot = Counter(); ex = []
    for d in sorted(lines):
        if d >= date.today().isoformat(): continue
        have = reads.get(d, set()) | reads.get((date.fromisoformat(d) - timedelta(days=1)).isoformat(), set())
        for k in lines[d]:
            tot += 1; mk_tot[k[1]] += 1
            if k not in have:
                miss += 1; mk_miss[k[1]] += 1
                if len(ex) < 12: ex.append((d,) + k)
    if tot:
        print(f"COV {sp}: book lines captured {tot}, never read by the model {miss} ({miss/tot:.1%})")
        print(f"COV {sp} unread by market: " + ", ".join(f"{m} {mk_miss[m]}/{mk_tot[m]}" for m in sorted(mk_tot, key=lambda m: -mk_miss[m])[:14]))
        print(f"COV {sp} examples: {ex}")
    else:
        print(f"COV {sp}: no book lines captured in the last 14 days")
bets = B.list_bets()
settled = [b for b in bets if b.get("result") in ("win", "loss", "push")]
print(f"BETS settled {len(settled)}, with a closing price {sum(1 for b in settled if b.get('close_odds') is not None)}")
miss = Counter((b.get("sport"), b.get("market")) for b in settled if b.get("close_odds") is None)
print("BETS missing close by sport/market:", dict(miss.most_common(12)))
