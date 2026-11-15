"""Nov 15: across every sport, which saved board reads carried a bet tag (not Pass), and are they still to play."""
import os, sys
from collections import Counter
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
day = "2026-11-15"
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB", "NCAAWB", "WNBA", "MLB"):
    try:
        snaps = MS.load_snapshots(sp, [day])
    except Exception as e:
        print(sp, "error", e); continue
    latest = {}
    for s in snaps:
        if s.get("line") is None or s.get("projection") is None: continue
        k = (s.get("player"), s.get("market"))
        if k not in latest or str(s.get("ts")) > str(latest[k].get("ts")): latest[k] = s
    tags = Counter((s.get("use_tag") or "none") for s in latest.values())
    print(f"\n== {sp}: {len(latest)} reads | {dict(tags)}")
    bets = [s for s in latest.values() if s.get("use_tag") and "Pass" not in s["use_tag"]]
    for s in sorted(bets, key=lambda s: -(s.get("chance") or 0))[:25]:
        side = s.get("side"); price = s.get("over_price") if side == "Over" else s.get("under_price")
        print(f"  {str(s.get('kickoff'))[:16]} {s.get('game')!s:28} {s['player']:22} {s['market']:16} {side} {s['line']} "
              f"proj {s['projection']:.1f} ch {s.get('chance') or 0:.0%} px {price} | {s['use_tag']}")
