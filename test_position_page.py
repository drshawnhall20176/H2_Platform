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
    meta = [dict(order=wk, date=f"2026-09-{10 + wk}", home="D0" if wk % 2 else "OFF", away="OFF" if wk % 2 else "D0",
                 home_score=24, away_score=20) for wk in (1, 2, 3)]                                      # D0 is home in weeks 1 and 3 (wins) and away in week 2 (loses)
    return PD.build_bundle(sport, home, away, pgames, {home: {"WR1": [{"pid": "h1", "name": "HomeWr", "status": "Questionable"}]}}, h2h,
                           notes=["Based on 2026 games through week 4."], meta_games=meta)


def basketball_bundle(sport="NBA", home=1, away=2, ranked=True):
    """Guards and centers for teams 1..N across three dated games; team 1 and 2 are this game's sides."""
    pgames, meta = [], []
    teams = range(1, 13 if ranked else 3)
    for i, t in enumerate(teams):
        for d in (1, 2, 3):
            date = f"2026-10-0{d}T23:00Z"
            opp = 100 + t
            pgames.append(dict(game=f"{t}-{d}", order=date, team=opp, opp=t, pid=f"g{t}", name=f"Guard{t}", pos="PG",
                               stats=dict(min=30, pts=10 + 2 * t + d, reb=3, ast=4, fg3m=1)))
            pgames.append(dict(game=f"{t}-{d}", order=date, team=opp, opp=t, pid=f"c{t}", name=f"Big{t}", pos="C",
                               stats=dict(min=25, pts=6, reb=9, ast=1, fg3m=0)))
            meta.append(dict(order=date, date=date, home=t if d != 2 else opp, away=opp if d != 2 else t, home_score=110, away_score=100))
    names = {t: f"Team {t}" for t in teams}
    names.update({100 + t: f"Opp {t}" for t in teams})
    return PD.build_bundle(sport, home, away, pgames, {}, [], names=names, meta_games=meta)


def games(slots=("2026-10-11T17:00:00Z",)):
    return [dict(label=f"AWAY{i} @ HOME{i}", home=f"HOME{i}", away=f"AWAY{i}", home_id=f"HOME{i}", away_id=f"AWAY{i}",
                 home_abbr=f"HOME{i}", away_abbr=f"AWAY{i}", game_date=iso) for i, iso in enumerate(slots)]


@pytest.fixture
def page(monkeypatch):
    calls = {"bundle": []}

    def run(sport="NFL", glist=None, ranked=True, session=None, bundle_fn=None):
        import streamlit as st
        st.cache_data.clear()                                          # the page caches by (sport, date, game)
        monkeypatch.setattr(PD, "list_games", lambda s, d: list(glist if glist is not None else games()))

        def fake_bundle(sport_key, date_str, game, use_previous=False):
            calls["bundle"].append((sport_key, game["label"], use_previous))
            if bundle_fn is not None:
                return bundle_fn(sport_key, game)
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
    assert len(frames) == 5                                               # two position tables + the game log and its average + the meetings table
    home_tbl = [f for f in frames if "Starter" in f.columns and any("HomeWr" in s for s in f["Starter"])]
    assert len(home_tbl) == 1 and "HomeWr 🚫 Questionable"[:6] in " ".join(home_tbl[0]["Starter"]) and "⚠️ Questionable" in " ".join(home_tbl[0]["Starter"])
    wr = home_tbl[0][home_tbl[0]["Slot"] == "WR1"].iloc[0]
    assert wr["D rank (1 = softest)"].endswith("/13") or wr["D rank (1 = softest)"].endswith("/12") or "/" in wr["D rank (1 = softest)"]
    assert "HOME0 lead the series 1–0" in t
    assert [m.label for m in at.metric][-4:] == ["Meetings", "HOME0 wins", "AWAY0 wins", "Avg total"]


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
    at.text_input(key="pm_find").set_value("zzz").run()                  # a fresh handle: the earlier one belongs to the previous run's tree
    assert any("No games match" in i.value for i in at.info)


