"""AppTest coverage for views/38_Position_Matchups.py (loaders replaced with synthetic data)."""
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import position_data as PD
import position_lines as PL
import position_matchups as PM
import position_pbp as PP

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


def fake_nfl_log(with_pbp=True):
    """Stand-in for PD.load_nfl_log: twelve ordinary defenses plus HOME0, a defense with four varied games
    (venue / kickoff / roof / spread / result differ), a regular-defender list and two games with defenders out."""
    pgames, lookup, games_meta = [], {}, []

    def add(order, team, opp, pid, name, tgt, rec, yds, long_, td=0):
        pgames.append(dict(game=f"{order}-{team}", order=order, team=team, opp=opp, pid=pid, name=name, pos="WR",
                           stats=dict(tgt=tgt, rec=rec, rec_yds=yds, rec_td=td)))
        full = dict({k: 0.0 for k in PP.STAT_KEYS}, tgt=tgt, rec=rec, rec_yds=yds, rec_long=long_, td=td, atd=1.0 if td else 0.0,
                    tgt_share=25.0)
        half = dict(full, tgt=tgt / 2, rec=rec / 2, rec_yds=yds / 2, rec_long=long_ / 2)
        lookup[(order, team, pid)] = {"Full Game": full, "1st Half": half, "2nd Half": dict(full, rec_yds=yds - yds / 2)}

    for i in range(12):
        for wk in (1, 2, 3):
            add(202600 + wk, "OFF", f"D{i}", f"o{i}", f"Rec{i}", 6, 3 + i, 30 + 10 * i, 20 + i)
    homes = [  # order, offense, kickoff, roof, spread (home team's expected margin), home score, away score, HOME0 is home?
        (202601, "OFF1", "20:15", "dome", 3.0, 24, 20, True), (202602, "OFF2", "13:00", "outdoors", 3.0, 27, 20, False),
        (202603, "AWAY0", "13:00", "outdoors", -2.5, 21, 17, True), (202604, "OFF4", "20:20", "outdoors", -1.0, 10, 14, False)]
    for order, off, tm, roof, spread, hs, as_, is_home in homes:
        wk = order % 100
        add(order, off, "HOME0", f"s{wk}", f"Star{wk}", 8, 5, 50 + 10 * wk, 20 + wk, td=1 if wk == 2 else 0)
        h, a = ("HOME0", off) if is_home else (off, "HOME0")
        games_meta.append(dict(order=order, date=f"2026-09-{10 + wk}", home=h, away=a, home_score=hs, away_score=as_, time=tm,
                               spread=spread, roof=roof, total=44.5))
    for wk in (1, 2, 3):                                                  # AWAY0 also has a defensive record (it is one of the game's two sides)
        add(202600 + wk, "OFF", "AWAY0", "oa", "RecA", 7, 4, 55, 22)
    allowed = PM.allowed_by_slot(pgames, "NFL")
    allowed_chart = {}
    if with_pbp:
        PM.attach_periods(allowed, lookup)
        lookup[(202601, "OFF1", "c1")] = {"Full Game": dict({k: 0.0 for k in PP.STAT_KEYS}, tgt=3, rec=2, rec_yds=20, rec_long=15, tgt_share=10.0)}
        allowed_chart = PM.chart_allowed(allowed, {(202601, "OFF1"): {"WR1": ("c1", "ChartGuy")}}, lookup)
    teams = {"HOME0", "AWAY0", "OFF", "OFF1", "OFF2", "OFF4"} | {f"D{i}" for i in range(12)}
    return {"allowed": allowed, "allowed_chart": allowed_chart, "meta": PM.build_game_meta(games_meta),
            "all_names": {t: f"{t} FC" for t in teams},
            "logos": {"OFF1": "https://x.test/off1.png"}, "headshots": {"s1": "https://x.test/s1.png"},
            "absences": {(202602, "HOME0"): ["Star D"], (202603, "HOME0"): ["Star D", "Edge R"]},
            "regulars": {"HOME0": [{"name": "Star D", "avg_pct": 0.9, "games": 4}, {"name": "Edge R", "avg_pct": 0.7, "games": 4}]},
            "notes": ["Fake note about the sample."], "season": 2026, "week": 5, "has_pbp": with_pbp}


