"""Nov 25: Soft Spots (NBA) -- defenses that give up the most to a position, with each player's H2 pick."""
import soft_spots as SS


def _summary():
    out = {}
    for i in range(10):
        out[i] = {"G": {"games": 8, "stats": {"pts": 40 + i, "reb": 10, "ast": 9, "fg3m": 4}},
                  "F": {"games": 8, "stats": {"pts": 35, "reb": 15, "ast": 5, "fg3m": 3}},
                  "C": {"games": 2, "stats": {"pts": 99, "reb": 9, "ast": 2, "fg3m": 0}}}      # too few games
    out[9]["G"]["stats"]["pts"] = 60                     # the softest guard defense by far
    return out


def test_table_ranks_and_percent_vs_average():
    tb = SS.table(_summary(), "pts")
    assert "C" not in tb                                 # under MIN_GAMES everywhere
    v, rank, pct = tb["G"][9]
    assert v == 60 and rank == 1 and pct > 0.25
    assert tb["F"][0][2] == 0                            # everyone equal: 0% vs average


def test_spots_lists_tonights_soft_spots_with_the_players_there():
    depth = {"OFF": {"G": [{"name": "Star Guard", "avg_min": 34}, {"name": "Bench", "avg_min": 6}]}}
    rows = SS.spots(_summary(), [(9, "OFF", "OFF @ D9", "7:00 PM"), (0, "OFF", "x", "")],
                    lambda t: depth.get(t, {}), {9: "Defense Nine", "OFF": "Offense"}, stats=("pts",))
    assert len(rows) == 1 and rows[0]["defense"] == "Defense Nine" and rows[0]["slot"] == "G"
    assert [p["name"] for p in rows[0]["players"]] == ["Star Guard"]         # 10+ minutes only
    assert SS.headline(rows[0]).startswith("Defense Nine allows the most points to guards")


def test_pick_for_prefers_the_same_stat():
    picks = [{"kind": "Prop", "player": "Star Guard", "market": "Rebounds", "chance": 0.6, "pick": "r"},
             {"kind": "Prop", "player": "Star Guard", "market": "Points", "chance": 0.55, "pick": "p"}]
    assert SS.pick_for("Star Guard", picks, "pts")["pick"] == "p"
    assert SS.pick_for("Star Guard", picks, "ast")["pick"] == "r"
    assert SS.pick_for("Nobody", picks) is None
    assert SS.ordinal(1) == "most" and SS.ordinal(2) == "2nd most" and SS.ordinal(13) == "13th most"


