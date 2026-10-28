"""
test_slate_sync.py — the Oct 28 sync check, as tests: every page reads a player through ONE model.

The finding: Best Bets / Edge Board / Graded Picks / Parlays / Slip Lab ran an older recent-games resample (Davion
Mitchell's points 15.6) while Hot Hand, Matchup Lab and Position Matchups shared the Player props model (18.2), and
Best Bets ranked plays against placeholder lines. These tests pin the fix: the slate pages' numbers ARE Position
Matchups' numbers.
"""

import numpy as np
import pytest

import form_policy as FPol
import nba_projections as NP
import odds_api as O
import player_props as PPR
import props_engine as PE
import projections
import slate_props as SP

HOME, AWAY = 1, 2


def _line(game, order, team, opp, pid, name, pos, pts, reb=4, ast=3, fg3m=1, mins=32):
    return dict(game=game, order=order, team=team, opp=opp, pid=pid, name=name, pos=pos,
                stats=dict(min=mins, pts=pts, reb=reb, ast=ast, fg3m=fg3m))


def _sample():
    """Ten teams, five games each against each other; team 1 = Miami (Mitchell, pid 7), team 2 = Atlanta."""
    cur = []
    for t in range(1, 11):
        for i in range(5):
            opp = (t % 10) + 1
            g = f"g{t}-{i}"
            d = f"2026-10-2{i}"
            cur.append(_line(g, d, t, opp, 100 + t, f"Guard{t}", "PG", 18 + (t % 3) + i % 2))
            cur.append(_line(g, d, t, opp, 200 + t, f"Wing{t}", "SF", 14 + (t % 2), reb=6))
            cur.append(_line(g, d, t, opp, 300 + t, f"Big{t}", "C", 12, reb=10, ast=2, fg3m=0))
            # the defending side of the same game, so every defense has games allowed
            cur.append(_line(g, d, opp, t, 400 + opp, f"Opp{opp}", "PG", 16, mins=30))
    for i, p in enumerate((21, 22, 18, 11)):
        cur.append(_line(f"m{i}", f"2026-10-2{i + 1}", HOME, 9, 7, "Davion Mitchell", "PG", p, reb=1, ast=6, fg3m=2,
                         mins=34))
    prior = [_line(f"p{i}", f"2026-04-0{i + 1}", HOME, 5, 7, "Davion Mitchell", "PG", p, reb=2, ast=5, fg3m=1, mins=30)
             for i, p in enumerate((12, 15, 9, 12))]
    return {"cur": cur, "prior": prior}


def _offers(points_line=17.5, over=-110, under=-110, extra=()):
    o = [{"market": "player_points", "player": "Davion Mitchell", "point": points_line,
          "over": {"draftkings": over, "fanduel": over + 5}, "under": {"draftkings": under, "fanduel": under - 5}}]
    return o + list(extra)


GAME = {"label": "Miami Heat @ Atlanta Hawks", "home_id": AWAY, "away_id": HOME, "home_name": "Atlanta Hawks",
        "away_name": "Miami Heat", "home_abbr": "ATL", "away_abbr": "MIA", "game_date": "2026-10-28T23:00Z"}
LINES = [{"home_team": "Atlanta Hawks", "away_team": "Miami Heat", "spreads": {"Atlanta Hawks": -4.5, "Miami Heat": 4.5},
          "total": 231.5}]
REST = {HOME: 2, AWAY: 1}


def _slate(offers=None, market_keys=None):
    return SP.slate_reads([GAME], _sample(), offers if offers is not None else _offers(), book="draftkings",
                          rest=REST, game_lines=LINES,
                          markets={k: SP.CORE_MARKETS[k] for k in (market_keys or ["player_points"])})


def _position_matchups_row(market="Points", offers=None):
    """What Position Matchups' Player props computes for Mitchell (Miami is the AWAY team), built the way the page
    builds it."""
    s = _sample()
    rot = PPR.team_rotation(s["cur"], s["prior"], HOME, None, "NBA", last_n=7)
    t = PPR.market_tables(s["cur"], s["prior"], market, "NBA")
    ctx = PPR.game_context(HOME, False, -4.5, 231.5, REST[HOME], REST[AWAY], s["cur"],
                           offers=offers if offers is not None else _offers(), book="draftkings", sport="NBA")
    rows = PPR.player_rows(rot, AWAY, market, t["cur"], t["prior"], s["cur"], s["prior"], mode="blend", context=ctx)
    return next(r for r in rows if r["pid"] == 7)