def games(slots=("2026-10-11T17:00:00Z",)):
    return [dict(label=f"AWAY{i} @ HOME{i}", home=f"HOME{i}", away=f"AWAY{i}", home_id=f"HOME{i}", away_id=f"AWAY{i}",
                 home_abbr=f"HOME{i}", away_abbr=f"AWAY{i}", game_date=iso) for i, iso in enumerate(slots)]


@pytest.fixture
def page(monkeypatch):
    calls = {"bundle": []}

    def run(sport="NFL", glist=None, ranked=True, session=None, bundle_fn=None, nfl_log=None):
        import streamlit as st
        st.cache_data.clear()                                          # the page caches by (sport, date, game)
        monkeypatch.setattr(PD, "load_nfl_log", lambda d: (nfl_log if nfl_log is not None else fake_nfl_log()))
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
    assert len(frames) == 3                                               # two position tables + the meetings table (the game log is an HTML table)
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


def log_html(at):
    found = [m.value for m in at.markdown if 'class="pmlog"' in m.value]
    assert len(found) == 1, f"expected one game-log table, found {len(found)}"
    return found[0]


def cells(row_html):
    import html as _html
    return [" ".join(_html.unescape(re.sub(r"<[^>]+>", " ", c)).split()) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.S)]


def log_rows(at):
    """(header cells, body rows, footer rows) of the game-log table, as plain text."""
    h = log_html(at)
    section = lambda tag: re.findall(r"<tr[^>]*>.*?</tr>", re.search(rf"<{tag}>(.*?)</{tag}>", h, re.S).group(1), re.S)
    return cells(section("thead")[0]), [cells(r) for r in section("tbody")], [cells(r) for r in section("tfoot")]


def to_wr1(at, defense="HOME0 FC  ★ this game"):
    pick(at, "Position").set_value("WR1 — Wide receiver 1").run()
    if defense != "HOME0 FC  ★ this game":
        pick(at, "Defense").set_value(defense).run()
    return at


def test_game_log_defaults_to_the_home_defense_and_lists_every_filter(page):
    at = page("NFL")
    assert not at.exception, [e.value for e in at.exception]
    assert "📋 Game log — a position against one defense" in texts(at) and "QBs vs HOME0 FC defense** · Full Game" in texts(at)
    pos, d = pick(at, "Position"), pick(at, "Defense")
    assert pos.options[0] == "QB — Quarterback" and len(pos.options) == len(PM.FOOTBALL_SLOTS)
    assert d.options[:2] == ["HOME0 FC  ★ this game", "AWAY0 FC  ★ this game"] and "D3 FC" in d.options and d.value == "HOME0"
    assert pick(at, "Part of the game").options == list(PM.GAME_PERIODS) and pick(at, "Stadium").options == ["All", "Indoors", "Outdoors"]
    assert pick(at, "Defense was").options == ["All", "Favorite", "Underdog"] and at.checkbox(key="pm_log_prime").value is False
    assert "ℹ️ Fake note about the sample." in texts(at)


def test_wr_log_has_the_doink_columns_newest_first_with_logo_headshot_and_result(page):
    at = to_wr1(page("NFL"))
    head, body, foot = log_rows(at)
    assert head == ["DATE", "OPPONENT", "W/L", "PLAYER", "TD", "TGT SHARE", "REC TGT", "REC", "REC YDS", "REC LONG", "FANTASY PTS"]
    assert [r[0] for r in body] == ["Wk 4 · 09/14/26", "Wk 3 · 09/13/26", "Wk 2 · 09/12/26", "Wk 1 · 09/11/26"]
    assert body[0][1:] == ["at OFF4 FC", "W 14-10", "Star4", "0", "25%", "8", "5", "90", "24", "14.0"]
    wk1, wk2 = body[3], body[2]
    assert wk1[1] == "vs OFF1 FC" and wk1[2] == "W 24-20" and wk2[1] == "at OFF2 FC" and wk2[2] == "L 20-27" and wk2[4] == "1"
    assert body[1][2] == "W 21-17"
    h = log_html(at)
    assert 'src="https://x.test/off1.png"' in h and 'src="https://x.test/s1.png"' in h and "rgba(" in h               # logo, headshot, shading
    assert len(foot) == 1 and foot[0][0].startswith("AVG (4 games)")                                               # no book lines loaded yet
    assert "HIT RATE" not in h