# ------------------------------------------------------------------ registration
def test_the_page_is_registered_for_its_four_sports_and_owner_only():
    src = (Path(__file__).parent / "streamlit_app.py").read_text()
    assert '"38": ("NFL", "NCAAF", "NBA", "NCAAMB")' in src
    assert '"38": ("Position Matchups", "🧭", "position_matchups")' in src
    assert re.search(r'for k in \("7".*?"38"\):\s*\n\s*SECTION_OF\[k\] = "🔬 DEEP RESEARCH"', src, re.DOTALL)
    assert '"Position Matchups"}' in src.split("owner_only_titles = {")[1].split("}")[0] + "}"
    assert (Path(__file__).parent / "views" / "38_Position_Matchups.py").exists()


# ------------------------------------------------------------------ the position-vs-defense game log
def pick(at, label):
    return [s for s in at.selectbox if s.label == label][0]


def log_frames(at):
    """(game log table, its average row) — the two frames right after the two position tables."""
    frames = [d.value for d in at.dataframe]
    i = [k for k, f in enumerate(frames) if "Opponent" in f.columns and "W/L" in f.columns][0]
    return frames[i], frames[i + 1]


def test_game_log_defaults_to_the_home_defense_first_position(page):
    at = page("NFL")
    assert not at.exception, [e.value for e in at.exception]
    assert "📋 Game log — a position against one defense" in texts(at) and "QBs vs HOME0 defense" in texts(at)
    pos, d = pick(at, "Position"), pick(at, "Defense")
    assert pos.options[0] == "QB — Quarterback" and len(pos.options) == len(PM.FOOTBALL_SLOTS)
    assert d.options[:2] == ["HOME0  ★ this game", "AWAY0  ★ this game"] and "D3" in d.options and d.value == "HOME0"


def test_game_log_shows_a_position_in_each_game_with_colour_ready_numbers_and_an_average(page):
    at = page("NFL")
    pick(at, "Position").set_value("WR1 — Wide receiver 1").run()
    pick(at, "Defense").set_value("D3").run()
    assert "WR1s vs D3 defense" in texts(at)
    table, avg = log_frames(at)
    assert list(table.columns) == ["Date", "Opponent", "W/L", "Score", "Player", "rec", "rec yds", "rec TD", "Fantasy pts"]
    assert list(table["Date"]) == ["Wk 3", "Wk 2", "Wk 1"] and list(table["Player"]) == ["Rec3"] * 3
    assert list(table["rec yds"]) == [60.0] * 3 and avg.iloc[0]["rec yds"] == "60.0" and avg.iloc[0]["Average"] == "3 game(s)"


def test_game_log_knows_venue_and_result_when_the_schedule_does(page):
    at = page("NFL")
    pick(at, "Position").set_value("WR1 — Wide receiver 1").run()
    pick(at, "Defense").set_value("D0").run()
    table, _ = log_frames(at)                                                       # D0 also faced HOME's own offense, which the schedule doesn't list
    known = table[table["Opponent"].str.endswith("OFF")]
    assert list(known["W/L"]) == ["W", "L", "W"] and list(known["Opponent"]) == ["vs OFF", "at OFF", "vs OFF"] and known.iloc[0]["Score"] == "24-20"
    assert known.iloc[1]["Date"] == "Wk 2 · 09/12/26"
    at.radio(key="pm_log_venue").set_value("Away").run()
    table, avg = log_frames(at)
    assert len(table) == 1 and table.iloc[0]["Opponent"] == "at OFF" and avg.iloc[0]["Average"] == "1 game(s)"


def test_game_log_window_size_limits_rows(page):
    at = page("NFL")
    pick(at, "Position").set_value("WR1 — Wide receiver 1").run()
    pick(at, "Defense").set_value("D3").run()
    at.selectbox(key="pm_log_n").set_value("Last 5").run()
    assert len(log_frames(at)[0]) == 3                                              # only three games exist
    assert at.selectbox(key="pm_log_n").options == ["Last 5", "Last 10", "Last 16", "All sampled"]


def test_game_log_with_no_games_for_the_filter_says_so(page):
    at = page("NFL")
    pick(at, "Defense").set_value("D5").run()
    at.radio(key="pm_log_venue").set_value("Home").run()                           # D5 has no schedule rows, so no known home games
    assert not at.exception and any("No home games for D5" in i.value and "venue unknown" in i.value for i in at.info)