# --------------------------------------------------------------------------- the same read everywhere
def test_the_slate_read_is_the_position_matchups_read():
    pm = _position_matchups_row()
    sl = _slate()[(7, "player_points")]
    for k in ("projection", "line", "p_model", "p_market", "p_final", "side", "lean", "factor", "env", "gap"):
        assert sl[k] == pm[k], k
    assert pm["env"] != 1.0                      # the game lines (spread + total) are folded in on both


def test_best_bets_plays_are_player_props_reads_at_the_book_line():
    reads = _slate()
    plays = NP.build_best_bets([{"Player": "Davion Mitchell", "_pid": 7, "Team": "Miami Heat", "Opp": "Atlanta Hawks",
                                 "GameLabel": GAME["label"], "_game_date": GAME["game_date"], "_game_log": []}],
                               reads=reads)
    row = reads[(7, "player_points")]
    p = next(x for x in plays if x["PlayerId"] == 7 and x["Market"] == "Points")
    assert p["Model"] == "player-props" and p["Line"] == 17.5 and p["LineSource"] == "book"
    assert p["Projection"] == round(row["projection"], 2) and p["Side"] == row["side"] and p["Lean"] == row["lean"]
    sp = SP.side_probs(row)
    assert p["ModelProb"] == round(sp["p_final"], 4)                           # Player props' "Chance"
    assert p["RealPrice"] == (row["over_price"] if p["Side"] == "Over" else row["under_price"])
    assert (p["Conviction"] > 1.0) == (row["lean"] in ("Over", "Under"))


def test_no_book_line_no_play():
    reads = _slate(offers=_offers(), market_keys=["player_points", "player_rebounds"])
    plays = SP.plays(reads, [])
    assert {p["Market"] for p in plays} == {"Points"}                           # nobody posted rebounds
    assert all(p["LineSource"] == "book" for p in plays)


def test_a_line_far_from_the_projection_is_held_for_news_on_every_page():
    reads = _slate(offers=_offers(points_line=9.5, over=-150, under=120))
    row = reads[(7, "player_points")]
    assert row["gap"] == "big"
    p = SP.play_from_row(row, None)
    assert p["Lean"] in ("Check news", "No lean") and p["Conviction"] == 1.0 and p["Notes"] == PE.GAP_TAG
    assert p["Why"].startswith("⚠️")


def test_edge_board_prices_with_the_player_props_model():
    reads = _slate()
    index = NP.build_projection_index([], [], reads=reads)
    e = index[(NP.normalize_name("Davion Mitchell"), "player_points")]
    row = reads[(7, "player_points")]
    assert e["mean"] == row["projection"] and e["line"] == 17.5
    # the probability array reproduces the Player props model probability at any half line
    for line in (12.5, 17.5, 22.5):
        assert projections.prob_over(e["dist"], line) == pytest.approx(
            PE.prob_over(row["projection"], row["values"], line, row["dist"]), abs=1e-6)
    edges, _ = O.compute_edges(index, _offers(), projections_module=NP)
    over = next(x for x in edges if x["Side"] == "Over")
    read = PE.read_line(row["projection"], row["values"], 17.5, row["dist"], -105, -110,
                        O.devig_two_way(-110, -110) * 0.5 + O.devig_two_way(-105, -115) * 0.5)
    assert over["ModelProb"] == round(read["p_final"], 4) and over["Proj"] == round(row["projection"], 2)
    assert "Lean" in over


def test_edge_board_model_board_uses_book_lines_only():
    reads = _slate(market_keys=["player_points", "player_rebounds"])
    board = NP.default_board_from_index(NP.build_projection_index([], [], reads=reads))
    assert board and all(b["Line"] == 17.5 and b["Market"] == "Points" for b in board)
    assert {b["Lean"] for b in board} <= {"Over", "Under", "No lean", "Check news"}


# --------------------------------------------------------------------------- fallbacks
def test_the_old_engine_now_uses_the_shared_form_rule():
    log = [dict(pts=p, reb=1, ast=6, fg3m=2, src="current") for p in (21, 22, 18, 11)] + \
          [dict(pts=p, reb=2, ast=5, fg3m=1, src="prior") for p in (12, 15, 9, 12, 14, 10)]
    rows = [{"Player": "Davion Mitchell", "Team": "MIA", "GameLabel": "x", "_game_log": log, "_pid": 7}]
    idx = NP.build_projection_index(rows, [], sims=40000, seed=3)
    mean = idx[(NP.normalize_name("Davion Mitchell"), "player_points")]["mean"]
    assert mean == pytest.approx(FPol.form_avg(log, "pts"), abs=0.25)          # 18.2-ish, not the old 15.6
    old = float(np.mean([g["pts"] for g in log]))
    assert abs(mean - old) > 2


