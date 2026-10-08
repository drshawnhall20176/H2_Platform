"""AppTest coverage for views/38_Position_Matchups.py (loaders replaced with synthetic data)."""
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import position_data as PD
import position_matchups as PM

PAGE = str(Path(__file__).parent / "views" / "38_Position_Matchups.py")


def synthetic_bundle(sport="NFL", home="HOME", away="AWAY", ranked=True):
    pgames = []
    n = 12 if ranked else 3
    for i in range(n):
        for wk in (1, 2, 3):
            pgames.append(dict(game=f"{i}-{wk}", order=wk, team="OFF", opp=f"D{i}", pid=f"o{i}", name=f"Rec{i}", pos="WR",
                               stats=dict(tgt=6, rec=3 + i, rec_yds=30 + 10 * i)))
    for wk in (1, 2, 3):
        pgames.append(dict(game=f"h{wk}", order=wk, team=home, opp="D0", pid="h1", name="HomeWr", pos="WR", stats=dict(tgt=9, rec=7, rec_yds=90)))
        pgames.append(dict(game=f"v{wk}", order=wk, team="OFF2", opp=home, pid="r1", name="Rival", pos="WR", stats=dict(tgt=9, rec=9, rec_yds=140, rec_td=1)))
        pgames.append(dict(game=f"w{wk}", order=wk, team="OFF2", opp=away, pid="r1", name="Rival", pos="WR", stats=dict(tgt=4, rec=1, rec_yds=8)))
        pgames.append(dict(game=f"a{wk}", order=wk, team=away, opp="D1", pid="a1", name="AwayWr", pos="WR", stats=dict(tgt=8, rec=5, rec_yds=60)))
    h2h = [dict(date="2025-10-01", home=home, away=away, home_score=27, away_score=20, season=2025)]
    return PD.build_bundle(sport, home, away, pgames, {home: {"WR1": [{"pid": "h1", "name": "HomeWr", "status": "Questionable"}]}}, h2h,
                           notes=["Based on 2026 games through week 4."])


def games(slots=("2026-10-11T17:00:00Z",)):
    return [dict(label=f"AWAY{i} @ HOME{i}", home=f"HOME{i}", away=f"AWAY{i}", home_id=f"HOME{i}", away_id=f"AWAY{i}",
                 home_abbr=f"HOME{i}", away_abbr=f"AWAY{i}", game_date=iso) for i, iso in enumerate(slots)]


@pytest.fixture
def page(monkeypatch):
    calls = {"bundle": []}

    def run(sport="NFL", glist=None, ranked=True, session=None):
        import streamlit as st
        st.cache_data.clear()                                          # the page caches by (sport, date, game)
        monkeypatch.setattr(PD, "list_games", lambda s, d: list(glist if glist is not None else games()))

        def fake_bundle(sport_key, date_str, game, use_previous=False):
            calls["bundle"].append((sport_key, game["label"], use_previous))
            return synthetic_bundle(sport_key, game["home"], game["away"], ranked)
        monkeypatch.setattr(PD, "load_bundle", fake_bundle)
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.session_state["sport"] = sport
        for k, v in (session or {}).items():
            at.session_state[k] = v
        at.run()
        return at
    run.calls = calls
    return run


def texts(at):
    return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption] + [i.value for i in at.info])


def test_nfl_page_shows_both_directions_targets_and_fades_and_the_h2h(page):
    at = page("NFL")
    assert not at.exception, [e.value for e in at.exception]
    t = texts(at)
    assert "AWAY0 offense  vs  HOME0 defense" in t and "HOME0 offense  vs  AWAY0 defense" in t
    assert "🟢 Targets" in t and "🔴 Fades" in t and "Based on 2026 games through week 4." in t
    assert "PPR-style fantasy points" in t and "usage, not just the depth-chart label" in t
    frames = [d.value for d in at.dataframe]
    assert len(frames) == 3                                               # two position tables + the meetings table
    home_tbl = [f for f in frames if "Starter" in f.columns and any("HomeWr" in s for s in f["Starter"])]
    assert len(home_tbl) == 1 and "HomeWr 🚫 Questionable"[:6] in " ".join(home_tbl[0]["Starter"]) and "⚠️ Questionable" in " ".join(home_tbl[0]["Starter"])
    wr = home_tbl[0][home_tbl[0]["Slot"] == "WR1"].iloc[0]
    assert wr["D rank (1 = softest)"].endswith("/13") or wr["D rank (1 = softest)"].endswith("/12") or "/" in wr["D rank (1 = softest)"]
    assert "HOME0 lead the series 1–0" in t
    assert [m.label for m in at.metric] == ["Meetings", "HOME0 wins", "AWAY0 wins", "Avg total"]


