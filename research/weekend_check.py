"""Nov 19: weekend readiness -- Odds API credits left, and the 💰 record with untested markets left out."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odds_api as O, best_bets_data as BBD, model_store as MS, postgame as PG
api = BBD.get_odds_api_key()
_, hdr = O._get("sports", {"apiKey": api})
print("WC credits", {k: v for k, v in (hdr or {}).items() if "requests" in k.lower()})
dates = MS.snapshot_dates("NBA"); snaps = MS.load_snapshots("NBA", dates); g = []
for d in sorted({s["slate_date"] for s in snaps}):
    day = [s for s in snaps if s["slate_date"] == d]
    try:
        g += PG.grade(day, PG.fetch_results("NBA", d, sorted({(s["team"], s["opp"]) for s in day})))
    except Exception:
        pass
print("WC money", PG.money_record(g))
print("WC lock", PG.lock_record(g))
