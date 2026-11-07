"""Nov 7: why most Analyst Desk angles come up empty on NBA -- each angle's inputs and hits on today's real board."""
import os
import sys
from collections import Counter
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyst as A                      # noqa: E402
import analyst_publisher as AP           # noqa: E402
import odds_api as O                     # noqa: E402
import sports                            # noqa: E402

D = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
for sport in (os.environ.get("SPORTS") or "NBA").split(","):
    deps = AP.default_deps()
    book = O.DEFAULT_BOOK
    plays, meta, _ = deps["load_board"](sport, D, book)
    if sport in sports.WEEKLY_SLATE_SPORTS:
        meta = sports.scope_filter(meta, lambda m: m.get("game_date"), D, sports.SCOPE_DATE)
        labels = {m.get("label") for m in meta}
        plays = [p for p in plays if p.get("Game") in labels]
    pp = [p for p in plays if p.get("Model") == "player-props"] or plays
    print(f"===== {sport} {D}: plays {len(plays)}, player-props {len(pp)}, games {len(meta)}, book {book}")
    if not pp:
        continue
    print("markets", Counter(p.get("Market") for p in pp).most_common())
    print("sample play keys", sorted(pp[0].keys()))
    key = deps["api_key"]()
    offers = deps["fetch_offers"](sport, D, key) if key else None
    omap = sports.get(sport).market_map
    print("offers", len(offers or []), "market_map", omap)
    print("offer markets", Counter(o.get("market") for o in offers or []).most_common(12))
    idx = A.index_offers(offers)
    in_map = sum(1 for p in pp if omap.get(p.get("Market")))
    found = sum(1 for p in pp if idx.get((A._norm(p.get("Player")), omap.get(p.get("Market")))))
    print(f"plays whose market is in market_map: {in_map}/{len(pp)}; with offers found: {found}")
    try:
        game_env, n1 = deps["game_env"](sport, D, meta, key)
    except Exception as e:
        game_env, n1 = {}, f"ERR {e}"
    try:
        matchups, n2 = deps["matchups"](sport, D)
    except Exception as e:
        matchups, n2 = {}, f"ERR {e}"
    print("game_env", len(game_env), "note", n1, "| sample keys", list(game_env)[:3], "| play games", sorted({p.get('Game') for p in pp})[:3])
    if game_env:
        e0 = next(iter(game_env.values()))
        print("  env entry", {k: e0.get(k) for k in ("home_name", "away_name", "home_spread", "away_spread", "total", "total_pct")})
        print("  play teams", sorted({p.get('Team') for p in pp})[:6])
        print("  team_side matched", sum(1 for p in pp if game_env.get(p.get('Game')) and A.team_side(p, game_env[p['Game']])), "/", len(pp))
    print("matchups", len(matchups), "note", n2, "| sample", list(matchups.items())[:2])
    print("  matchup keys hit", sum(1 for p in pp if (A._norm(p.get('Player')), p.get('Market')) in matchups))
    vals = [len(A._values(p, sport)) for p in pp]
    print("game-log values per play: zero", sum(v == 0 for v in vals), "| >=5", sum(v >= 5 for v in vals), "| _stat_key sample",
          Counter(p.get("_stat_key") for p in pp).most_common(6))
    if pp[0].get("_game_log"):
        print("  log entry sample", pp[0]["_game_log"][0])
    print("ConvictionSource", Counter(p.get("ConvictionSource") for p in pp), "| TeamTrend", Counter(str(p.get("TeamTrend")) for p in pp).most_common(5))
    print("TeamTrendRatio by team", sorted({(p.get("Team"), p.get("TeamTrendRatio")) for p in pp}, key=str)[:40])
    import line_history as LH
    from datetime import timedelta
    since = (datetime.now(pytz.timezone("US/Eastern")) - timedelta(days=14)).strftime("%Y-%m-%d")
    lidx = LH.sport_index(sport, since)
    print("line index keys", len(lidx), "sample", list(lidx)[:3])
    page_fn = A.history_lookup(lidx, omap)
    print("page lookup rows (top 30 plays)", sum(len(page_fn(sport, p["Player"], p["Market"], p["Side"])) for p in sorted(pp, key=lambda q: -(q.get("Conviction") or 0))[:30]))
    moves = [A.line_move_toward(p, {"history_fn": page_fn, "book": book}) for p in pp]
    moves = [m for m in moves if m is not None]
    print("plays with a measurable move at", book, len(moves), "| >=3pts toward", sum(m >= 0.03 for m in moves), "| max", max(moves) if moves else None)
    hist_rows = 0
    for p in sorted(pp, key=lambda q: -(q.get("Conviction") or 0))[:15]:
        try:
            hist_rows += len(deps["history_fn"](sport, p.get("Player"), p.get("Market"), p.get("Side")) or [])
        except Exception as e:
            print("history err", e)
            break
    print("line-history rows for top 15 plays", hist_rows)
    calls = A.scan(pp, sport, D, offers=offers, odds_map=omap, history_fn=deps["history_fn"], expect_book_lines=bool(offers),
                   book=book, game_env=game_env, matchups=matchups)
    cnt = Counter(a for c in calls for a in A.angle_names(c))
    print("CALLS", len(calls), "angle hits:", {k: cnt.get(k, 0) for k in A.ANGLES})
