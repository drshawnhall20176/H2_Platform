import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
for p in MS.load_game_picks("NCAAMB"):
    if any(t in (p.get("home") or "") for t in ("South Alabama", "Stephen F. Austin", "Northwestern Wildcats", "Utah Valley")) and str(p.get("kickoff",""))[:10] >= "2026-11-22":
        print({k: p.get(k) for k in ("kickoff","away","home","neutral","model_margin","home_spread","edge","model_p","model_p_raw","fair_home","best_home","best_away","ml_edge")})
