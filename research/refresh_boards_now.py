"""Nov 20: rebuild today's props boards now (owner: 💰 not showing yet) and report the 💰 / 🔒 counts."""
import sys
sys.path.insert(0, ".")
import best_bets_data as BBD, props_engine as PE, todays_best as TB, sports as S
day = PE._et_today()
for k in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    if not S.in_season(k):
        print("REF", k, "not in season"); continue
    try:
        BBD.load_generic_best_bets_board(k, day, BBD.O.DEFAULT_BOOK)
    except Exception as e:
        print("REF", k, "failed", type(e).__name__, e); continue
    rows = (TB.load_props(k, day) or {}).get("rows") or []
    m = [r for r in rows if r.get("money")]
    print(f"REF {k}: rows={len(rows)} money={len(m)} locks={sum(1 for r in rows if r.get('lock'))}")
    for r in m:
        print(f"REF   💰 {r.get('time')} {r.get('pick')} {r.get('price')} {r.get('book')} ch={r.get('chance')} edge={r.get('edge')}")
