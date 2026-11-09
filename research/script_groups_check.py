import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, script_effects as SE
for sp in ("NFL", "NCAAF"):
    got = MS.get_setting(f"script_learn:{sp}")
    d = json.loads(got) if isinstance(got, str) else (got or {})
    print("SG", sp, "games", d.get("games"), "keys", list(d.keys())[:12])
    for g in ("pass_td", "pass_int", "anytime_td", "sacks", "fg_made", "kick_pts", "pat_made", "rush_yds", "pass_yds"):
        print("SG", sp, g, "trust", (d.get("trust") or {}).get(g), "n", (d.get("n") or {}).get(g), "effects", {k: round(v, 3) for k, v in ((d.get("effects") or {}).get(g) or {}).items() if isinstance(v, (int, float))})
    SE.refresh(sp) if hasattr(SE, "refresh") else None