def test_time_slot_filter_narrows_the_game_list(page):
    gl = games(["2026-10-11T17:00:00Z", "2026-10-12T00:20:00Z"])                # 1:00 PM ET and 8:20 PM ET
    at = page("NFL", gl)
    slots = at.selectbox(key="pm_slot")
    assert slots.options[0] == "All slate" and set(slots.options[1:]) == {"Afternoon", "Late"}
    assert len(at.selectbox(key="pm_game").options) == 2
    slots.set_value("Late").run()
    assert len(at.selectbox(key="pm_game").options) == 1 and "AWAY1 @ HOME1" in at.selectbox(key="pm_game").options[0]
    assert at.selectbox(key="pm_game").value.endswith("AWAY1 @ HOME1") and page.calls["bundle"][-1][1] == "AWAY1 @ HOME1"


def test_picking_another_game_loads_that_games_bundle(page):
    at = page("NFL", games(["2026-10-11T17:00:00Z", "2026-10-11T20:25:00Z"]))
    at.selectbox(key="pm_game").select_index(1).run()
    assert page.calls["bundle"][-1][1] == "AWAY1 @ HOME1" and "AWAY1 offense  vs  HOME1 defense" in texts(at)


def test_season_option_is_football_only_and_is_passed_through(page):
    at = page("NFL")
    box = [s for s in at.selectbox if s.label == "Defense data"][0]
    assert box.value == "This season so far" and page.calls["bundle"][-1][2] is False
    box.set_value("Last season (full)").run()
    assert page.calls["bundle"][-1][2] is True
    nba = page("NBA")
    assert not [s for s in nba.selectbox if s.label == "Defense data"]


def test_not_enough_defenses_to_rank_says_so_for_football(page):
    at = page("NFL", ranked=False)
    assert not at.exception and "Not enough games yet to rank the defenses" in texts(at)
    assert not [m for m in at.markdown if m.value == "**🟢 Targets**"]


def test_ncaamb_without_ranks_explains_why(page):
    at = page("NCAAMB", ranked=False)
    assert not at.exception and "without a league rank" in texts(at)


def test_no_games_shows_the_friendly_message(page):
    at = page("NFL", glist=[])
    assert not at.exception and any("games found for" in i.value for i in at.info) and not at.dataframe


def test_unsupported_sport_is_gated(page):
    at = page("MLB")
    assert not at.exception and not at.dataframe


def test_loader_failure_degrades_to_a_warning(monkeypatch, page):
    import streamlit as st
    st.cache_data.clear()
    monkeypatch.setattr(PD, "list_games", lambda s, d: games())

    def boom(*a, **k):
        raise RuntimeError("feed down")
    monkeypatch.setattr(PD, "load_bundle", boom)
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception and any("Couldn't build this matchup" in w.value for w in at.warning)


def test_long_slates_get_a_team_search(page):
    many = [dict(label=f"Away{i} @ Home{i}", home=f"Home{i}", away=f"Away{i}", home_id=i, away_id=1000 + i, home_abbr=None, away_abbr=None,
                 game_date="2026-12-01T01:00:00Z") for i in range(30)]
    at = page("NCAAMB", many, ranked=False)
    find = at.text_input(key="pm_find")
    find.set_value("home7").run()
    assert at.selectbox(key="pm_game").options and len(at.selectbox(key="pm_game").options) == 1
    find.set_value("zzz").run()
    assert any("No games match" in i.value for i in at.info)


# ------------------------------------------------------------------ registration
def test_the_page_is_registered_for_its_four_sports_and_owner_only():
    src = (Path(__file__).parent / "streamlit_app.py").read_text()
    assert '"38": ("NFL", "NCAAF", "NBA", "NCAAMB")' in src
    assert '"38": ("Position Matchups", "🧭", "position_matchups")' in src
    assert re.search(r'for k in \("7".*?"38"\):\s*\n\s*SECTION_OF\[k\] = "🔬 DEEP RESEARCH"', src, re.DOTALL)
    assert '"Position Matchups"}' in src.split("owner_only_titles = {")[1].split("}")[0] + "}"
    assert (Path(__file__).parent / "views" / "38_Position_Matchups.py").exists()