def test_page_renders_with_a_fake_slate(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import position_data as PD
    import position_matchups as PM
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(PD, "list_games", lambda sp, d: [{"label": "7:00 PM", "home": "D9", "away": "OFF",
                                                          "home_id": 9, "away_id": "OFF"}])
    monkeypatch.setattr(PD, "load_bundle", lambda sp, d, g, prev: {"allowed": {}, "props": {"pgames": []},
                                                                   "all_names": {9: "Defense Nine", "OFF": "Offense"}})
    monkeypatch.setattr(PM, "summarize", lambda allowed, sport, n=None: _summary())
    monkeypatch.setattr(PM, "usage_depth", lambda pg, team, sport, last_n=10:
                        {"G": [{"name": "Star Guard", "avg_min": 34}]} if team == "OFF" else {})
    monkeypatch.setattr(TB, "load_all_props", lambda sp, d: [{"kind": "Prop", "player": "Star Guard", "market": "Points",
                                                              "side": "Over", "line": 20.5, "chance": 0.57,
                                                              "pick": "Star Guard Points Over 20.5", "use": "🎯 Single only",
                                                              "price": -110, "earned": 0.57}])
    at = AppTest.from_file("views/62_Soft_Spots.py", default_timeout=60).run()
    assert not at.exception
    md = " ".join(m.value for m in at.markdown)
    assert "Defense Nine allows the most points to guards" in md and "Star Guard" in md
    assert "ss_open_0_0" in [b.key for b in at.button if b.key]


# --------------------------------------------------------------------------- Nov 26: every sport + the game card
def _football():
    out = {}
    for i in range(12):
        out[f"T{i}"] = {"QB": {"games": 8, "stats": {"pass_yds": 220.0, "pass_td": 1.4, "rush_yds": 15.0}},
                        "WR1": {"games": 8, "stats": {"rec": 5.0, "rec_yds": 70.0, "rec_td": 0.4}}}
    out["T0"]["QB"]["stats"]["pass_td"] = 2.6            # the softest pass-TD defense by far
    return out


def test_football_spots_name_the_role_and_who_plays_it():
    depth = {"CHI": {"QB": [{"name": "Caleb Williams", "avg_min": None}]}}
    rows = SS.spots_any("NFL", _football(), [("T0", "CHI", "CHI @ T0", "1:00 PM")], lambda t: depth.get(t, {}),
                        {"T0": "Detroit Lions", "CHI": "Chicago Bears"})
    assert len(rows) == 1 and rows[0]["stat"] == "pass_td" and rows[0]["rank"] == 1 and rows[0]["grade"] == "A+"
    assert SS.headline_any(rows[0]).startswith("Detroit Lions allows the most passing TDs to QBs")
    lines = SS.card_lines(rows)["Detroit Lions"]
    assert lines == ["**A+** · most passing TDs to QBs (2.6 a game) → **Caleb Williams**"]


def test_pairs_by_role_and_letters():
    assert ("QB", "rec") not in SS.pairs_for("NFL") and ("TE1", "rec_yds") in SS.pairs_for("NFL")
    assert len(SS.pairs_for("NBA")) == 12
    assert SS.letter(1, 32) == "A+" and SS.letter(32, 32) == "F" and SS.top_cut(32) == 5 and SS.top_cut(10) == 3


def test_depth_from_allowed_takes_the_usual_slot_holder():
    allowed = {"X": [{"offense": "CHI", "order": 11, "who": {"QB": ["Caleb Williams"], "WR1": ["Rome Odunze"]}},
                     {"offense": "CHI", "order": 10, "who": {"QB": ["Caleb Williams"], "WR1": ["DJ Moore"]}}],
               "Y": [{"offense": "CHI", "order": 9, "who": {"QB": ["Caleb Williams"], "WR1": ["Rome Odunze"]}}]}
    d = SS.depth_from_allowed(allowed, "CHI")
    assert d["QB"][0]["name"] == "Caleb Williams" and d["WR1"][0]["name"] == "Rome Odunze"


def test_match_game_handles_nfl_abbreviations_and_short_names():
    games = [{"home": "DET", "away": "CHI", "home_id": "DET", "away_id": "CHI"}]
    assert SS.match_game("NFL", games, "Chicago Bears", "Detroit Lions") is games[0]
    nba = [{"home": "Boston Celtics", "away": "Atlanta Hawks", "home_abbr": "BOS", "away_abbr": "ATL"}]
    assert SS.match_game("NBA", nba, "Atlanta Hawks", "Boston Celtics") is nba[0]
    assert SS.match_game("NFL", games, "Green Bay Packers", "Detroit Lions") is None


def test_game_card_lines_for_one_matchup():
    import game_card as GC
    data = {"games": [{"home": "T0", "away": "CHI", "home_id": "T0", "away_id": "CHI"}], "summary": _football(),
            "allowed": {"T5": [{"offense": "CHI", "order": 11, "who": {"QB": ["Caleb Williams"]}}]},
            "names": {}, "pgames": []}
    got = GC.soft_spot_lines("NCAAF", data, "CHI", "T0")
    assert list(got) == ["T0"] and "Caleb Williams" in got["T0"][0]


def test_page_other_sport(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(SS, "load_league", lambda sp, d: {
        "games": [{"label": "1:00 PM", "home": "T0", "away": "CHI", "home_id": "T0", "away_id": "CHI"}],
        "summary": _football(), "allowed": {"T5": [{"offense": "CHI", "order": 11, "who": {"QB": ["Caleb Williams"]}}]},
        "names": {"T0": "Detroit Lions", "CHI": "Chicago Bears"}, "pgames": []})
    monkeypatch.setattr(TB, "load_all_props", lambda sp, d: [])
    at = AppTest.from_file("views/62_Soft_Spots.py", default_timeout=60)
    at.session_state["ss_sport"] = "NFL"
    at.run()
    assert not at.exception
    md = " ".join(m.value for m in at.markdown)
    assert "Detroit Lions allows the most passing TDs to QBs" in md and "Caleb Williams" in md


def test_out_players_leave_and_the_next_man_moves_up():
    d = {"RB1": [{"name": "Kenneth Walker III"}, {"name": "Emmett Johnson"}], "RB2": [{"name": "Emmett Johnson"},
                                                                                     {"name": "Jaydn Ott"}]}
    got = SS.without_out(d, {"Kenneth Walker III"})
    assert got["RB1"][0]["name"] == "Emmett Johnson" and got["RB2"][0]["name"] == "Jaydn Ott"
    assert SS.without_out(d, set())["RB2"][0]["name"] == "Emmett Johnson"   # nobody out: unchanged
