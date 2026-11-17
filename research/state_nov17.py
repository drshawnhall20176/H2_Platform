"""Nov 17: owner's betting record + the model's 30-day Use-tag records per sport."""
import os, sys, json
from collections import defaultdict
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS, pick_records as PR

allb = [b for b in B.list_bets() if b.get("is_real_bet") is not False]
mb = B.money_bets(allb)
def line(name, bets):
    s = B.summary(bets)
    print(f"{name:34} n {s['settled']:4} W-L {s['wins']}-{s['losses']} staked ${s['staked']:.2f} P/L ${s['profit']:+.2f} ROI {s['roi']}% | CLV n {s['clv_n']} avg {s['avg_clv']} beat {s['beat_close_rate']}%")
print("first bet", min(str(b.get('slate_date')) for b in mb), "open", sum(1 for b in mb if B._result(b) not in ('win','loss','push','void')))
line("ALL", mb)
for since in ("2026-11-01", "2026-11-08", "2026-11-10"):
    line(f"since {since}", [b for b in mb if str(b.get('slate_date')) >= since])
singles = [b for b in mb if not B.is_parlay_header(b)]
parl = [b for b in mb if B.is_parlay_header(b)]
line("singles", singles); line("parlays", parl)
line("singles since 11-08", [b for b in singles if str(b.get('slate_date')) >= "2026-11-08"])
line("parlays since 11-08", [b for b in parl if str(b.get('slate_date')) >= "2026-11-08"])
by = defaultdict(list)
for b in singles: by[str(b.get("sport"))].append(b)
for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])): line(f"  single {k}", v)
cat = defaultdict(list)
for b in mb: cat[str(b.get("category"))].append(b)
for k, v in cat.items(): line(f"  cat {k}", v)
ls = [b for b in mb if "long" in str(b.get("notes") or "").lower()]
line("long shots", ls)
print("\nMARKETS (singles, settled>=4)")
for r in B.market_breakdown(singles)[:25]: print("  ", json.dumps(r, default=str)[:220])
print("\nCALIB", json.dumps(B.calibration([b for b in singles if b.get('model_prob')]), default=str)[:1200])
# daily last 10 days
print("\nDAYS")
d = defaultdict(list)
for b in mb: d[str(b.get("slate_date"))].append(b)
for k in sorted(d)[-12:]:
    s = B.summary(d[k]); print(f"  {k} W-L {s['wins']}-{s['losses']} P/L ${s['profit']:+.2f} staked ${s['staked']:.2f}")
print("\nRECENT", [(b.get("id"), b.get("player") or b.get("game"), B._result(b), round(B.bet_pnl(b) or 0,2)) for b in mb if (b.get("id") or 0) >= 742])
print("\nMODEL 30-day use-tag records")
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    print(" ", sp, PR.tag_records(sp))
