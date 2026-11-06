"""Nov 6: which logged bets get a closing price, and which don't (by sport, market, book, kind)."""
import os, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, sports
bets = [b for b in B.money_bets(B.list_bets()) if str(b.get("slate_date") or "") >= "2026-10-30"]
print(f"{len(bets)} money rows since Oct 30")
def cov(rows):
    n = len(rows); h = sum(1 for b in rows if b.get("close_odds") is not None)
    return f"{h:4d}/{n:4d} ({h / n:.0%})" if n else "0/0"
for key in ("sport", "book"):
    g = defaultdict(list)
    for b in bets:
        g[b.get(key) or "—"].append(b)
    print(f"-- by {key}")
    for k, rs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        print(f"   {k:24s} {cov(rs)}")
print("-- by kind")
print("   parlay headers ", cov([b for b in bets if B.is_parlay_header(b)]))
print("   singles        ", cov([b for b in bets if not B.is_parlay_header(b)]))
print("-- singles missing a close, by sport/market (and is the market in the sport's odds map?)")
c = Counter()
for b in bets:
    if B.is_parlay_header(b) or b.get("close_odds") is not None:
        continue
    sp = b.get("sport") or "—"
    try:
        mm = sports.get(sp).market_map
        inmap = b.get("market") in mm
    except Exception:
        inmap = None
    c[(sp, b.get("market"), inmap, (b.get("book") or "—"))] += 1
for (sp, m, inmap, bk), n in c.most_common(40):
    print(f"   {n:3d}  {sp:7s} {str(m):26s} in odds map: {inmap}  book {bk}")
