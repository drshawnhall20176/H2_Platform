"""Nov 17: when the market moves toward the model's side during the day, do those reads hit more? (graded, 30 days)"""
import os, sys
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as DR

def dec(p):
    p = float(p); return 1 + (p / 100 if p > 0 else 100 / -p)
morning = "2026-11-17"
for sport in ("NBA", "NHL", "NFL", "NCAAF"):
    days = 63 if sport in ("NFL", "NCAAF") else 30
    cut = (date.fromisoformat(morning) - timedelta(days=days)).isoformat()
    ds = [d for d in MS.snapshot_dates(sport) if cut <= d < morning]
    g = DR.grade_dates(sport, ds)
    stats = {}
    for d in ds:
        snaps = [s for s in MS.load_snapshots(sport, [d]) if s.get("p_market") is not None and s.get("line") is not None]
        first, last = {}, {}
        for s in snaps:
            k = (s["player"], s["market"])
            if k not in first or str(s.get("ts")) < str(first[k].get("ts")): first[k] = s
            if k not in last or str(s.get("ts")) > str(last[k].get("ts")): last[k] = s
        res = {(r["player"], r["market"]): r for r in g.get(d, []) if r.get("result") in ("hit", "miss")}
        for k, f in first.items():
            l = last[k]; r = res.get(k)
            if r is None or f is l or str(f.get("ts"))[:13] == str(l.get("ts"))[:13]: continue
            side = f.get("side")
            if side not in ("Over", "Under"): continue
            try:
                pm_f = float(f["p_market"]); pm_l = float(l["p_market"]); ch = float(f["chance"])
            except (TypeError, ValueError): continue
            m_f = pm_f if side == "Over" else 1 - pm_f
            m_l = pm_l if side == "Over" else 1 - pm_l
            # a line move toward the side counts too: Over and the line went up = market agrees
            lm = float(l["line"]) - float(f["line"])
            toward = (m_l - m_f) + (0.04 * (lm if side == "Over" else -lm))
            edge = ch - m_f
            # did the ORIGINAL side hit, judged at the original line?
            act = r.get("actual")
            if act is None: continue
            y = (float(act) > float(f["line"])) if side == "Over" else (float(act) < float(f["line"]))
            if float(act) == float(f["line"]): continue
            bucket = "toward" if toward >= 0.02 else ("away" if toward <= -0.02 else "flat")
            tagged = edge >= 0.03
            for key in (("all", bucket), ("edge3", bucket)) if tagged else (("all", bucket),):
                n, h, ch_s, u = stats.get(key, (0, 0, 0.0, 0.0))
                price = f.get("over_price") if side == "Over" else f.get("under_price")
                pu = (dec(price) - 1 if y else -1.0) if price is not None else 0.0
                stats[key] = (n + 1, h + y, ch_s + ch, u + pu)
    print(f"\n{sport}")
    for key in sorted(stats):
        n, h, c, u = stats[key]
        print(f"  {key[0]:6} {key[1]:7} n {n:5} hit {h/n:.1%} model said {c/n:.1%} units@open {u:+.1f} ({u/n:+.1%})")