def test_period_selector_switches_to_the_halves(page):
    at = to_wr1(page("NFL"))
    pick(at, "Part of the game").set_value("1st Half").run()
    _, body, _ = log_rows(at)
    assert "QBs" not in texts(at) and "WR1s vs HOME0 FC defense** · 1st Half" in texts(at)
    assert [r[8] for r in body][::-1] == ["30", "35", "40", "45"] and [r[6] for r in body] == ["4"] * 4          # half the yards of each game
    pick(at, "Part of the game").set_value("Q3").run()
    assert [r[8] for r in log_rows(at)[1]] == ["0"] * 4                                                          # no Q3 line in the data: zeros, not full-game numbers


def test_without_play_by_play_the_period_picker_is_off_and_totals_still_show(page):
    at = to_wr1(page("NFL", nfl_log=fake_nfl_log(with_pbp=False)))
    assert pick(at, "Part of the game").disabled is True
    head, body, _ = log_rows(at)
    assert "REC LONG" not in head and "TGT SHARE" not in head and "REC YDS" in head and len(body) == 4           # weekly stats have no longs or shares
    assert not any("Half and quarter splits" in i.value for i in at.info)
    stale = to_wr1(page("NFL", nfl_log=fake_nfl_log(with_pbp=False), session={"pm_log_period": "1st Half"}))      # a half picked before the data went away
    assert any("Half and quarter splits need play-by-play" in i.value for i in stale.info) and len(log_rows(stale)[1]) == 4


def test_venue_primetime_stadium_and_role_filters(page):
    at = to_wr1(page("NFL"))
    at.radio(key="pm_log_venue").set_value("Home").run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 3", "Wk 1"]
    at.radio(key="pm_log_venue").set_value("All").run()
    at.checkbox(key="pm_log_prime").set_value(True).run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 4", "Wk 1"]                                              # the two 8 PM kickoffs
    at.checkbox(key="pm_log_prime").set_value(False).run()
    pick(at, "Stadium").set_value("Indoors").run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 1"]
    pick(at, "Stadium").set_value("Outdoors").run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 4", "Wk 3", "Wk 2"]
    pick(at, "Defense was").set_value("Favorite").run()                                                         # wk4 away with the home side a 1-pt dog; wk3 home a 2.5-pt dog -> not favoured
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 4"]
    pick(at, "Defense was").set_value("Underdog").run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 3", "Wk 2"]


def test_only_vs_the_opponent_and_without_defenders_filters(page):
    at = to_wr1(page("NFL"))
    assert at.checkbox(key="pm_log_only_opp").label == "Only vs AWAY0 FC"
    at.checkbox(key="pm_log_only_opp").set_value(True).run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 3"]
    at.checkbox(key="pm_log_only_opp").set_value(False).run()
    ms = [m for m in at.multiselect if m.label.startswith("Without these defenders")][0]
    assert ms.options == ["Star D", "Edge R"]
    ms.set_value(["Star D"]).run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 3", "Wk 2"]
    [m for m in at.multiselect if m.label.startswith("Without these defenders")][0].set_value(["Star D", "Edge R"]).run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 3"]                                                       # both had to sit out
    pick(at, "Defense").set_value("D3 FC").run()


def test_a_defense_outside_this_game_has_no_only_vs_box(page):
    at = to_wr1(page("NFL"), defense="D3 FC")
    assert not [c for c in at.checkbox if c.key == "pm_log_only_opp"] and not [m for m in at.multiselect if m.label.startswith("Without")]
    assert len(log_rows(at)[1]) == 3 and log_rows(at)[1][0][3] == "Rec3"


def test_stat_range_filter_keeps_games_inside_the_range(page):
    at = to_wr1(page("NFL"))
    [s for s in at.selectbox if s.label == "Filter by a stat"][0].set_value("REC YDS").run()
    lo = [n for n in at.number_input if n.label == "Min"][0]
    lo.set_value(75.0).run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 4", "Wk 3"]                                               # 90 and 80 yards; 70 and 60 drop out
    [n for n in at.number_input if n.label == "Max"][0].set_value(85.0).run()
    assert [r[0][:4] for r in log_rows(at)[1]] == ["Wk 3"]
    [n for n in at.number_input if n.label == "Min"][0].set_value(500.0).run()
    assert any("No games for HOME0 FC match those filters" in i.value for i in at.info)


