import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_review as D
for sp in ("NFL", "NBA", "NHL", "NCAAF"):
    rep = D.review_sport(sp, "2026-11-10", write=False)
    for d in (rep.get("calibration") or {}).get("auto") or []:
        print("AD", sp, d["side"], "active", d["active"], "->", d["new"], "| n", d["n"], "dates", d["dates"], "splits", d["passed"], "/", d["splits"], "|", d["why"])
    for d in rep.get("auto_tuning") or []:
        print("AD", sp, "tuning", d["market"], d.get("slot") or "", "->", d.get("factor"), "| n since", d["n_since"], "|", d["why"])
