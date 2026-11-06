"""Nov 6 audit for the investor report.
1. Locked Desk calls hit 52% vs 60% stated. Split by source: calls that match a props-model kickoff snapshot (the
   newer model, with its corrected chance and Use tag) vs calls that don't (the older fallback rows).
2. Bets beat the close only 34%. Split CLV by sport, market, book, entry-vs-close side sanity, and how far before the
   game the bet was logged."""
import os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyst_ledger as AL, betlog as B, model_store as MS
from projections import normalize_name as nn


def summ(g, key="hit", p="model_prob"):
    n = len(g)
    if not n:
        return "n=0"
    h = sum(1 for r in g if r[key]) / n
    s = sum(r[p] for r in g if r.get(p) is not None) / max(1, sum(1 for r in g if r.get(p) is not None))
    return f"n={n:5d} hit {h:.1%} said {s:.1%} gap {h - s:+.1%}"


calls = [c for c in AL.fetch_calls() if c.get("hit") is not None and c.get("model_prob") is not None]
print("## 1. Locked calls by source")
for sp in sorted({c["sport"] for c in calls}):
    cs = [c for c in calls if c["sport"] == sp]
    snaps = MS.load_snapshots(sp, sorted({c["call_date"] for c in cs}))
    idx = {}
    for s in snaps:
        idx[(s.get("slate_date"), nn(s.get("player") or ""), s.get("market"), s.get("side"))] = s
    props, other = [], []
    for c in cs:
        s = idx.get((c["call_date"], nn(c.get("player") or ""), c.get("market"), c.get("side")))
        if s:
            props.append(dict(c, snap_chance=s.get("chance"), use=s.get("use_tag")))
        else:
            other.append(c)
    print(f"{sp}: all {summ(cs)}")
    print(f"    matches props model  {summ(props)}")
    sc = [c for c in props if c.get("snap_chance") is not None]
    if sc:
        print(f"      ...with the snapshot's (corrected) chance {summ(sc, p='snap_chance')}")
        for u in sorted({str(c.get('use')) for c in sc}):
            print(f"      use {u:20s} {summ([c for c in sc if str(c.get('use')) == u], p='snap_chance')}")
    print(f"    no props snapshot    {summ(other)}")
    by_m = defaultdict(list)
    for c in cs:
        by_m[c["call_date"] >= "2026-11-02"].append(c)
    print(f"    before Nov 2 {summ(by_m[False])} | Nov 2+ {summ(by_m[True])}")

print("\n## 2. Closing line")
bets = [b for b in B.money_bets(B.list_bets()) if not B.is_parlay_header(b)]
rows = []
for b in bets:
    c = B.clv_pct(b.get("entry_odds"), b.get("close_odds"))
    if c is None:
        continue
    rows.append(dict(b, clv=c))
def cl(g, lab):
    if not g:
        return
    beat = sum(1 for r in g if r["clv"] > 0) / len(g)
    same = sum(1 for r in g if r["clv"] == 0) / len(g)
    print(f"{lab:38s} n={len(g):4d} beat {beat:5.1%} same {same:5.1%} avg {sum(r['clv'] for r in g) / len(g):+6.2f}%")
cl(rows, "all")
for k in ("sport", "book", "market"):
    print(f"-- by {k}")
    g = defaultdict(list)
    for r in rows:
        g[r.get(k) or "—"].append(r)
    for name, rs in sorted(g.items(), key=lambda kv: -len(kv[1]))[:12]:
        cl(rs, f"  {name}")
print("-- sign sanity: entry and close on opposite sides of even (e.g. -150 vs +130)")
flip = [r for r in rows if (r["entry_odds"] > 0) != (r["close_odds"] > 0) and abs(r["entry_odds"]) > 115 and abs(r["close_odds"]) > 115]
cl(flip, "  opposite-sign pairs")
for r in sorted(rows, key=lambda r: r["clv"])[:8]:
    print("   worst:", r.get("slate_date"), r.get("sport"), r.get("player"), r.get("market"), r.get("side"), r.get("line"),
          r.get("entry_odds"), "->", r.get("close_odds"), f"{r['clv']:+.1f}%", (r.get("notes") or "")[:40])
print("-- by month")
g = defaultdict(list)
for r in rows:
    g[str(r.get("slate_date"))[:7]].append(r)
for m, rs in sorted(g.items()):
    cl(rs, f"  {m}")
print("-- logged after vs before slate date (ts_placed day vs slate_date)")
late = [r for r in rows if str(r.get("ts_placed") or "")[:10] > str(r.get("slate_date") or "")]
cl(late, "  logged after the slate date")
cl([r for r in rows if r not in late], "  logged on/before")
