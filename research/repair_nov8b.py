import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, script_data as D, props_engine as PE
# by exact price from the kickoff snapshot
for bids, (pl, sd, ln, gm, res) in (((612, 618, 624), ("Jeremy Reaves", "Over", 5.5, "LA @ WAS", "win")),
                                    ((613, 619, 625), ("Jacob Rodriguez", "Under", 4.5, "DET @ MIA", "loss"))):
    for bid in bids:
        B.update_bet(bid, player=pl, side=sd, line=ln, game=gm, result=res)
def box(path, date):
    sb = D._get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard", {"dates": date}) or {}
    out = {}
    for ev in sb.get("events") or []:
        s = D._get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary", {"event": ev["id"]}) or {}
        for t in (s.get("boxscore") or {}).get("players") or []:
            for g in t.get("statistics") or []:
                for a in g.get("athletes") or []:
                    nm = PE.norm_name((a.get("athlete") or {}).get("displayName"))
                    d = out.setdefault(nm, {"game": ev.get("shortName")})
                    for k, v in zip(g.get("keys") or [], a.get("stats") or []):
                        d[k] = v
                    d["dnp"] = d.get("dnp") or bool(a.get("didNotPlay"))
    return out
nfl = box("football/nfl", "20261108")
sw = nfl.get(PE.norm_name("D'Andre Swift"))
print("RB swift", sw and {k: sw.get(k) for k in ("rushingAttempts", "rushingYards", "game")})
if sw and sw.get("rushingAttempts") is not None:
    att = float(sw["rushingAttempts"]); r = "win" if att > 15.5 else "loss"
    for bid in (611, 617, 623):
        B.update_bet(bid, player="D'Andre Swift", side="Over", line=15.5, game=sw.get("game"), result=r)
    print("RB swift", att, r)
nba = box("basketball/nba", "20261108")
def num(x):
    try: return float(str(x).split("-")[0])
    except Exception: return 0.0
for bid in range(628, 633):
    b = next(x for x in B.list_bets() if x["id"] == bid)
    p = nba.get(PE.norm_name(b["player"]))
    if not p:
        print("RB NBA missing", b["player"]); continue
    if p.get("dnp"):
        B.update_bet(bid, result="void"); print("RB", b["player"], "DNP void"); continue
    v = {"Pts": num(p.get("points")), "Reb": num(p.get("rebounds")), "Ast": num(p.get("assists"))}
    tot = sum(v[k] for k in b["market"].split("+"))
    r = "push" if tot == b["line"] else ("win" if (tot > b["line"]) == (b["side"] == "Over") else "loss")
    B.update_bet(bid, result=r, game=p.get("game"))
    print("RB NBA", b["player"], b["market"], b["side"], b["line"], "actual", tot, v, r, p.get("game"))
for t in B.ticket_settlements(B.list_bets()):
    B.update_bet(t["id"], result=t["result"]); print("RB ticket", t)
tot = 0.0
for b in B.list_bets():
    if str(b.get("slate_date"))[:10] == "2026-11-08" and b.get("is_real_bet") and (not B._ticket(b) or B.is_parlay_header(b)):
        print("RB DAY", b["id"], b.get("sport"), B._ticket(b) or "single", b.get("player"), b.get("market"), b.get("side"), b.get("line"), b.get("entry_odds"), b.get("stake"), b.get("result"), B.bet_pnl(b), b.get("model_prob"))
        tot += B.bet_pnl(b) or 0
print("RB TOTAL", round(tot, 2))
