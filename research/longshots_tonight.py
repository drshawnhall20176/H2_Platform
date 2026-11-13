"""Nov 13: every NBA game tonight through the Long Shots finder at DraftKings; rungs priced +1100 or longer."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD
import book_menu as BM
import long_shots as LS
import odds_api as O
import position_lines as PL
import props_engine as PE
import sports

DAY, BOOK, MIN_PRICE = "2026-11-13", "draftkings", 1100
api = os.environ["ODDS_API_KEY"]
sp = sports.get("NBA")
rows, meta = sp.engine.build_slate(DAY)
offers = BBD.fetch_generic_offers("NBA", DAY, api)
reads = BBD.slate_reads_for("NBA", DAY, meta, offers, BOOK) or {}
print("games", len(meta), "reads", len(reads))
evs = O.fetch_events_all(api, sport=sp.odds_sport_key)
alts = list(LS.SPORTS["NBA"]["alt"])
for g in meta:
    ev = PL.match_event(evs, g["home_name"], g["away_name"])
    if not ev:
        print(f"\n### {g['label']}: not posted"); continue
    res = BM.fetch_menu(api, sp.odds_sport_key, [ev["id"]], alts, BOOK, feed_by_event={ev["id"]: ev.get("_feed") or sp.odds_sport_key})
    q = res.get("quotes") or []
    out = LS.finder({k: v for k, v in reads.items() if v.get("game") == g["label"]}, q, PE.norm_name, PE.prob_over, sport="NBA")
    long_ = [r for r in out if (r.get("Price") or 0) >= MIN_PRICE]
    long_.sort(key=lambda r: -r["EV per $1"])
    print(f"\n### {g['label']}  tip {ev.get('commence_time')}  rungs checked {len(out)}, at +{MIN_PRICE}+: {len(long_)}, credits left {res.get('remaining')}")
    for r in long_[:8]:
        print("  " + " | ".join(f"{k}={r.get(k)}" for k in ("Player", "Bet", "Price", "Book says", "Honest chance",
              "Model raw", "EV per $1", "Projection", "Main line", "Flags")))
