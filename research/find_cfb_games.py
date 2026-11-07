import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
import todays_best as TB
want = [("Alabama", "LSU"), ("Oregon", "Ohio State"), ("Temple", "Navy"), ("Charlotte", "UAB")]
recs = [r for r in MS.load_game_picks("NCAAF") if TB._et_date(r.get("kickoff")) == "2026-11-07"]
print("GAMES", len(recs))
for a, b in want:
    hit = [r for r in recs if any(a in str(r.get(k)) for k in ("home", "away")) and any(b in str(r.get(k)) for k in ("home", "away"))]
    for r in hit:
        print("GAME", a, b, "|", r.get("game_id"), "|", r.get("away"), "@", r.get("home"), "|", r.get("kickoff"), "| line_total", r.get("line_total"), "model_total", r.get("model_total"))
    if not hit:
        print("GAME", a, b, "| NOT FOUND")
