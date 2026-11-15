import os, sys, json
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, intl_picks as IP, model_store as MS, daily_review as D
for b in B.list_bets():
    if b.get("sport") == "INTL" and "gl:NCAAF:" in str(b.get("notes") or ""):
        B.update_bet(int(b["id"]), sport="NCAAF"); print("relabeled", b["id"], b.get("game"))
print("settled", IP.settle_logged("NCAAF"))
try:
    print("parlays rolled", D.settle_game_lines())
except Exception as exc:
    print("settle_game_lines", exc)
for b in B.list_bets():
    if b.get("id") in (719, 720, 721, 722, 723):
        print("BET", b["id"], b.get("sport"), b.get("game"), b.get("side"), b.get("line"), b.get("result"))
for kind in ("morning", "picks"):
    for d in ("2026-11-15", "2026-11-14"):
        v = MS.get_setting(f"brief:{d}:{kind}", None)
        print(f"BRIEF {kind} {d}:", (f"saved {v.get('at')}, sent={v.get('sent')}, {len(v.get('text') or '')} chars" if v else "none"))
v = MS.get_setting("brief:2026-11-15:morning", None)
if v: print(v.get("text")[:3000])
