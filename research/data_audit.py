"""Nov 18 -- (1) CLV by bet tag from the saved reads; (2) vig-removal methods vs outcomes; (3) is any data dropped?"""
import math, os, sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, props_engine as PE, postgame as PG
TODAY = date.today().isoformat()
SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
def imp(a):
    a = float(a); return 100 / (a + 100) if a > 0 else -a / (-a + 100)
def ts(x):
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except Exception:
        return None
GR = {}
for sp in SPORTS:
    ds = [d for d in MS.snapshot_dates(sp) if d < TODAY]
    GR[sp] = D.grade_dates(sp, ds)

print("== 1. snapshots per prop and CLV by tag")
for sp in SPORTS:
    rows = [r for rs in GR[sp].values() for r in rs]
    by = defaultdict(list)
    for r in rows:
        by[(r["slate_date"], r.get("game"), r.get("player"), r.get("market"))].append(r)
    nsnap = Counter(min(len(v), 10) for v in by.values())
    print(f"S {sp} props {len(by)} snapshots per prop: {dict(sorted(nsnap.items()))}")
    stats = defaultdict(lambda: Counter())
    res = defaultdict(lambda: Counter())
    for k, v in by.items():
        v = sorted(v, key=lambda r: str(r.get("ts")))
        ko = ts(v[0].get("kickoff"))
        pre = [r for r in v if ko is None or (ts(r.get("ts")) and ts(r["ts"]) < ko)]
        if len(pre) < 2: continue
        close = pre[-1]
        # entry: first read carrying each tag; CLV judged for the side that read took, at its line
        seen = set()
        for r in pre[:-1]:
            tag = PE.norm_use(r.get("use_tag")) or "?"
            if tag in seen: continue
            seen.add(tag)
            side = r.get("side"); l0, l1 = float(r["line"]), float(close["line"])
            if l1 != l0:
                good = (l1 > l0) if side == "Over" else (l1 < l0)
                c = "beat" if good else "lost"
            else:
                p0 = r.get("over_price") if side == "Over" else r.get("under_price")
                p1 = close.get("over_price") if side == "Over" else close.get("under_price")
                q0 = r.get("under_price") if side == "Over" else r.get("over_price")
                q1 = close.get("under_price") if side == "Over" else close.get("over_price")
                if None in (p0, p1, q0, q1): c = "no price"
                else:
                    n0 = imp(p0) / (imp(p0) + imp(q0)); n1 = imp(p1) / (imp(p1) + imp(q1))
                    c = "beat" if n1 > n0 + 0.01 else "lost" if n1 < n0 - 0.01 else "same"
            stats[tag][c] += 1
            # outcome of the ENTRY read (its own line), split by CLV
            fin = next((x for x in v if x.get("result") in ("hit", "miss")), None)
            if fin is not None:
                thr = PE.threshold(l0); act = fin.get("actual")
                if act is not None and act != thr:
                    hit = (act > thr) == (side == "Over")
                    res[(tag, c)]["hit" if hit else "miss"] += 1
    for tag, c in sorted(stats.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(c.values())
        bits = []
        for cc in ("beat", "same", "lost"):
            h = res[(tag, cc)]
            hr = f"{h['hit']/(h['hit']+h['miss']):.0%} of {h['hit']+h['miss']}" if h['hit'] + h['miss'] else "—"
            bits.append(f"{cc} {c[cc]/n:.0%} (hit {hr})")
        print(f"CLV {sp} {tag:20} entries {n:5d} | " + " | ".join(bits) + f" | no price {c['no price']}")

print("\n== 2. removing the vig: which method's chance matches outcomes (graded reads, both prices)")
def m_mult(o, u): a, b = imp(o), imp(u); return a / (a + b)
def m_add(o, u): a, b = imp(o), imp(u); v = (a + b - 1) / 2; return min(max(a - v, 0.005), 0.995)
def m_power(o, u):
    a, b = imp(o), imp(u); lo, hi = 1.0, 3.0
    for _ in range(50):
        k = (lo + hi) / 2
        if a ** k + b ** k > 1: lo = k
        else: hi = k
    return a ** ((lo + hi) / 2)
def m_shin(o, u):
    a, b = imp(o), imp(u); s = a + b; lo, hi = 0.0, 0.4
    def ps(z): return [(math.sqrt(z * z + 4 * (1 - z) * x * x / s) - z) / (2 * (1 - z)) for x in (a, b)]
    for _ in range(60):
        z = (lo + hi) / 2; p = ps(z)
        if sum(p) > 1: lo = z
        else: hi = z
    return ps((lo + hi) / 2)[0]
M = {"multiplicative (now)": m_mult, "additive": m_add, "power": m_power, "Shin": m_shin}
allrows = []
for sp in SPORTS:
    seen = {}
    for rs in GR[sp].values():
        for r in rs:
            if r.get("result") in ("hit", "miss") and r.get("over_price") and r.get("under_price") and r.get("actual") is not None:
                seen[(r["slate_date"], r.get("game"), r.get("player"), r.get("market"), r.get("line"))] = r
    for r in seen.values():
        y = r["actual"] > PE.threshold(float(r["line"]))
        allrows.append((sp, float(r["over_price"]), float(r["under_price"]), y, r.get("market")))
def band(o, u):
    lo = max(o, u)                          # the longer price of the two
    return "even (both -150..+150)" if abs(o) <= 150 and abs(u) <= 150 and not (o > 150 or u > 150) else \
        ("+150..+299 side" if lo < 300 else "+300 or longer side")
for scope in ("ALL",) + SPORTS:
    rs = [r for r in allrows if scope == "ALL" or r[0] == scope]
    if len(rs) < 200: continue
    for b in ("ALL", "even (both -150..+150)", "+150..+299 side", "+300 or longer side"):
        sub = [r for r in rs if b == "ALL" or band(r[1], r[2]) == b]
        if len(sub) < 100: continue
        out = []
        for name, f in M.items():
            ll = 0.0; sp_long = 0.0; hit_long = 0
            for _, o, u, y, _m in sub:
                p = min(max(f(o, u), 0.005), 0.995)
                ll -= math.log(p) if y else math.log(1 - p)
                # chance of the longer-priced side vs how often it happened
                if o >= u: sp_long += p; hit_long += y
                else: sp_long += 1 - p; hit_long += (not y)
            out.append(f"{name}: logloss {ll/len(sub):.4f}, longer side said {sp_long/len(sub):.1%}")
        hl = sum(((y) if o >= u else (not y)) for _, o, u, y, _ in sub) / len(sub)
        print(f"DV {scope:6} {b:24} n{len(sub):5d} longer side happened {hl:.1%} || " + " | ".join(out))

print("\n== 3. is any data being dropped? (every saved prop, last snapshot each)")
for sp in SPORTS:
    last = {}
    for rs in GR[sp].values():
        for r in rs:
            k = (r["slate_date"], r.get("game"), r.get("player"), r.get("market"))
            if k not in last or str(r.get("ts")) > str(last[k].get("ts")): last[k] = r
    c = Counter(r["result"] for r in last.values())
    n = len(last)
    print(f"G {sp} props {n}: " + ", ".join(f"{k} {v} ({v/n:.1%})" for k, v in c.most_common()))
    # voids: player missing vs stat missing; pending: by date
    vm = Counter(); pend = Counter()
    for r in last.values():
        if r["result"] == "void": vm[r.get("market")] += 1
        if r["result"] == "pending": pend[r["slate_date"]] += 1
    if vm: print(f"G {sp} voids by market: {dict(vm.most_common(12))}")
    if pend: print(f"G {sp} pending (ungraded) by slate: {dict(sorted(pend.items()))}")
    # markets saved but never gradable (stat_value None for every read)
    mk = defaultdict(Counter)
    for r in last.values(): mk[r.get("market")][r["result"]] += 1
    dead = [m for m, cc in mk.items() if cc["void"] == sum(cc.values()) and sum(cc.values()) >= 5]
    if dead: print(f"G {sp} MARKETS NEVER GRADED (all void): {dead}")