def test_game_log_window_size_limits_rows(page):
    at = to_wr1(page("NFL"))
    at.selectbox(key="pm_log_n").set_value("Last 5").run()
    assert len(log_rows(at)[1]) == 4 and at.selectbox(key="pm_log_n").options == ["Last 5", "Last 10", "Last 16", "All sampled"]
    assert at.selectbox(key="pm_log_n").value == "Last 5"


def test_game_log_controls_start_on_last_ten_all_venues(page):
    at = page("NFL")
    assert at.selectbox(key="pm_log_n").value == "Last 10" and at.radio(key="pm_log_venue").value == "All"
    assert at.radio(key="pm_log_venue").options == ["All", "Home", "Away"]


def test_game_log_follows_the_game_and_resets_the_defense_when_the_game_changes(page):
    at = page("NFL", games(["2026-10-11T17:00:00Z", "2026-10-11T20:25:00Z"]))
    pick(at, "Defense").set_value("D3").run()
    at.selectbox(key="pm_game").select_index(1).run()                          # HOME1 / AWAY1 have no games in the log data, so the list starts without a ★ pair
    assert not at.exception and not any("★" in o for o in pick(at, "Defense").options)
    assert pick(at, "Defense").value == "AWAY0" and f"QBs vs {pick(at, 'Defense').options[0].strip()} defense** · Full Game" in texts(at)


def test_nothing_in_the_nfl_log_says_so(page):
    empty = {"allowed": {}, "meta": {}, "all_names": {}, "logos": {}, "headshots": {}, "absences": {}, "regulars": {}, "notes": [],
             "season": 2026, "week": 5, "has_pbp": False}
    at = page("NFL", nfl_log=empty)
    assert not at.exception and "No defense has games in the sample yet" in texts(at)


def test_a_failed_nfl_log_load_degrades_to_a_warning(monkeypatch, page):
    at = page("NFL")
    monkeypatch.setattr(PD, "load_nfl_log", lambda d: (_ for _ in ()).throw(RuntimeError("feed down")))
    import streamlit as st
    st.cache_data.clear()
    at.run()
    assert not at.exception and any("Couldn't load the NFL game-log data (RuntimeError)" in w.value for w in at.warning)
    assert len(at.dataframe) == 3                                                                                # the rest of the page still renders


def test_manual_hit_rate_tool_uses_the_chosen_stat_and_line(page):
    at = to_wr1(page("NFL"))
    assert pick(at, "Test your own line on").options == ["TD", "TGT SHARE", "REC TGT", "REC", "REC YDS", "REC LONG", "Fantasy pts"]
    pick(at, "Test your own line on").set_value("REC YDS").run()
    line = [n for n in at.number_input if n.label == "Line"][0]
    assert line.value == 75.0                                                                                     # the sample average (75), rounded to .5
    line.set_value(69.5).run()
    m = [m for m in at.metric if m.label.startswith("Over")][0]
    assert m.label == "Over 69.5 REC YDS" and m.value == "3/4  (75%)"
    [n for n in at.number_input if n.label == "Line"][0].set_value(80.0).run()
    assert [m for m in at.metric if m.label.startswith("Over")][0].value == "1/4  (25%)"                           # exactly on the line is not a hit


# ------------------------------------------------------------------ book lines (Best lines / hit rate rows)
def offers_for(player="AwayWr", market="player_reception_yds", point=60.5):
    return [dict(market=market, player=player, point=point, over={"fanduel": -115, "draftkings": -110}, under={"fanduel": -105, "draftkings": -110}),
            dict(market="player_anytime_td", player=player, point=0.5, over={"fanduel": 220, "draftkings": 240}, under={}),
            dict(market=market, player="Somebody Else", point=10.5, over={"fanduel": -110}, under={"fanduel": -110})]


@pytest.fixture
def lines(monkeypatch):
    import best_bets_data as BBD
    import odds_api as O
    state = {"events": [dict(id="ev1", home_team="HOME0 FC", away_team="AWAY0 FC")], "offers": offers_for(), "error": None, "markets": [], "key": "k"}
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: state["key"])
    monkeypatch.setattr(O, "fetch_events_all", lambda api_key, sport=None: state["events"])

    def fake_fetch(api_key, event, markets, sport):
        state["markets"].append((event["id"], list(markets), sport))
        return state["offers"], state["error"]
    monkeypatch.setattr(PL, "fetch_offers", fake_fetch)
    return state


