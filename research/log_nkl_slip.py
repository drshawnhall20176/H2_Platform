"""Nov 19: log the owner's six $3 NKL singles from his DraftKings slip (owner asked in chat). Idempotent."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS, intl_hoops as I, intl_picks as IP
DAY = "2026-11-19"
SLIP = [  # (away, home, market, side, line, odds)
    ("Rytas II", "LSU Atletas", "Total", "over", 169.5, -115),
    ("Zalgiris Kaunas II", "Mazeikiai", "Total", "over", 178.5, -115),
    ("Omega-Tauras BC", "Silute", "Total", "over", 173.5, -115),
    ("BC Vilkaviskio Perlas", "Neptunas-Akvaservis", "Total", "over", 156.5, -110),
    ("Kretingos Kretinga", "Telsiai", "Total", "over", 168.5, -115),
    ("Plunges Olimpas", "Suduva-Mantinga", "Spread", "home", -15.5, -110),
]
existing = B.list_bets()
picks = [p for p in MS.load_game_picks("NKL") if str(p.get("kickoff"))[:10] in ("2026-11-19", "2026-11-20", "2026-11-18")]
print("LN nkl picks", len(picks), [f"{p['away']} @ {p['home']} {str(p.get('kickoff'))[:16]}" for p in picks][:20])
for away, home, mk, side, line, odds in SLIP:
    p = next((p for p in picks if I.find_team([p["home"]], home, True) and I.find_team([p["away"]], away, True)), None)
    if p:
        f = IP.bet_fields(dict(p, sport="NKL"), mk, side, line, odds, 3.0, True)
        try:
            ch = IP.fair_chance(dict(p, sport="NKL"), mk, side, line)
        except Exception:
            ch = None
        f["model_prob"] = None if ch is None else round(ch, 4)
    else:
        team = home if side == "home" else None
        f = {"slate_date": DAY, "sport": "INTL", "game": f"{away} @ {home}", "player": team or "Game total",
             "market": mk, "side": team or side.title(), "line": line, "entry_odds": float(odds),
             "entry_odds_source": "manual", "model_prob": None, "stake": 3.0, "is_real_bet": True,
             "category": B.default_category("INTL", from_model=False), "notes": None}
    f["slate_date"] = DAY
    f["book"] = "draftkings"
    f["notes"] = ",".join(x for x in ("DK slip 11/19", f.get("notes")) if x)
    dup = any(str(b.get("slate_date"))[:10] == DAY and b.get("market") == f["market"] and b.get("side") == f["side"]
              and b.get("line") == f["line"] and b.get("game") == f["game"] for b in existing)
    if dup:
        print("LN already logged", f["game"], f["side"], f["line"]); continue
    bid = B.add_bet(**f)
    print("LN logged", bid, f["game"], f["market"], f["side"], f["line"], odds, "model", f.get("model_prob"),
          "linked" if p else "NOT LINKED (settles from the results archive)")
