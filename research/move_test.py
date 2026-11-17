"""Nov 17: when the market moves toward the model's side before the game (line_history), do those reads hit more?"""
import os, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as DR, line_history as LH

def dec(p):
    p = float(p); return 1 + (p / 100 if p > 0 else 100 / -p)
def imp(p):
    p = float(p); return 100 / (p + 100) if p > 0 else -p / (-p + 100)
morning = "2026-11-17"
for sport in ("NBA", "NHL", "NFL"):
    days = 63 if sport == "NFL" else 30
    cut = (date.fromisoformat(morning) - timedelta(days=days)).isoformat()
    ds = [d for d in MS.snapshot_dates(sport) if cut <= d < morning]
    idx = LH.sport_index(sport, since=cut)
    by_player = defaultdict(lambda: defaultdict(list))      # player -> lh market -> rows
    for (pl, mk), rows in idx.items():
        for r in rows: by_player[pl][mk].append(r)
    g = DR.grade_dates(sport, ds)
    # market name map by line matching
    votes = defaultdict(Counter)
    graded = []
    for d, rs in g.items():
        for r in rs:
            if r.get("result") not in ("hit", "miss") or r.get("line") is None: continue
            graded.append((d, r))
            for mk, rows in by_player.get(r["player"], {}).items():
                if any(str(x.get("commence_time") or x["captured_at"])[:10] in (d, (date.fromisoformat(d)+timedelta(days=1)).isoformat())
                       and x.get("line") is not None and float(x["line"]) == float(r["line"]) for x in rows):
                    votes[r["market"]][mk] += 1
    mmap = {m: c.most_common(1)[0][0] for m, c in votes.items() if c}
    print(f"\n{sport}: graded {len(graded)}, market map {mmap}")
    stats = {}
    for d, r in graded:
        mk = mmap.get(r["market"]); side = r.get("side")
        if not mk or side not in ("Over", "Under"): continue
        rows = [x for x in by_player.get(r["player"], {}).get(mk, [])
                if str(x.get("commence_time") or "")[:10] in (d, (date.fromisoformat(d)+timedelta(days=1)).isoformat())
                and str(x["captured_at"]) < str(x.get("commence_time") or "9")]
        if len(rows) < 2: continue
        # consensus over books: first vs last capture time, the read's side
        side_rows = sorted([x for x in rows if x["side"] in (side, side.lower())], key=lambda x: x["captured_at"])
        if len(side_rows) < 2: continue
        t0, t1 = side_rows[0]["captured_at"], side_rows[-1]["captured_at"]
        if str(t0)[:13] == str(t1)[:13]: continue
        f = [x for x in side_rows if x["captured_at"] == t0 and x.get("price") is not None]
        l = [x for x in side_rows if x["captured_at"] == t1 and x.get("price") is not None]
        if not f or not l: continue
        line_f = sum(float(x["line"]) for x in f) / len(f); line_l = sum(float(x["line"]) for x in l) / len(l)
        pf = sum(imp(x["price"]) for x in f) / len(f); pl = sum(imp(x["price"]) for x in l) / len(l)
        dl = line_l - line_f
        toward = (pl - pf) + 0.04 * (dl if side == "Over" else -dl)   # side got pricier or the line moved its way
        bucket = "toward" if toward >= 0.02 else ("away" if toward <= -0.02 else "flat")
        bet = bool(r.get("use_tag")) and "Pass" not in str(r.get("use_tag"))
        y = 1 if r["result"] == "hit" else 0
        price = r.get("over_price") if side == "Over" else r.get("under_price")
        u = (dec(price) - 1 if y else -1.0) if price is not None else 0.0
        for key in (("all", bucket),) + ((("bet", bucket),) if bet else ()):
            n, h, c, uu = stats.get(key, (0, 0, 0.0, 0.0))
            stats[key] = (n + 1, h + y, c + float(r.get("chance") or 0), uu + u)
    for key in sorted(stats):
        n, h, c, u = stats[key]
        print(f"  {key[0]:4} {key[1]:7} n {n:5} hit {h/n:.1%} model said {c/n:.1%} units {u:+.1f} ({u/n:+.1%})")
