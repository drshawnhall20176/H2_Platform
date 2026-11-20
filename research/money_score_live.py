"""Nov 20: fit the Money Score now (saves today's fit) and list today's game-line scores."""
import sys
sys.path.insert(0, ".")
import money_score as MSC, props_engine as PE, todays_best as TB
MSC.refit()
day = PE._et_today()
rows = TB.winner_rows(day)
sc = sorted([r for r in rows if r.get("money_score") is not None], key=lambda r: -r["money_score"])
print(f"MSL {day}: {len(rows)} games, {len(sc)} scored, {sum(1 for r in rows if r.get('money'))} 💰")
for r in sc[:25]:
    print(f"MSL {r['sport']:7} {r.get('time'):>8} {r['game'][:44]:44} {r['money_pick']:28} {r.get('money_price')} "
          f"score={r['money_score']:+.1%} ch={r['money_chance']:.0%} {'💰' if r.get('money') else ''}")
