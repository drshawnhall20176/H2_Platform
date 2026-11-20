"""Nov 20: is 💰 showing today? Saved boards per sport + snapshot reads that meet the rule."""
import sys
sys.path.insert(0, ".")
import model_store as MS, props_engine as PE, todays_best as TB
day = PE._et_today()
print("LIVE day", day, "money_sports:", PE.money_sports(day=day))
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    s = TB.load_props(sp, day) or {}
    rows = s.get("rows") or []
    print(f"LIVE {sp} board saved_at={s.get('at')} rows={len(rows)} money={sum(1 for r in rows if r.get('money'))} locks={sum(1 for r in rows if r.get('lock'))}")
    snaps = MS.load_snapshots(sp, [day])
    ok = [x for x in snaps if PE.snapshot_is_money(sp, x)]
    near = [x for x in snaps if x.get("ev") is not None and x["ev"] >= 0.03]
    print(f"LIVE {sp} snapshots={len(snaps)} edge3+={len(near)} money_rule={len(ok)}")
    for x in near[:6]:
        pm = x.get("p_market"); side = x.get("side")
        pms = None if pm is None else (pm if side == "Over" else 1 - pm)
        print(f"LIVE   {x.get('player')} {x.get('market')} {side} {x.get('line')} ev={x.get('ev'):.3f} ch={x.get('chance')} price={x.get('price')} book={x.get('book')} mev={PE.market_edge(pms, x.get('price'))}")
