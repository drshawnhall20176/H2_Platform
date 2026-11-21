import sys
sys.path.insert(0, ".")
import betlog as B
bets = B.list_bets()
cl = sorted([b for b in bets if b.get("close_odds") is not None and b.get("entry_odds") is not None], key=lambda b: b.get("ts_placed", ""))
print(f"PC clv bets {len(cl)}")
v = [(B.clv_pct(b["entry_odds"], b["close_odds"]) or 0, b) for b in cl]
for i, (c, b) in enumerate(v):
    if abs(c) > 25:
        print(f"PC OUTLIER #{i} id={b['id']} {b.get('sport')} {b.get('player') or b.get('side')} {b.get('market')} entry={b['entry_odds']} close={b['close_odds']} clv={c:.1f}")
def seg(a, z):
    xs = [c for c, _ in v[a:z]]
    return f"{sum(xs)/len(xs):+.2f}% n={len(xs)}" if xs else "-"
print("PC segments", seg(0, 85), seg(85, 125), seg(125, 239), "| no outliers recent:",
      f"{sum(c for c,_ in v[125:] if abs(c)<=25)/max(1,sum(1 for c,_ in v[125:] if abs(c)<=25)):+.2f}%")
by = {}
for c, b in v:
    k = (b.get("sport"), bool(b.get("is_real_bet") if b.get("is_real_bet") is not None else True))
    by.setdefault(k, []).append(c)
for k, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
    xs2 = [x for x in xs if abs(x) <= 25]
    print(f"PC clv {k[0]} real={k[1]}: n={len(xs)} avg={sum(xs2)/max(1,len(xs2)):+.2f}% beat={sum(x>0 for x in xs)}/{len(xs)}")
cal = B.calibration(bets, n_bins=5)
for c in cal:
    print("PC cal", {k: (round(v_, 3) if isinstance(v_, float) else v_) for k, v_ in c.items()})
s = [b for b in bets if B._result(b) in ("win", "loss")]
import inspect
print("PC calib src", inspect.getsource(B.calibration)[:600].replace("\n", " | "))
for lo, hi in ((0.6, 0.7), (0.7, 0.8), (0.8, 1.01)):
    g = [b for b in s if b.get("model_prob") is not None and lo <= float(b["model_prob"]) < hi]
    by = {}
    for b in g:
        by.setdefault(b.get("sport"), [0, 0])[B._result(b) == "win"] += 1
    print(f"PC band {lo}-{hi}: n={len(g)} wins={sum(B._result(b)=='win' for b in g)} by sport (L,W)={by}")
