"""
Oct 29: NFL, NCAAF and NHL pick pages (Best Bets, Edge Board, Graded Picks, Parlays, Slip Lab) read players through
the same Player props model Position Matchups uses -- one shared function (slate_props.team_rows) for the page and
the slate -- plus the event matcher that never matched an NFL game to the books ("KC" vs "Kansas City Chiefs").
"""

import pytest

import best_bets_data as BBD
import nfl_projections as NFLP
import nhl_projections as NHLP
import odds_api as O
import position_lines as PL
import props_engine as PE
import slate_props as SP
from test_position_page import football_props_bundle, nhl_bundle

NFL_GAME = {"label": "AWAY0 @ HOME0", "home": "HOME0", "away": "AWAY0", "game_date": "2026-11-01T17:00:00Z"}
NHL_GAME = {"label": "Team 2 @ Team 1", "home": "Team 1", "away": "Team 2", "game_date": "2026-10-29T23:00:00Z"}


def wr_offer(point=59.5):
    return [{"market": "player_reception_yds", "player": "HOME0 Wideout", "point": point,
             "over": {"draftkings": -115, "fanduel": -110}, "under": {"draftkings": -105, "fanduel": -110}}]


def sog_offer(point=2.5):
    return [{"market": "player_shots_on_goal", "player": "Center 1", "point": point,
             "over": {"draftkings": -130}, "under": {"draftkings": 100}}]


# --------------------------------------------------------------------------- the books' event, matched
def test_nfl_abbreviations_and_college_names_match_the_books():
    ev = [{"id": 1, "home_team": "Green Bay Packers", "away_team": "Carolina Panthers"},
          {"id": 2, "home_team": "Ohio State Buckeyes", "away_team": "Penn State Nittany Lions"},
          {"id": 3, "home_team": "Miami Hurricanes", "away_team": "Miami (OH) RedHawks"},
          {"id": 4, "home_team": "Los Angeles Rams", "away_team": "Seattle Seahawks"}]
    assert PL.match_event(ev, "GB", "CAR")["id"] == 1                       # Thursday night's miss
    assert PL.match_event(ev, "LA", "SEA")["id"] == 4
    assert PL.match_event(ev, "Ohio State", "Penn State")["id"] == 2
    assert PL.match_event(ev, "Atlanta Hawks", "Miami Heat") is None
    assert PL.match_event(ev, "Carolina Panthers", "Green Bay Packers")["id"] == 1  # full names, either order


def test_game_lines_come_from_one_sport_wide_request(monkeypatch):
    seen = []
    monkeypatch.setattr(O, "_get", lambda path, params: seen.append((path, params)) or ([{"id": "e"}], {"remaining": "9"}))
    data, hdr = O.fetch_sport_game_lines("k", sport="americanfootball_nfl")
    assert data == [{"id": "e"}] and len(seen) == 1
    assert seen[0][0] == "sports/americanfootball_nfl/odds" and seen[0][1]["markets"] == "h2h,spreads,totals"


# --------------------------------------------------------------------------- the same read on the page and the slate
def test_football_slate_read_is_the_position_matchups_read():
    b = football_props_bundle("NFL")
    gl = {NFL_GAME["label"]: {"spread_home": -3.5, "total": 47.5, "p_home": 0.6}}
    reads = SP.family_slate_reads("NFL", [NFL_GAME], {NFL_GAME["label"]: b}, wr_offer(), gl, book="draftkings",
                                  markets={"player_reception_yds": "Receiving Yards"})
    sl = next(r for (pid, mk), r in reads.items() if r["player"] == "HOME0 Wideout")
    page_row = next(r for r in SP.team_rows("football", "NFL", b, "HOME0", "AWAY0", "Receiving Yards", -3.5, 47.5,
                                            offers=wr_offer(), book="draftkings") if r["player"] == "HOME0 Wideout")
    for k in ("projection", "line", "p_final", "side", "lean", "gap"):
        assert sl[k] == page_row[k], k
    assert sl["line"] == 59.5 and sl["line_src"] == "book" and sl["sd_floor"] == (0.45, 8.0)
    p = SP.play_from_row(sl, None)
    assert p["Market"] == "Receiving Yards" and p["Use"] in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE, PE.USE_PASS)


def test_hockey_uses_the_moneyline_goal_margin_like_the_page():
    import props_odds as PO
    b = nhl_bundle()
    gl = {NHL_GAME["label"]: {"spread_home": -1.5, "total": 6.5, "p_home": 0.62}}
    reads = SP.family_slate_reads("NHL", [NHL_GAME], {NHL_GAME["label"]: b}, sog_offer(), gl,
                                  markets={"player_shots_on_goal": "Shots on Goal"})
    sl = next(r for r in reads.values() if r["player"] == "Center 1")
    page_row = next(r for r in SP.team_rows("hockey", "NHL", b, 1, 2, "Shots on Goal", PO.hockey_spread_from_ml(0.62), 6.5,
                                            offers=sog_offer()) if r["player"] == "Center 1")
    assert sl["projection"] == page_row["projection"] and sl["env"] == page_row["env"] and sl["line"] == 2.5
    assert SP.game_line_values("hockey", gl[NHL_GAME["label"]])[0] == PO.hockey_spread_from_ml(0.62)


