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
