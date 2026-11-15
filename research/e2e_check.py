"""Nov 15 end-to-end state check (read-only)."""
import os, sys, json
from datetime import datetime, timedelta, timezone
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytz, requests
import model_store as MS, betlog as B, todays_best as TB, sports, long_shots_scan as LSS, lab_long_shots as LLS
ET = pytz.timezone("US/Eastern")
now = datetime.now(timezone.utc); today = now.astimezone(ET).strftime("%Y-%m-%d")
yday = (now.astimezone(ET) - timedelta(days=1)).strftime("%Y-%m-%d")
print("TODAY", today, "now ET", now.astimezone(ET).strftime("%H:%M"))
def age(iso):
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return f"{(now - t).total_seconds() / 3600:.1f}h ago"
    except Exception:
        return "?"
print("\n== SPORTS in season", [k for k in ("NBA", "NFL", "NHL", "NCAAF", "NCAAMB", "MLB", "WNBA") if sports.in_season(k)])
print("\n== MORNING REVIEW / CALIBRATION")
for sp in ("NBA", "NFL", "NHL", "NCAAF", "NCAAMB", "GAME_LINES"):
    ms = MS.daily_review_mornings(sp)[:2]; tr = MS.daily_review_mornings(f"{sp}-tuning")[:1]
    rep = MS.load_daily_review(sp, ms[0]) if ms else {}
    g = (rep or {}).get("graded") or (rep or {}).get("n") or ""
    auto = ((rep or {}).get("calibration") or {}).get("auto")
    print(f"REV {sp:10} mornings {ms} tuning {tr} | auto: {json.dumps(auto, default=str)[:260] if auto else '-'}")
for c in MS.list_calibration(): print("CAL", c.get("sport"), c.get("s"), str(c.get("approved_ts"))[:16], str(c.get("details"))[:100])
for b in MS.list_blend(): print("BLEND", b.get("sport"), b.get("market"), b.get("w"), str(b.get("approved_ts"))[:16])
for k in ("tennis_calibration",) + tuple(f"game_calibration:{l}" for l in ("NCAAMB", "EUROLEAGUE", "NBL")):
    print("SET", k, json.dumps(MS.get_setting(k, None), default=str)[:200])
print("\n== BRIEFS")
for kind in ("morning", "picks"):
    for d in (today, yday):
        v = MS.get_setting(f"brief:{kind}:{d}", None)
        print(f"BRIEF {kind} {d}:", (f"saved {age(v.get('at'))}, sent={v.get('sent')}, {len(v.get('text') or '')} chars" if v else "none"))
print("\n== BETS")
bets = B.list_bets()
open_ = [b for b in bets if not b.get("result")]
for b in open_:
    print("OPEN", b.get("id"), b.get("slate_date"), b.get("sport"), b.get("game"), b.get("player"), b.get("market"), b.get("side"), b.get("line"), b.get("entry_odds"), "parlay" if b.get("parlay_id") else "")
print("open total", len(open_), "| stuck (before today)", sum(1 for b in open_ if str(b.get("slate_date")) < today))
recent = [b for b in bets if str(b.get("slate_date")) in (yday,)]
print("yesterday's bets", len(recent), {r: sum(1 for b in recent if b.get("result") == r) for r in ("win", "loss", "push", "void")})
print("\n== TODAY'S BOARDS (props) / GAME PICKS")
for sp in ("NBA", "NFL", "NHL", "NCAAMB", "NCAAF"):
    v = TB.load_props(sp, today)
    print(f"PROPS {sp:7}", f"{len(v.get('rows') or [])} rows, saved {age(v.get('at'))}" if v else "none")
for lg in ("NBA", "NHL", "NCAAMB", "NFL", "TENNIS"):
    try:
        ps = [p for p in MS.load_game_picks(lg, ungraded=True) if TB._et_date(p.get("kickoff")) == today]
        print(f"PICKS {lg:7} {len(ps)} games today, latest capture {max((str(p.get('captured_at') or p.get('ts') or '') for p in ps), default='-')[:16]}")
    except Exception as exc:
        print("PICKS", lg, "error", exc)
try:
    w = TB.winner_rows(today); print("WINNER ROWS today", len(w), {s: sum(1 for r in w if r["sport"] == s) for s in {r["sport"] for r in w}})
    print("LOAD_ERRORS", TB.LOAD_ERRORS)
except Exception as exc:
    print("winner_rows error", exc)
try:
    import soccer_picks as SP, intl_picks as IP
    print("SOCCER slate leagues", len(SP.slate_leagues() or []), "| INTL slate", IP.slate_leagues())
    print("SOCCER rows today", len(TB.soccer_rows(today)), "flags", len(TB.soccer_flags(today)))
except Exception as exc:
    print("soccer/intl error", exc)
print("\n== LONG SHOTS")
for sp in LSS.SPORTS:
    v = LSS.load(sp, today)
    print(f"LS {sp:6}", f"{v.get('games')} games, {len(v.get('rows') or [])} value rungs, top {len(v.get('top') or [])}, scanned {age(v.get('at'))}" if v else "none")
v = LLS.load_scorers(today); print("LS SOCCER scorers", f"{len(v.get('rows') or [])} rows, scanned {age(v.get('at'))}" if v else "none")
try:
    c = LLS.collect(today); print("LAB LS", {k: (v["n"], len(v["top"])) for k, v in c.items()})
except Exception as exc:
    print("lab ls error", exc)
print("\n== ODDS API")
r = requests.get("https://api.the-odds-api.com/v4/sports", params={"apiKey": os.environ.get("ODDS_API_KEY", "")}, timeout=20)
print("ODDS status", r.status_code, "remaining", r.headers.get("x-requests-remaining"), "used", r.headers.get("x-requests-used"))