def load_button(at):
    return [b for b in at.button if b.key == "pm_load_lines"][0]


def test_book_lines_button_offers_the_cost_and_loads_the_best_lines_and_hit_rates(page, lines):
    at = to_wr1(page("NFL"))
    assert "Load book lines" in load_button(at).label and "~" in load_button(at).label
    assert [s for s in at.selectbox if s.label.startswith("Book lines for")][0].options == ["AwayWr"]
    assert "HIT RATE" not in log_html(at) and not lines["markets"]                                              # nothing is fetched until the button is pressed
    load_button(at).click().run()
    assert lines["markets"] == [("ev1", ["player_anytime_td", "player_receptions", "player_reception_yds", "player_reception_longest"],
                                 "americanfootball_nfl")]
    _, body, foot = log_rows(at)
    labels = [f[0].split(" (")[0] for f in foot]
    assert labels == ["AVG", "HIT RATE", "LINE", "BEST OVER", "BEST UNDER"]
    ys = [f for f in foot if f[0].startswith("LINE")][0]
    head = log_rows(at)[0]
    assert ys[head.index("REC YDS") - 3] == "60.5" and ys[head.index("TD") - 3] == "0.5"
    over = [f for f in foot if f[0] == "BEST OVER"][0]
    assert over[head.index("REC YDS") - 3] == "-110 DraftKings" and over[head.index("TD") - 3] == "+240 DraftKings"
    assert [f for f in foot if f[0] == "BEST UNDER"][0][head.index("TD") - 3] == "—"                              # anytime TD is a yes-only market


def test_hit_rate_row_counts_games_over_the_posted_line(page, lines):
    at = to_wr1(page("NFL"))
    load_button(at).click().run()
    head, body, foot = log_rows(at)
    hit = [f for f in foot if f[0].startswith("HIT RATE")][0]
    # yards 90, 80, 70, 60 against 60.5: three overs; touchdowns 0, 1, 0, 0 against 0.5: one over
    assert hit[head.index("REC YDS") - 3] == "75% 3/4" and hit[head.index("TD") - 3] == "25% 1/4" and hit[head.index("REC TGT") - 3] == "—"


def test_book_lines_follow_the_chosen_defense_side_and_player(page, lines):
    at = to_wr1(page("NFL"), defense="AWAY0 FC  ★ this game")
    assert [s for s in at.selectbox if s.label.startswith("Book lines for")][0].label.startswith("Book lines for (HOME0 FC WR1)")
    other = to_wr1(page("NFL"), defense="D3 FC")
    assert not [b for b in other.button if b.key == "pm_load_lines"] and any("Book lines are available for the two teams" in c.value for c in other.caption)


def test_book_lines_problems_are_reported_not_raised(page, lines):
    lines["key"] = None
    at = to_wr1(page("NFL"))
    load_button(at).click().run()
    assert any("No Odds API key" in w.value for w in at.warning) and "HIT RATE" not in log_html(at)
    lines["key"], lines["events"] = "k", [dict(id="x", home_team="Other", away_team="Team")]
    at = to_wr1(page("NFL"))
    load_button(at).click().run()
    assert any("haven't listed this game yet" in w.value for w in at.warning)
    lines["events"], lines["error"], lines["offers"] = [dict(id="ev1", home_team="HOME0 FC", away_team="AWAY0 FC")], "HTTP 429 quota", []
    at = to_wr1(page("NFL"))
    load_button(at).click().run()
    assert any("HTTP 429 quota" in w.value for w in at.warning)
    lines["error"], lines["offers"] = None, offers_for(player="Someone New")
    at = to_wr1(page("NFL"))
    load_button(at).click().run()
    assert any("No posted lines for AwayWr yet" in c.value for c in at.caption) and "HIT RATE" not in log_html(at)