def test_placeholder_plays_are_dropped_when_the_books_have_lines():
    import best_bets_data as BBD
    plays = [{"LineSource": "book"}, {"LineSource": "default"}]
    assert BBD.drop_placeholder_plays(plays) == [{"LineSource": "book"}]
    only_default = [{"LineSource": "default"}]
    assert BBD.drop_placeholder_plays(only_default) == only_default              # no lines at all: nothing to compare


def test_game_lines_match_by_team_name():
    assert SP.game_lines_for(LINES, "Atlanta Hawks", "Miami Heat") == {"spread_home": -4.5, "total": 231.5}
    assert SP.game_lines_for(LINES, "Boston Celtics", "Miami Heat") == {}


def test_best_bets_loader_uses_the_shared_model_for_nba(monkeypatch):
    import best_bets_data as BBD
    import sports
    nba = sports.get("NBA")
    slate_row = {"Player": "Davion Mitchell", "_pid": 7, "Team": "Miami Heat", "Opp": "Atlanta Hawks",
                 "GameLabel": GAME["label"], "_game_date": GAME["game_date"], "_game_log": [], "_team_id": HOME}
    monkeypatch.setattr(nba.engine, "build_slate", lambda d, *a, **k: ([slate_row], [GAME]))
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "k")
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: _offers())
    monkeypatch.setattr(BBD, "fetch_slate_game_lines_cached", lambda *a, **k: LINES)
    monkeypatch.setattr(BBD, "load_props_model_inputs",
                        lambda sk, d, teams: {"sample": _sample(), "injuries": {}, "rest": REST})
    monkeypatch.setattr(BBD, "attach_team_trend", lambda *a, **k: None)
    BBD.load_generic_best_bets_board.clear()
    plays, meta, _books = BBD.load_generic_best_bets_board("NBA", "2026-10-28", "draftkings")
    pts = [p for p in plays if p["PlayerId"] == 7 and p["Market"] == "Points"]
    assert pts and pts[0]["Model"] == "player-props"
    assert pts[0]["Projection"] == round(_position_matchups_row()["projection"], 2)
    assert all(p["LineSource"] == "book" for p in plays)
    BBD.load_generic_best_bets_board.clear()


# --------------------------------------------------------------------------- the pages render it
def _page_board():
    import datetime as dt
    when = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%MZ")
    game = dict(GAME, game_date=when)
    lean = _slate()[(7, "player_points")]
    held = _slate(offers=_offers(points_line=9.5, over=-150, under=120))[(7, "player_points")]
    plays = []
    for row in (lean, dict(held, pid=8, player="Held Guy")):
        row = dict(row, game_date=when)
        p = SP.play_from_row(row, None)
        p["GameDate"] = when
        p["TeamTrend"] = "➡️ Steady"                    # attach_team_trend's column (the real loader adds it)
        plays.append(p)
    # make the first one a lean whatever the toy numbers say, so the board has a row to show
    plays[0].update(Lean=plays[0]["Side"], Conviction=1.3)
    plays[1].update(Lean="Check news", Conviction=1.0)
    return plays, [game]


@pytest.mark.parametrize("page", ["1_#U2b50_Best_Bets.py", "2_Graded_Picks.py", "3_Suggested_Parlays.py"])
def test_nba_pick_pages_render_the_shared_model(monkeypatch, page):
    from pathlib import Path
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    import best_bets_data as BBD
    import quick_log
    import sports
    st.cache_data.clear()
    plays, meta = _page_board()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings"]))
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: None)
    monkeypatch.setattr(sports, "has_started", lambda *a, **k: False)
    monkeypatch.setattr(st, "page_link", lambda *a, **k: None)
    monkeypatch.setattr(quick_log, "render_quick_log", lambda *a, **k: None)
    at = AppTest.from_file(str(Path(__file__).parent / "views" / page), default_timeout=90)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    if page.startswith("1_"):
        board = [d.value for d in at.dataframe if "Projection" in getattr(d.value, "columns", [])]
        assert board and list(board[0]["Player"]) == ["Davion Mitchell"]                  # the held play isn't ranked
        assert any("Check the news" in e.label or "check the news" in e.label for e in at.expander)
        assert any("Same model as" in c.value for c in at.caption)