# --------------------------------------------------------------------------- the pick pages
def test_board_keeps_the_old_engine_only_for_markets_the_props_model_lacks():
    reads = {("p", "player_reception_yds"): {"market": "Receiving Yards"}}
    legacy = [{"Market": "Receiving Yards", "LineSource": "book", "Player": "old"},
              {"Market": "Pass Completions", "LineSource": "book", "Player": "kept"},
              {"Market": "Pass Completions", "LineSource": "default", "Player": "placeholder"}]
    import slate_props
    orig = slate_props.plays
    try:
        slate_props.plays = lambda r, rows: [{"Market": "Receiving Yards", "Player": "new"}]
        out = BBD.compose_board("NFL", reads, [], legacy)
    finally:
        slate_props.plays = orig
    assert [p["Player"] for p in out] == ["new", "kept"]
    assert BBD.compose_board("NFL", None, [], legacy)[-1]["Player"] == "kept"                  # no reads: placeholders out


def test_football_slate_reads_through_the_best_bets_loader(monkeypatch):
    import position_data as PD
    b = football_props_bundle("NFL")
    monkeypatch.setattr(PD, "list_games", lambda sport, d: [NFL_GAME])
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "k")
    monkeypatch.setattr(BBD, "fetch_game_lines_by_label", lambda *a, **k: {NFL_GAME["label"]: {"spread_home": -3.5, "total": 47.5}})
    monkeypatch.setattr(BBD, "load_family_bundles", lambda *a, **k: {NFL_GAME["label"]: b})
    reads = BBD.slate_reads_for("NFL", "2026-11-01", [{"label": NFL_GAME["label"]}], wr_offer(), "draftkings")
    row = next(r for r in reads.values() if r["player"] == "HOME0 Wideout" and r["market_key"] == "player_reception_yds")
    assert row["market"] == NFLP._MARKET_SPEC["player_reception_yds"][1] and row["line"] == 59.5
    assert "NFL" in BBD.PROPS_MODEL_SPORTS and "NCAAF" in BBD.PROPS_MODEL_SPORTS and "NHL" in BBD.PROPS_MODEL_SPORTS


def test_edge_board_mixes_reads_and_the_old_engine():
    b = nhl_bundle()
    reads = SP.family_slate_reads("NHL", [NHL_GAME], {NHL_GAME["label"]: b}, sog_offer(),
                                  {NHL_GAME["label"]: {"total": 6.5, "p_home": 0.55}},
                                  markets={"player_shots_on_goal": "Shots on Goal"})
    idx = SP.index_from_reads(reads, [], NHLP.normalize_name)
    e = idx[(NHLP.normalize_name("Center 1"), "player_shots_on_goal")]
    row = e["read"]
    assert e["line"] == 2.5 and e["mean"] == row["projection"]
    import projections
    assert projections.prob_over(e["dist"], 2.5) == pytest.approx(
        PE.prob_over(row["projection"], row["values"], 2.5, row["dist"], *row["sd_floor"]), abs=1e-6)
    board = SP.board_from_index(idx, NHLP)
    assert board and all(x["Line"] == 2.5 and "Use" in x for x in board)


def test_anytime_td_reads_are_yes_plays():
    row = {"pid": 1, "player": "RB", "market": "Anytime TD", "market_key": "player_anytime_td", "line": 0.5,
           "line_src": "book", "projection": 0.8, "values": [1, 0, 1, 1], "dist": "count", "side": "Over",
           "p_final": 0.55, "p_model": 0.58, "p_market": 0.5, "lean": "Over", "ev": 0.05, "over_price": 110,
           "under_price": None, "flags": [], "out": False, "book": {"best_over": ("draftkings", 110)}}
    p = SP.play_from_row(row, None)
    assert p["Side"] == "Yes" and p["Line"] is None
    assert SP.play_from_row(dict(row, side="Under", p_final=0.4), None) is None


def test_only_games_with_posted_props_get_built(monkeypatch):
    import position_data as PD
    other = {"label": "X @ Y", "home": "Ohio State", "away": "Penn State", "game_date": "2026-10-31T16:00:00Z"}
    built = []
    monkeypatch.setattr(PD, "list_games", lambda sport, d: [NFL_GAME, other])
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "k")
    monkeypatch.setattr(BBD, "fetch_game_lines_by_label", lambda *a, **k: {})
    monkeypatch.setattr(BBD, "load_family_bundles", lambda sport, d, labels: built.append(labels) or {})
    offers = [dict(o, home_team="Penn State Nittany Lions", away_team="Ohio State Buckeyes") for o in wr_offer()]
    BBD.slate_reads_for("NCAAF", "2026-10-31", [{"label": NFL_GAME["label"]}, {"label": "X @ Y"}], offers, None)
    assert built == [("X @ Y",)]
