"""Build 246 on the real pages: Matchup Lab, Hot Hand Engine, Best Bets, Graded Picks and the parlay pages run for NBA with the
new markets (combos, steals, blocks, blocks+steals, turnovers, threes attempted) and show them."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import basketball_markets as BM
import best_bets_data as BBD
import nba_engine as NE
import nba_projections as NP
import quick_log
import sports

VIEWS = Path(__file__).parent / "views"
ALL = ["Points", "Rebounds", "Assists", "Threes Made", "Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Reb+Ast", "Steals", "Blocks",
       "Blocks+Steals", "Turnovers", "Threes Attempted"]


def _games(n=12, **kw):
    base = {"pts": 22, "reb": 7, "ast": 5, "fg3m": 2, "min": 32, "stl": 1, "blk": 1, "tov": 3, "fg3a": 6}
    out = []
    for i in range(n):
        g = {**base, "pts": 22 + (i % 5), "date": f"2026-11-{i + 1:02d}T00:00Z", "opp": "Opp", **kw}
        out.append(BM.add_derived(g))
    return out


def _row(name="Star Guard", team="Home", opp="Away", team_id=1, opp_id=2, pid=11):
    log = _games()
    return {"Player": name, "Team": team, "GameLabel": f"{opp} @ {team}", "Opp": opp, "AvgMin": 32.0, "PTS": 24.0, "REB": 7.0,
            "AST": 5.0, "FG3M": 2.0, **BM.row_columns(log), "_pid": pid, "_game_log": log,
            "_game_date": "2026-11-10T00:00:00Z", "_opp_id": opp_id, "_team_id": team_id}


_OPP = {"pts": 110.0, "reb": 44.0, "ast": 25.0, "fg3m": 12.0, "poss": 100.0, "stl": 8.0, "blk": 5.0, "tov": 13.0, "fg3a": 35.0,
        "pr": 154.0, "pa": 135.0, "ra": 69.0, "pra": 179.0, "bs": 13.0}


@pytest.fixture
def nba_engine(monkeypatch):
    import streamlit as st
    st.cache_data.clear()
    rows = [_row(), _row("Wing Man", "Away", "Home", 2, 1, 12)]
    meta = [{"label": "Away @ Home", "away_name": "Away", "home_name": "Home", "game_date": "2026-11-10T00:00:00Z",
             "home_id": 1, "away_id": 2, "home_abbr": "HOM", "away_abbr": "AWY"}]
    monkeypatch.setattr(NE, "build_slate", lambda d, *a, **k: (rows, meta))
    monkeypatch.setattr(NE, "get_team_injuries", lambda abbr: [])
    monkeypatch.setattr(NE, "get_team_recent_allowed_stats", lambda *a, **k: dict(_OPP))
    monkeypatch.setattr(NE, "get_team_rest_info", lambda *a, **k: {"rest_days": 2, "is_back_to_back": False})
    monkeypatch.setattr(NE, "get_player_history_vs_opponent", lambda *a, **k: _games(3, pts=18))
    monkeypatch.setattr(NE, "get_player_season_games", lambda *a, **k: _games(15))
    monkeypatch.setattr(sports, "has_started", lambda *a, **k: False)
    monkeypatch.setattr(quick_log, "render_quick_log", lambda *a, **k: None)
    monkeypatch.setenv("ODDS_API_KEY", "")
    return rows


def _run(page, **session):
    at = AppTest.from_file(str(VIEWS / page), default_timeout=120)
    at.session_state["sport"] = "NBA"
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_matchup_lab_draws_a_trend_chart_for_every_market_and_profiles_them(nba_engine):
    at = _run("11_Matchup_Lab.py")
    charts = at.get("plotly_chart")
    assert len(charts) == 13 + 1                                   # one per market, plus Minutes
    shown = {c.proto.figure.layout.title.text if hasattr(c.proto, "figure") else None for c in charts}
    profile = [d for d in at.dataframe if "Recent Avg" in d.value.columns][0].value
    assert set(profile["Market"]) == set(ALL) | {"Minutes"}
    pra = profile[profile["Market"] == "Pts+Reb+Ast"].iloc[0]
    assert round(float(pra["Recent Avg"]), 1) == round(BM.average_for(_games(), "pra"), 1)
    opp = [d for d in at.dataframe if "Opp Team Total (season)" in d.value.columns][0].value
    assert float(opp[opp["Market"] == "Pts+Reb+Ast"]["Opp Team Total (season)"].iloc[0]) == 179.0
    assert float(opp[opp["Market"] == "Steals"]["Opp Team Total (season)"].iloc[0]) == 8.0
    assert float(opp[opp["Market"] == "Points"]["Opp Team Total (season)"].iloc[0]) == 110.0   # was blank in Season mode before 246
    recent = [d.value for d in at.dataframe if "Opp" in d.value.columns and "PRA" in d.value.columns][0]
    assert list(recent["PRA"])[0] == BM.game_value(_games()[0], "pra") and "STL" in recent.columns


def test_matchup_lab_skips_a_chart_for_a_stat_the_players_game_lines_do_not_carry(nba_engine, monkeypatch):
    old = [{k: v for k, v in g.items() if k in ("pts", "reb", "ast", "fg3m", "min", "date", "opp")} for g in _games()]
    for r in nba_engine:
        r["_game_log"] = old
        r.update(BM.row_columns(old))
    monkeypatch.setattr(NE, "get_player_season_games", lambda *a, **k: old)
    monkeypatch.setattr(NE, "get_player_history_vs_opponent", lambda *a, **k: old[:3])
    at = _run("11_Matchup_Lab.py")
    assert len(at.get("plotly_chart")) == 8 + 1                    # the four core stats + four combos + Minutes
    assert any("not in this player's recent game lines yet" in c.value for c in at.caption)


def test_hot_hand_lists_the_new_markets_and_sorts_without_error(nba_engine):
    at = _run("10_Hot_Hand_Engine.py")
    board = [d for d in at.dataframe if "Matchup Score" in d.value.columns][0].value
    assert set(board["Market"]) == set(ALL)
    assert float(board[(board["Market"] == "Pts+Reb+Ast") & (board["Player"] == "Star Guard")]["Recent Avg"].iloc[0]) > 30
    picker = [m for m in at.multiselect if m.label == "Markets"][0]
    assert set(picker.value) == set(ALL)


def _plays():
    out = []
    for i, m in enumerate(ALL):
        stat = {"Points": "pts", "Rebounds": "reb", "Assists": "ast", "Threes Made": "fg3m"}.get(m) or BM.EXTRA_DISPLAY_TO_STAT[m]
        line = {"Points": 22.5, "Rebounds": 6.5, "Assists": 4.5, "Threes Made": 2.5, "Pts+Reb+Ast": 33.5, "Pts+Reb": 28.5,
                "Pts+Ast": 26.5, "Reb+Ast": 11.5, "Steals": 0.5, "Blocks": 0.5, "Blocks+Steals": 1.5, "Turnovers": 2.5,
                "Threes Attempted": 5.5}[m]
        out.append({"Player": f"Player {i}", "PlayerId": 100 + i, "Team": "Home" if i % 2 else "Away", "Game": "Away @ Home", "Opp": "X",
                    "Market": m, "Side": "Over", "Line": line, "LineSource": "default" if m == "Threes Attempted" else "book",
                    "ModelProb": 0.6, "Fair": -150, "Conviction": 1.5 + i / 100, "Why": "cleared in 8 of last 10", "_stat_key": stat,
                    "GameDate": "2026-11-10T00:00:00Z", "TeamTrend": "➡️ Steady", "_game_log": _games(), "RealPrice": -110,
                    "RealPriceBook": "draftkings", "PriceSource": "book", "_ceiling": 2.0})
    return out


def _patch_board(monkeypatch):
    import streamlit as st
    st.cache_data.clear()
    meta = [{"label": "Away @ Home", "game_date": "2026-11-10T00:00:00Z", "away_name": "Away", "home_name": "Home"}]
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (_plays(), meta, ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: [])
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: None)
    monkeypatch.setattr(sports, "has_started", lambda *a, **k: False)
    monkeypatch.setattr(st, "page_link", lambda *a, **k: None)
    monkeypatch.setattr(quick_log, "render_quick_log", lambda *a, **k: None)


@pytest.mark.parametrize("page", ["1_#U2b50_Best_Bets.py", "2_Graded_Picks.py"])
def test_single_play_boards_preselect_everything_a_book_prices_but_not_threes_attempted(monkeypatch, page):
    _patch_board(monkeypatch)
    at = _run(page)
    picker = [m for m in at.multiselect if m.label.startswith("Markets")][0]
    assert set(ALL) == set(picker.options)
    assert set(picker.value) == set(ALL) - {"Threes Attempted"}


def test_best_bets_receipts_for_a_combo_sum_the_games_parts(monkeypatch):
    _patch_board(monkeypatch)
    at = _run("1_#U2b50_Best_Bets.py")
    picker = [s for s in at.selectbox if s.label.startswith("Select a play to inspect")][0]
    idx = next(i for i, l in enumerate(picker.options) if "Pts+Reb+Ast Over 33.5" in l)
    picker.select_index(idx).run()
    assert not at.exception, [e.value for e in at.exception]
    metrics = {m.label: m.value for m in at.metric}
    games = _games()
    expected_hits = sum(1 for g in games if BM.game_value(g, "pra") > 33.5)
    assert metrics["Games sampled"] == "12" and metrics["Cleared 33.5"] == f"{expected_hits}/12"
    assert metrics["Recent average"] == f"{BM.average_for(games, 'pra'):.1f}"
    log_table = [d.value for d in at.dataframe if "PRA" in d.value.columns][0]
    assert list(log_table["PRA"]) == [BM.game_value(g, "pra") for g in games]


def test_best_bets_receipts_say_so_when_a_players_game_lines_lack_the_stat(monkeypatch):
    _patch_board(monkeypatch)
    plays = _plays()
    for p in plays:
        p["_game_log"] = [{"pts": 20, "reb": 5, "ast": 4, "fg3m": 1, "min": 30, "date": "2026-11-01T00:00Z", "opp": "X"}] * 4
    monkeypatch.setattr(BBD, "load_generic_best_bets_board",
                        lambda *a, **k: (plays, [{"label": "Away @ Home", "game_date": "2026-11-10T00:00:00Z",
                                                  "away_name": "Away", "home_name": "Home"}], ["draftkings"]))
    at = _run("1_#U2b50_Best_Bets.py")
    picker = [s for s in at.selectbox if s.label.startswith("Select a play to inspect")][0]
    picker.select_index(next(i for i, l in enumerate(picker.options) if "Steals Over" in l)).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("recent game lines don't include that stat yet" in c.value for c in at.caption)


@pytest.mark.parametrize("page", ["3_Suggested_Parlays.py", "4_Speculative_Basket.py"])
def test_the_parlay_pages_run_with_the_new_markets_in_the_pool(monkeypatch, page):
    _patch_board(monkeypatch)
    at = _run(page)
    assert not at.exception