def test_game_log_hit_rate_uses_the_chosen_stat_and_line(page):
    at = page("NFL")
    pick(at, "Position").set_value("WR1 — Wide receiver 1").run()
    pick(at, "Defense").set_value("D3").run()
    assert pick(at, "Hit rate on").options == ["rec", "rec yds", "rec TD", "Fantasy pts"]
    pick(at, "Hit rate on").set_value("rec yds").run()
    line = [n for n in at.number_input if n.label == "Line"][0]
    assert line.value == 60.0                                                       # starts at the sample's own average
    line.set_value(59.5).run()
    m = [m for m in at.metric if m.label.startswith("Over")][0]
    assert m.label == "Over 59.5 rec yds" and m.value == "3/3  (100%)"
    [n for n in at.number_input if n.label == "Line"][0].set_value(60.0).run()
    assert [m for m in at.metric if m.label.startswith("Over")][0].value == "0/3  (0%)"      # exactly on the line is not a hit


def test_game_log_follows_the_game_and_resets_the_defense_when_the_game_changes(page):
    at = page("NFL", games(["2026-10-11T17:00:00Z", "2026-10-11T20:25:00Z"]))
    pick(at, "Defense").set_value("D3").run()
    at.selectbox(key="pm_game").select_index(1).run()
    assert not at.exception and pick(at, "Defense").options[0] == "HOME1  ★ this game" and "QBs vs HOME1 defense" in texts(at)


def test_game_log_for_basketball_shows_groups_dates_and_venue(page):
    gl = [dict(label="Team 2 @ Team 1", home="Team 1", away="Team 2", home_id=1, away_id=2, home_abbr="T1", away_abbr="T2", game_date="2026-10-08T23:00:00Z")]
    at = page("NBA", gl, bundle_fn=lambda sport, g: basketball_bundle(sport))
    assert not at.exception, [e.value for e in at.exception]
    assert pick(at, "Position").options == ["G — Guards", "F — Forwards", "C — Centers"] and "Guards" not in pick(at, "Position").value[:2]
    assert pick(at, "Defense").options[:2] == ["Team 1  ★ this game", "Team 2  ★ this game"]
    table, avg = log_frames(at)
    assert list(table.columns) == ["Date", "Opponent", "W/L", "Score", "Player", "pts", "reb", "ast", "3PM", "PRA"]
    assert list(table["Date"]) == ["10/03/26", "10/02/26", "10/01/26"] and list(table["Player"]) == ["Guard1"] * 3
    assert list(table["Opponent"]) == ["vs Opp 1", "at Opp 1", "vs Opp 1"] and list(table["W/L"]) == ["W", "L", "W"]
    assert "Basketball rows are the whole position group" in texts(at)


def test_ncaamb_game_log_offers_only_the_two_teams(page):
    gl = [dict(label="Two @ One", home="One", away="Two", home_id=1, away_id=2, home_abbr=None, away_abbr=None, game_date="2026-12-01T01:00:00Z")]
    at = page("NCAAMB", gl, bundle_fn=lambda sport, g: basketball_bundle(sport, ranked=True))
    assert pick(at, "Defense").options == ["Team 1  ★ this game", "Team 2  ★ this game"]


def test_game_log_with_nothing_sampled_says_so(page):
    empty = lambda sport, g: PD.build_bundle(sport, g["home"], g["away"], [], {}, [])
    at = page("NFL", bundle_fn=empty)
    assert not at.exception and "No defense has games in the sample yet" in texts(at)


def test_game_log_colours_every_stat_column_and_the_headline(page, monkeypatch):
    seen = []
    real = PM.heat_css
    monkeypatch.setattr(PM, "heat_css", lambda values: seen.append(list(values)) or real(values))
    at = page("NFL")
    pick(at, "Position").set_value("WR1 — Wide receiver 1").run()
    pick(at, "Defense").set_value("D3").run()
    assert not at.exception
    assert seen[-4:] == [[6.0] * 3, [60.0] * 3, [0.0] * 3, [12.0] * 3]               # rec, rec yds, rec TD, Fantasy pts — one call per numeric column


def test_game_log_controls_start_on_all_games_last_ten(page):
    at = page("NFL")
    assert at.selectbox(key="pm_log_n").value == "Last 10" and at.radio(key="pm_log_venue").value == "All"
    assert at.radio(key="pm_log_venue").options == ["All", "Home", "Away"]