def test_listing_failure_is_reported(page, lines, monkeypatch):
    import odds_api as O
    monkeypatch.setattr(O, "fetch_events_all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    at = to_wr1(page("NFL"))
    load_button(at).click().run()
    assert any("Couldn't list the games at the books (RuntimeError)" in w.value for w in at.warning)


# ------------------------------------------------------------------ the log for the other sports
def test_basketball_log_shows_groups_dates_and_venue_without_nfl_only_filters(page):
    gl = [dict(label="Team 2 @ Team 1", home="Team 1", away="Team 2", home_id=1, away_id=2, home_abbr="T1", away_abbr="T2", game_date="2026-10-08T23:00:00Z")]
    at = page("NBA", gl, bundle_fn=lambda sport, g: basketball_bundle(sport))
    assert not at.exception, [e.value for e in at.exception]
    assert pick(at, "Position").options == ["G — Guards", "F — Forwards", "C — Centers"]
    assert pick(at, "Defense").options[:2] == ["Team 1  ★ this game", "Team 2  ★ this game"]
    assert not [s for s in at.selectbox if s.label == "Part of the game"] and not at.checkbox and not [b for b in at.button if b.key == "pm_load_lines"]
    head, body, foot = log_rows(at)
    assert head == ["DATE", "OPPONENT", "W/L", "PLAYER", "pts", "reb", "ast", "3PM", "PRA"]
    assert [r[0] for r in body] == ["10/03/26", "10/02/26", "10/01/26"] and [r[3] for r in body] == ["Guard1"] * 3
    assert [r[1] for r in body] == ["vs Opp 1", "at Opp 1", "vs Opp 1"] and [r[2][0] for r in body] == ["W", "L", "W"]
    assert "Basketball rows are the whole position group" in texts(at)
    assert foot[0][0].startswith("AVG (3 games)") and body[0][4].count(".") == 1                                  # basketball keeps decimals


def test_ncaamb_log_offers_only_the_two_teams(page):
    gl = [dict(label="Two @ One", home="One", away="Two", home_id=1, away_id=2, home_abbr=None, away_abbr=None, game_date="2026-12-01T01:00:00Z")]
    at = page("NCAAMB", gl, bundle_fn=lambda sport, g: basketball_bundle(sport, ranked=True))
    assert pick(at, "Defense").options == ["Team 1  ★ this game", "Team 2  ★ this game"]


def test_game_log_with_nothing_sampled_says_so_for_other_sports(page):
    empty = lambda sport, g: PD.build_bundle(sport, g["home"], g["away"], [], {}, [])
    at = page("NBA", bundle_fn=empty)
    assert not at.exception and "No defense has games in the sample yet" in texts(at)


def test_slot_defined_by_switches_between_usage_and_the_depth_chart(page):
    at = to_wr1(page("NFL"))
    sel = pick(at, "Slot defined by")
    assert sel.options == ["Usage", "Depth chart"] and sel.value == "Usage" and not sel.disabled
    assert log_rows(at)[1][3][3] == "Star1"                                                                       # week 1 by usage
    sel.set_value("Depth chart").run()
    body = log_rows(at)[1]
    assert [r[3] for r in body] == ["Star4", "Star3", "Star2", "ChartGuy"] and "by depth chart" in " ".join(m.value for m in at.markdown)
    assert body[3][-1] == "4.0"                                                                                   # ChartGuy: 2 rec + 2.0 yds-pts
    assert "listed there the day before" in " ".join(c.value for c in at.caption)
    pick(at, "Slot defined by").set_value("Usage").run()
    assert log_rows(at)[1][3][3] == "Star1" and "by depth chart" not in " ".join(m.value for m in at.markdown)


def test_slot_defined_by_is_disabled_when_no_depth_chart_data_loaded(page):
    log = fake_nfl_log()
    log["allowed_chart"] = {}
    at = to_wr1(page("NFL", nfl_log=log))
    sel = pick(at, "Slot defined by")
    assert sel.disabled and log_rows(at)[1][3][3] == "Star1"


def test_depth_chart_choice_survives_other_filters(page):
    at = to_wr1(page("NFL"))
    pick(at, "Slot defined by").set_value("Depth chart").run()
    pick(at, "Part of the game").set_value("1st Half").run()
    body = log_rows(at)[1]
    assert body[3][3] == "ChartGuy" and set(body[3][4:-1]) <= {"0", "0%"}                                          # he has no 1st-half play-by-play
    assert body[0][3] == "Star4" and body[0][4 + 3 - 1] != "0"                                                    # the others still show their first half
