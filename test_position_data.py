"""Tests for position_data.py — column mapping, depth charts, the basketball box-score sample, bundle assembly,
and the per-sport orchestration (engines faked, no network)."""
import pandas as pd
import pytest

import basketball_engine as BB
import position_data as PD
import position_matchups as PM
import sports


# ------------------------------------------------------------------ football mapping
def weekly_df(rows):
    base = dict(player_id="p", player_display_name="N", player_name="N", position="WR", team="A", opponent_team="B", week=1,
                attempts=0, passing_yards=0, passing_tds=0, passing_interceptions=0, carries=0, rushing_yards=0, rushing_tds=0,
                targets=0, receptions=0, receiving_yards=0, receiving_tds=0)
    return pd.DataFrame([dict(base, **r) for r in rows])


def test_nfl_pgames_maps_columns_filters_positions_and_stays_before_the_week():
    df = weekly_df([dict(player_id="1", position="WR", week=1, targets=8, receptions=5, receiving_yards=70, receiving_tds=1),
                    dict(player_id="2", position="QB", week=2, attempts=30, passing_yards=250, passing_tds=2),
                    dict(player_id="3", position="K", week=1), dict(player_id="4", position="WR", week=3, targets=9),   # week 3 is not before 3
                    dict(player_id="5", position="DE", week=1), dict(player_id="6", position="WR", week=1, opponent_team=None)])
    out = PD.nfl_pgames(df, before_week=3)
    assert [p["pid"] for p in out] == ["1", "2"]
    wr = out[0]
    assert wr["stats"]["tgt"] == 8 and wr["stats"]["rec_yds"] == 70 and wr["stats"]["rec_td"] == 1 and wr["order"] == 1
    assert out[1]["stats"]["pass_att"] == 30 and out[1]["stats"]["pass_td"] == 2
    assert PD.nfl_pgames(None, 5) == [] and PD.nfl_pgames(pd.DataFrame(), 5) == []


def test_ncaaf_pgames_uses_roster_positions_and_the_season():
    rows = [dict(season=2026, week=2, game_id=9, team="Ohio", opponent_team="Iowa", player_id=11, player="Rec", receiving_REC=6, receiving_YDS=90, receiving_TD=1),
            dict(season=2025, week=2, game_id=8, team="Ohio", opponent_team="Iowa", player_id=11, player="Rec", receiving_REC=1),
            dict(season=2026, week=6, game_id=7, team="Ohio", opponent_team="Iowa", player_id=11, player="Rec", receiving_REC=2),
            dict(season=2026, week=2, game_id=9, team="Ohio", opponent_team="Iowa", player_id=12, player="Nopos", receiving_REC=2),
            dict(season=2026, week=1, game_id=6, team="Ohio", opponent_team="Iowa", player_id=13, player="Qb", passing_ATT=30, passing_YDS=280, passing_TD=3)]
    out = PD.ncaaf_pgames(rows, 2026, 5, {"11": "WR", "13": "QB"})
    assert [(p["name"], p["pos"], p["order"]) for p in out] == [("Rec", "WR", 2), ("Qb", "QB", 1)]
    assert out[0]["stats"]["rec"] == 6 and out[0]["stats"]["rec_yds"] == 90 and out[1]["stats"]["pass_yds"] == 280
    assert "tgt" not in out[0]["stats"] or out[0]["stats"].get("tgt", 0) == 0


def chart(rows):
    return [dict(team="A", pos_abb=p, pos_rank=r, player_name=n, gsis_id=g) for p, r, n, g in rows]


def test_depth_chart_becomes_slots_with_wr_backups_and_injury_status():
    rows = chart([("QB", 1, "Q1", "g1"), ("QB", 2, "Q2", "g2"), ("RB", 1, "R1", "g3"), ("RB", 2, "R2", "g4"), ("FB", 1, "F1", "g5"),
                  ("WR", 1, "W1", "g6"), ("WR", 2, "W2", "g7"), ("WR", 3, "W3", "g8"), ("WR", 4, "W4", "g9"), ("TE", 1, "T1", "g10"),
                  ("TE", 2, "T2", "g11"), ("WR", 1, "W1", "g6"), ("LT", 1, "Lt", "g12")])
    d = PD.football_depth_from_chart(rows, {"W2": "Questionable", "R1": None})
    assert [x["name"] for x in d["QB"]] == ["Q1", "Q2"]
    assert d["RB1"][0]["name"] == "R1" and d["RB2"][0]["name"] == "R2"
    assert [d[k][0]["name"] for k in ("WR1", "WR2", "WR3")] == ["W1", "W2", "W3"] and d["WR2"][0]["status"] == "Questionable"
    assert [x["name"] for x in d["TE1"]] == ["T1", "T2"] and "FB" not in d
    assert PD.football_depth_from_chart([]) == {}


def test_clean_status_drops_nan_text():
    assert [PD.clean_status(x) for x in (None, float("nan"), "nan", "", " Out ", "None")] == [None, None, None, None, "Out", None]


def test_latest_depth_chart_rows_takes_the_newest_offense_snapshot_only():
    df = pd.DataFrame([dict(team="A", dt="2026-10-01", pos_grp="3WR 1TE", pos_abb="QB", pos_rank=1, player_name="Old", gsis_id="o"),
                       dict(team="A", dt="2026-10-02", pos_grp="3WR 1TE", pos_abb="QB", pos_rank=1, player_name="New", gsis_id="n"),
                       dict(team="A", dt="2026-10-02", pos_grp="Base 4-3 D", pos_abb="LDE", pos_rank=1, player_name="Dl", gsis_id="d"),
                       dict(team="A", dt="2026-10-02", pos_grp="Special Teams", pos_abb="P", pos_rank=1, player_name="Pt", gsis_id="p"),
                       dict(team="B", dt="2026-10-03", pos_grp="3WR 1TE", pos_abb="QB", pos_rank=1, player_name="Other", gsis_id="x")])
    assert [r["player_name"] for r in PD.latest_depth_chart_rows(df, "A")] == ["New"]
    assert PD.latest_depth_chart_rows(df, "Z") == [] and PD.latest_depth_chart_rows(None, "A") == []


# ------------------------------------------------------------------ basketball sample
def ev(eid, date, home, away, completed=True, stype=2):
    return {"id": eid, "date": date, "status": {"type": {"completed": completed}}, "season": {"type": stype},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"id": str(home)}}, {"homeAway": "away", "team": {"id": str(away)}}]}]}


def test_parse_scoreboard_events_filters_by_date_status_and_season_type():
    events = [ev("1", "2026-10-05T23:00Z", 1, 2), ev("2", "2026-10-06T23:00Z", 3, 4, completed=False), ev("3", "2026-10-07T23:00Z", 5, 6),
              ev("4", "2026-09-01T23:00Z", 7, 8), ev("5", "2026-10-04T23:00Z", 9, 10, stype=1), {"id": "6", "date": "2026-10-04T00:00Z"},
              ev("7", "2026-10-03T23:00Z", 1, 1)]
    out = PD.parse_scoreboard_events(events, "2026-10-07", "2026-09-20", lambda t: t != 1)
    assert [g["gid"] for g in out] == ["1"] and out[0]["home"] == 1 and out[0]["away"] == 2 and out[0]["type"] == 2
    assert [g["gid"] for g in PD.parse_scoreboard_events(events, "2026-10-07", "2026-09-20", lambda t: t == 1)] == ["5"]


def test_pick_recent_per_team_caps_each_team_and_teams_with_enough_counts():
    games = [{"gid": str(i), "date": f"2026-10-{i + 1:02d}", "home": 1, "away": 2 + i % 2} for i in range(6)]
    keep = PD.pick_recent_per_team(games, 2)
    assert set(keep) == {"5", "4", "3", "2"}                      # team 1 is capped at its two newest, but 2 and 3 each still need games
    assert PD.teams_with_enough(games, 3) == 3 and PD.teams_with_enough(games, 4) == 1


def lines_for(tid, rows):
    return [dict(id=i, name=n, pos=pos, starter=False, min=m, pts=pts, reb=r, ast=a, fg3m=t) for i, n, pos, m, pts, r, a, t in rows]


def test_basketball_pgames_attributes_each_team_to_the_other_and_fills_positions_from_the_roster():
    gl = {"g1": {"date": "2026-10-01T00:00Z", "lines": {1: lines_for(1, [(10, "Guard", "PG", 30, 20, 3, 6, 2), (11, "NoPos", None, 20, 8, 2, 1, 0)]),
                                                        2: lines_for(2, [(20, "Big", "C", 28, 12, 10, 2, 0)])}},
          "g2": {"date": "x", "lines": {1: lines_for(1, [(10, "Guard", "PG", 30, 5, 5, 5, 5)])}}}      # one-team game is skipped
    out = PD.basketball_pgames(gl, {11: "SF"})
    by = {p["name"]: p for p in out}
    assert (by["Guard"]["team"], by["Guard"]["opp"]) == (1, 2) and (by["Big"]["team"], by["Big"]["opp"]) == (2, 1)
    assert by["NoPos"]["pos"] == "SF" and by["Guard"]["stats"]["pts"] == 20 and by["Guard"]["order"] == "2026-10-01T00:00Z" and len(out) == 3


# ------------------------------------------------------------------ bundle assembly
def football_pgames(n_def=10):
    out = []
    for i in range(n_def):
        for wk in (1, 2, 3):
            out.append(dict(game=f"{i}-{wk}", order=wk, team="OFF", opp=f"D{i}", pid=f"o{i}", name=f"Rec{i}", pos="WR",
                            stats=dict(tgt=6, rec=3 + i, rec_yds=30 + 10 * i)))
    for wk in (1, 2, 3):
        out.append(dict(game=f"h{wk}", order=wk, team="HOME", opp="D0", pid="h1", name="HomeWr", pos="WR", stats=dict(tgt=9, rec=7, rec_yds=90)))
        out.append(dict(game=f"a{wk}", order=wk, team="AWAY", opp="D1", pid="a1", name="AwayWr", pos="WR", stats=dict(tgt=7, rec=4, rec_yds=50)))
    return out


def test_build_bundle_for_football_fills_depth_from_usage_and_builds_h2h():
    h2h = [dict(date="2025-10-01", home="HOME", away="AWAY", home_score=27, away_score=20, season=2025)]
    b = PD.build_bundle("NFL", "HOME", "AWAY", football_pgames(), {"HOME": {"WR1": [{"pid": "h1", "name": "Chart Wr", "status": "Out"}]}}, h2h)
    wr_home = [r for r in b["home_off"]["rows"] if r["slot"] == "WR1"][0]
    assert wr_home["players"][0]["name"] == "Chart Wr" and wr_home["players"][0]["status"] == "Out"      # the published chart wins
    wr_away = [r for r in b["away_off"]["rows"] if r["slot"] == "WR1"][0]
    assert wr_away["players"][0]["name"] == "AwayWr" and "held the slot in 3 of the last 4 games" in wr_away["players"][0]["note"]   # no chart -> usage
    assert b["home_off"]["defense"] == "AWAY" and b["away_off"]["offense"] == "AWAY" and b["notes"] == []
    assert b["h2h"]["summary"]["games"] == 1 and "HOME lead the series 1–0" in b["h2h"]["sentence"] and b["metric"] == PM.METRIC_LABEL["football"]
    assert b["games_sampled"] == (0, 0)


def test_build_bundle_flags_a_team_with_no_depth_or_usage():
    b = PD.build_bundle("NFL", "HOME", "AWAY", football_pgames()[:6], {}, [], names={"HOME": "Home FC", "AWAY": "Away FC"})
    assert any("No depth chart or recent usage found for Home FC" in n for n in b["notes"])
    assert b["names"] == {"HOME": "Home FC", "AWAY": "Away FC"}


def test_build_side_has_no_ranks_with_too_few_defenses():
    b = PD.build_bundle("NFL", "HOME", "AWAY", football_pgames(4), {}, [])
    assert b["home_off"]["ranked"] == 0 and all(r["rank"] is None for r in b["home_off"]["rows"])
    full = PD.build_bundle("NFL", "HOME", "AWAY", football_pgames(10), {}, [])
    assert full["home_off"]["ranked"] >= PD.MIN_TEAMS_FOR_RANK


def test_fill_depth_from_usage_only_fills_empty_slots():
    usage = {"WR1": [{"pid": 1, "name": "U1", "avg_min": 31.0, "games_in_slot": 4, "avg": 9.0}], "WR2": [{"pid": 2, "name": "U2", "avg_min": 0, "games_in_slot": 2, "avg": 5.0}]}
    out = PD.fill_depth_from_usage({"WR1": [{"pid": 9, "name": "Chart"}]}, usage, "NFL")
    assert out["WR1"][0]["name"] == "Chart" and out["WR2"][0]["name"] == "U2" and "2 of the last" in out["WR2"][0]["note"]
    bb = PD.fill_depth_from_usage({}, {"G": [{"pid": 1, "name": "G1", "avg_min": 31.4, "games_in_slot": 4, "avg": 20.0}]}, "NBA")
    assert bb["G"][0]["note"] == "31 min"


# ------------------------------------------------------------------ football orchestration (engine faked)
class FakeNfl:
    @staticmethod
    def _infer_season(d):
        return 2026

    @staticmethod
    def get_schedule(season):
        if season == 2025:
            return [dict(game_id="p", week=2, game_date="2025-09-14", game_time="13:00", home_team="AWAY", away_team="HOME", home_score=17, away_score=24)]
        if season == 2026:
            return [dict(game_id="g", week=5, game_date="2026-10-11", game_time="13:00", home_team="HOME", away_team="AWAY", home_score=None, away_score=None),
                    dict(game_id="m", week=3, game_date="2026-09-27", game_time="13:00", home_team="AWAY", away_team="OFF2", home_score=24, away_score=20)]
        return []

    @staticmethod
    def _resolve_week(sched, d):
        return 5

    @staticmethod
    def games_for_week(sched, week):
        return [g for g in sched if g["week"] == week]

    @staticmethod
    def kickoff_utc_iso(d, t):
        return f"{d}T17:00:00Z"

    @staticmethod
    def load_season_weekly_stats(season):
        rows = []
        for i in range(10):
            for wk in (1, 2, 3, 4):
                rows.append(dict(player_id=f"o{i}", player_display_name=f"Rec{i}", position="WR", team="OFF", opponent_team=f"D{i}", week=wk,
                                 targets=6, receptions=3 + i, receiving_yards=30 + 10 * i))
        for wk in (1, 2, 3, 4):
            rows.append(dict(player_id="h1", player_display_name="HomeWr", position="WR", team="HOME", opponent_team="D0", week=wk, targets=9, receptions=6, receiving_yards=80))
            rows.append(dict(player_id="a1", player_display_name="AwayWr", position="WR", team="AWAY", opponent_team="D1", week=wk, targets=8, receptions=5, receiving_yards=60))
        for wk in (1, 2, 3, 4):                                      # somebody who played each of the two defenses
            rows.append(dict(player_id="x1", player_display_name="Rival", position="WR", team="OFF2", opponent_team="AWAY", week=wk, targets=7, receptions=4, receiving_yards=55))
            rows.append(dict(player_id="x2", player_display_name="Rival2", position="WR", team="OFF3", opponent_team="HOME", week=wk, targets=5, receptions=2, receiving_yards=20))
        rows.append(dict(player_id="h1", player_display_name="HomeWr", position="WR", team="HOME", opponent_team="D0", week=5, targets=99, receptions=99, receiving_yards=999))   # not before week 5
        return weekly_df(rows)

    @staticmethod
    def get_team_injuries(team, season, week):
        return [dict(player="HomeWr", status="Questionable")] if team == "HOME" else []


@pytest.fixture
def fake_nfl(monkeypatch):
    nfl_sport = sports.get("NFL")
    monkeypatch.setitem(sports.REGISTRY, "NFL", __import__("dataclasses").replace(nfl_sport, engine_module="test_position_data_fake_nfl", _engine=None))
    import sys, types
    mod = types.ModuleType("test_position_data_fake_nfl")
    for k in ("_infer_season", "get_schedule", "_resolve_week", "games_for_week", "kickoff_utc_iso", "load_season_weekly_stats", "get_team_injuries"):
        setattr(mod, k, getattr(FakeNfl, k))
    monkeypatch.setitem(sys.modules, "test_position_data_fake_nfl", mod)
    import nflreadpy
    depth = pd.DataFrame([dict(team="HOME", dt="2026-10-07", pos_grp="3WR 1TE", pos_abb="WR", pos_rank=1, player_name="HomeWr", gsis_id="h1")])
    monkeypatch.setattr(nflreadpy, "load_depth_charts", lambda season: type("T", (), {"to_pandas": lambda self: depth})())
    monkeypatch.setattr(nflreadpy, "get_current_season", lambda: 2026)
    return mod


def test_list_games_for_football_is_the_dates_week_in_kickoff_order(fake_nfl):
    g = PD.list_games("NFL", "2026-10-07")
    assert [x["label"] for x in g] == ["AWAY @ HOME"] and g[0]["game_date"] == "2026-10-11T17:00:00Z" and g[0]["home_id"] == "HOME"


def test_load_football_end_to_end_with_a_fake_nfl(fake_nfl):
    b = PD.load_bundle("NFL", "2026-10-07", PD.list_games("NFL", "2026-10-07")[0])
    wr = [r for r in b["home_off"]["rows"] if r["slot"] == "WR1"][0]
    assert wr["players"][0]["name"] == "HomeWr" and wr["players"][0]["status"] == "Questionable"      # chart + injury report
    assert wr["players"][0]["recent"]["games"] == 4 and abs(wr["players"][0]["recent"]["avg"] - (6 + 8 + 0)) < 1e-9   # week 5 leak excluded
    assert wr["games"] == 4 and wr["n_teams"] == 12 and 1 <= wr["rank"] <= 12 and abs(wr["allowed"] - (4 + 5.5)) < 1e-9   # AWAY allowed Rival 4 rec + 55 yds
    assert any("games through week 4" in n for n in b["notes"])
    assert b["h2h"]["summary"]["games"] == 1 and b["h2h"]["summary"]["a_wins"] == 1          # HOME won at AWAY in 2025
    assert [r["players"][0]["name"] for r in b["away_off"]["rows"] if r["slot"] == "WR1"] == ["AwayWr"]     # usage fallback for the other side


def test_load_football_previous_season_uses_every_week(fake_nfl):
    b = PD.load_bundle("NFL", "2026-10-07", PD.list_games("NFL", "2026-10-07")[0], use_previous_season=True)
    wr = [r for r in b["home_off"]["rows"] if r["slot"] == "WR1"][0]
    assert wr["players"][0]["recent"]["avg"] != 14.0 or wr["players"][0]["recent"]["games"] == 4      # includes the week-5 line now
    assert not any("games through week" in n for n in b["notes"])


def test_load_football_degrades_with_notes_when_sources_fail(monkeypatch, fake_nfl):
    monkeypatch.setattr(fake_nfl, "load_season_weekly_stats", lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    b = PD.load_bundle("NFL", "2026-10-07", PD.list_games("NFL", "2026-10-07")[0])
    assert any("Couldn't load NFL weekly stats" in n for n in b["notes"]) and any("No 2026 player-game data" in n for n in b["notes"])
    assert b["home_off"]["rows"] and b["h2h"]["summary"]["games"] == 1


# ------------------------------------------------------------------ basketball orchestration (engines faked)
def cdn_box(home, away, rows_home, rows_away, with_pos=True):
    def grp(tid, rows):
        return {"team": {"id": str(tid)}, "statistics": [{"names": ["MIN", "PTS", "REB", "AST", "3PT"], "athletes": [
            {"athlete": dict({"id": str(i), "displayName": n}, **({"position": {"abbreviation": pos}} if with_pos and pos else {})),
             "stats": [str(m), str(p), str(r), str(a), f"{t}-5"], "starter": True} for i, n, pos, m, p, r, a, t in rows]}]}
    return {"gamepackageJSON": {"boxscore": {"players": [grp(home, rows_home), grp(away, rows_away)]}}}


class FakeBasketball:
    """A tiny league: teams 1..N. Team t's guard has id t*10+1, its center t*10+2."""
    SITE_API = "https://fake/site"
    CDN_API = "https://fake/cdn"
    SEASON_START = "2026-10-20"
    PRIOR_LOOKBACK_DAYS = 230

    def __init__(self, events, with_pos=True):
        self.events = events
        self.with_pos = with_pos
        self.fetched = []
        self.rosters = []

    def _get_json_cached(self, url, params=None):
        gid = (params or {}).get("gameId")
        self.fetched.append(gid)
        ev = next(e for e in self.events if e["id"] == gid)
        comps = ev["competitions"][0]["competitors"]
        home = int(next(c for c in comps if c["homeAway"] == "home")["team"]["id"])
        away = int(next(c for c in comps if c["homeAway"] == "away")["team"]["id"])
        pts = lambda t: 10 + t                                # a team's guard scores more for higher-numbered teams
        rows = lambda t: [(t * 10 + 1, f"G{t}", "PG", 30, pts(t), 3, 5, 2), (t * 10 + 2, f"C{t}", "C", 25, 8, 9, 1, 0)]
        return cdn_box(home, away, rows(home), rows(away), self.with_pos)

    def get_team_roster(self, tid):
        self.rosters.append(tid)
        return [dict(id=tid * 10 + 1, name=f"G{tid}", pos="PG"), dict(id=tid * 10 + 2, name=f"C{tid}", pos="C")]

    def get_team_injuries(self, abbr):
        return [dict(player="G1", status="Out")] if abbr == "T1" else []

    def get_schedule(self, d):
        return [dict(gameId="s", game_date="2026-10-08T00:00:00Z", home_id=1, home_name="Team One", home_abbr="T1", away_id=2, away_name="Team Two", away_abbr="T2")]

    def get_team_recent_game_ids(self, team, before, n=10, days_back=45):
        out = []
        for e in self.events:
            comps = e["competitions"][0]["competitors"]
            ids = [int(c["team"]["id"]) for c in comps]
            if team in ids and e["date"][:10] < before:
                opp = [i for i in ids if i != team][0]
                home = int(next(c for c in comps if c["homeAway"] == "home")["team"]["id"])
                out.append({"gameId": e["id"], "date": e["date"], "opp_id": str(opp), "opp_name": f"Team {opp}", "score": "110" if team == 1 else "100",
                            "opp_score": "100" if team == 1 else "110", "season_type": e["season"]["type"], "home_away": "home" if home == team else "away"})
        return sorted(out, key=lambda g: g["date"], reverse=True)[:n]


def league_events(n_teams=24, days=8, start="2026-09-20", stype=2, prefix="e"):
    out = []
    d0 = pd.Timestamp(start)
    for day in range(days):
        date = (d0 + pd.Timedelta(days=day)).strftime("%Y-%m-%dT23:00Z")
        for t in range(1, n_teams + 1):
            out.append(ev(f"{prefix}{day}-{t}", date, t, t % n_teams + 1, stype=stype))
    return out


@pytest.fixture
def basketball(monkeypatch):
    def install(sport_key, fake, scoreboard=None):
        import sys, types, dataclasses
        mod = types.ModuleType("test_position_data_fake_bb")
        for k in ("SITE_API", "CDN_API", "SEASON_START", "PRIOR_LOOKBACK_DAYS"):
            setattr(mod, k, getattr(fake, k))
        for k in ("_get_json_cached", "get_team_roster", "get_team_injuries", "get_schedule", "get_team_recent_game_ids"):
            setattr(mod, k, getattr(fake, k))
        monkeypatch.setitem(sys.modules, "test_position_data_fake_bb", mod)
        monkeypatch.setitem(sports.REGISTRY, sport_key, dataclasses.replace(sports.get(sport_key), engine_module="test_position_data_fake_bb", _engine=None))
        if scoreboard is not None:
            monkeypatch.setattr(BB, "scoreboard_events_in_window", lambda site, fetch, start, end, *a, **k: scoreboard)
        return mod
    return install


def test_get_game_player_lines_attributes_players_to_teams():
    box = cdn_box(1, 2, [(11, "G1", "PG", 30, 20, 3, 5, 2)], [(21, "G2", None, 25, 8, 9, 1, 0)])
    lines = BB.get_game_player_lines("x", "cdn", lambda url, params=None: box)
    assert set(lines) == {1, 2} and lines[1][0]["pos"] == "PG" and lines[2][0]["pos"] is None
    assert (lines[1][0]["pts"], lines[1][0]["reb"], lines[1][0]["ast"], lines[1][0]["fg3m"], lines[1][0]["min"]) == (20, 3, 5, 2, 30)
    assert BB.get_game_player_lines("x", "cdn", lambda url, params=None: None) == {} and BB.get_game_player_lines("x", "cdn", lambda *a, **k: {}) == {}


def test_nba_bundle_ranks_defenses_across_the_league_sample(basketball):
    events = league_events()
    fake = FakeBasketball(events)
    basketball("NBA", fake, scoreboard=events)
    b = PD.load_basketball("NBA", "2026-10-01", 1, 2, "Team One", "Team Two", "T1", "T2")
    assert b["names"] == {1: "Team One", 2: "Team Two"} and b["notes"] == []
    g_row = [r for r in b["home_off"]["rows"] if r["slot"] == "G"][0]          # Team One's guards vs Team Two's defense
    assert g_row["players"][0]["name"] == "G1" and g_row["players"][0]["status"] == "Out" and g_row["rank"] is not None and g_row["n_teams"] >= 20
    assert g_row["allowed"] is not None and g_row["thin"] is False
    c_row = [r for r in b["away_off"]["rows"] if r["slot"] == "C"][0]
    assert c_row["players"][0]["name"] == "C2" and c_row["line"].count("pts") == 1
    assert b["h2h"]["summary"]["games"] == 8 and b["h2h"]["sentence"].startswith("Team One lead the series 8–0")      # the fake gives team 1 a 110–100 win each time
    assert len(set(fake.fetched)) <= 24 * 7                                    # per-team cap bounds the box-score fetches
    assert fake.rosters == []                                                   # ESPN box scores carried positions, so no roster fetches


def test_positions_fall_back_to_rosters_when_the_box_score_has_none(basketball):
    events = league_events(n_teams=10, days=4)
    fake = FakeBasketball(events, with_pos=False)
    basketball("NBA", fake, scoreboard=events)
    b = PD.load_basketball("NBA", "2026-10-01", 1, 2, "Team One", "Team Two")
    assert fake.rosters and [r for r in b["home_off"]["rows"] if r["slot"] == "G"][0]["players"][0]["name"] == "G1"


def test_nba_preseason_uses_last_regular_season_for_the_sample(basketball):
    pre = league_events(days=3, start="2026-10-01", stype=1, prefix="pre")
    last = league_events(days=6, start="2026-04-01", stype=2, prefix="reg")
    fake = FakeBasketball(pre + last)
    basketball("NBA", fake, scoreboard=pre + last)
    b = PD.load_basketball("NBA", "2026-10-07", 1, 2, "Team One", "Team Two", "T1", "T2")
    assert any("end of last regular season" in n for n in b["notes"])
    assert all(g.startswith("reg") for g in fake.fetched)                      # not a single exhibition box score was used
    assert [r for r in b["home_off"]["rows"] if r["slot"] == "G"][0]["rank"] is not None


def test_ncaamb_samples_only_the_two_teams_and_gives_no_rank(basketball):
    events = league_events(n_teams=6, days=5, start="2026-11-20")
    fake = FakeBasketball(events)
    basketball("NCAAMB", fake)
    b = PD.load_basketball("NCAAMB", "2026-12-01", 1, 2, "One", "Two", "T1", "T2")
    assert any("360 teams" in n for n in b["notes"]) and b["home_off"]["ranked"] == 0
    row = [r for r in b["home_off"]["rows"] if r["slot"] == "G"][0]
    assert row["rank"] is None and row["tier"] == "—" and row["allowed"] is not None
    assert all(any(t in (e["competitions"][0]["competitors"][0]["team"]["id"], e["competitions"][0]["competitors"][1]["team"]["id"]) for t in ("1", "2"))
               for e in events if e["id"] in fake.fetched)                    # only games involving the two teams were fetched


def test_basketball_h2h_games_skips_exhibitions_other_opponents_and_unscored(basketball):
    events = [ev("a", "2026-10-01T00:00Z", 1, 2), ev("b", "2026-10-02T00:00Z", 2, 1), ev("c", "2026-09-30T00:00Z", 1, 3), ev("d", "2026-09-29T00:00Z", 1, 2, stype=1)]
    fake = FakeBasketball(events)
    mod = basketball("NBA", fake)
    out = PD.basketball_h2h_games(mod, 1, 2, "2026-10-07", "Team One", "Team Two")
    assert [(g["date"][:10], g["home"], g["home_score"], g["away_score"]) for g in out] == \
        [("2026-10-02", "Team Two", 100.0, 110.0), ("2026-10-01", "Team One", 110.0, 100.0)]      # newest first; venue from home_away
    unscored = FakeBasketball(events)
    unscored.get_team_recent_game_ids = lambda *a, **k: [dict(opp_id="2", score=None, opp_score=None, season_type=2, date="x")]
    assert PD.basketball_h2h_games(basketball("NBA", unscored), 1, 2, "2026-10-07", "A", "B") == []
    boom = FakeBasketball(events)
    boom.get_team_recent_game_ids = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    assert PD.basketball_h2h_games(basketball("NBA", boom), 1, 2, "2026-10-07", "A", "B") == []


def test_list_games_for_basketball_and_load_bundle_dispatch(basketball, monkeypatch):
    events = league_events(n_teams=10, days=4)
    fake = FakeBasketball(events)
    basketball("NBA", fake, scoreboard=events)
    g = PD.list_games("NBA", "2026-10-08")
    assert g == [dict(label="Team Two @ Team One", home="Team One", away="Team Two", home_id=1, away_id=2, home_abbr="T1", away_abbr="T2",
                      game_date="2026-10-08T00:00:00Z")]
    b = PD.load_bundle("NBA", "2026-10-08", g[0])
    assert b["sport"] == "NBA" and b["names"][1] == "Team One"


def test_a_box_score_position_beats_the_rosters():
    gl = {"g": {"date": "d", "lines": {1: lines_for(1, [(10, "Guard", "PG", 30, 20, 3, 6, 2)]), 2: lines_for(2, [(20, "Big", "C", 28, 12, 10, 2, 0)])}}}
    assert {p["name"]: p["pos"] for p in PD.basketball_pgames(gl, {10: "C", 20: "PG"})} == {"Guard": "PG", "Big": "C"}


def test_has_treats_nan_and_blank_as_missing():
    assert [PD._has(x) for x in (None, float("nan"), "", "  ", "nan", "KC", 3)] == [False, False, False, False, False, True, True]
    df = weekly_df([dict(player_id="1", position="WR", week=1, targets=5, opponent_team=float("nan"))])
    assert PD.nfl_pgames(df, 5) == []


def test_nba_sample_falls_back_to_last_season_when_only_a_few_teams_have_games(basketball):
    few = league_events(n_teams=6, days=4, start="2026-10-20", stype=2, prefix="cur")             # opening week: a real but tiny sample
    last = league_events(days=6, start="2026-04-01", stype=2, prefix="reg")
    fake = FakeBasketball(few + last)
    basketball("NBA", fake, scoreboard=few + last)
    b = PD.load_basketball("NBA", "2026-10-24", 1, 2, "Team One", "Team Two", "T1", "T2")
    assert any("end of last regular season" in n for n in b["notes"]) and all(g.startswith("reg") for g in fake.fetched)


def test_previous_season_option_reads_last_seasons_file_and_every_week(fake_nfl, monkeypatch):
    asked = []
    orig = fake_nfl.load_season_weekly_stats
    monkeypatch.setattr(fake_nfl, "load_season_weekly_stats", lambda s: asked.append(s) or orig(s))
    game = PD.list_games("NFL", "2026-10-07")[0]
    cur = PD.load_bundle("NFL", "2026-10-07", game)
    prev = PD.load_bundle("NFL", "2026-10-07", game, use_previous_season=True)
    assert asked == [2026, 2025]
    f = lambda b: [r for r in b["home_off"]["rows"] if r["slot"] == "WR1"][0]["players"][0]["recent"]
    assert abs(f(cur)["avg"] - 14.0) < 1e-9                                          # weeks 1-4 only (week 5 is the game's own week)
    assert abs(f(prev)["avg"] - (198.9 + 14 * 3) / 4) < 1e-9                         # last season = every week the file has


# ------------------------------------------------------------------ game-log data (dates / venue / results / names)
def test_scoreboard_parse_carries_names_and_scores_for_the_game_log():
    e = ev("1", "2026-10-05T23:00Z", 1, 2)
    comps = e["competitions"][0]["competitors"]
    comps[0].update(score="101", team={"id": "1", "displayName": "Team One"})
    comps[1].update(score="99", team={"id": "2", "displayName": "Team Two"})
    g = PD.parse_scoreboard_events([e], "2026-10-07", "2026-09-20", lambda t: True)[0]
    assert (g["home_name"], g["away_name"], g["home_score"], g["away_score"]) == ("Team One", "Team Two", "101", "99")
    bare = PD.parse_scoreboard_events([ev("2", "2026-10-05T23:00Z", 3, 4)], "2026-10-07", "2026-09-20", lambda t: True)[0]
    assert bare["home_name"] is None and bare["home_score"] is None


def test_football_meta_games_reads_each_sources_own_field_names():
    nfl = PD.football_meta_games("NFL", [dict(week=3, game_date="2026-09-27", home_team="A", away_team="B", home_score=10, away_score=7),
                                         dict(week=None, game_date="x", home_team="A", away_team="B")])
    assert nfl == [dict(order=3, date="2026-09-27", home="A", away="B", home_score=10, away_score=7)]
    col = PD.football_meta_games("NCAAF", [dict(week=4, start_date="2026-09-26T19:00Z", home_team="Ohio", away_team="Iowa", home_points=31, away_points=17)])
    assert col == [dict(order=4, date="2026-09-26T19:00Z", home="Ohio", away="Iowa", home_score=31, away_score=17)]
    assert PD.football_meta_games("NFL", None) == []


def test_build_bundle_carries_what_the_game_log_needs():
    b = PD.build_bundle("NFL", "HOME", "AWAY", football_pgames(), {}, [], names={"D3": "Dee Three", "HOME": "Home FC"},
                        meta_games=[dict(order=2, date="2026-09-20", home="D3", away="OFF", home_score=20, away_score=10)])
    assert set(b["allowed"]) >= {"D0", "D3", "D1"} and b["allowed"]["D3"][0]["who"]["WR1"] == ["Rec3"]
    assert b["all_names"]["D3"] == "Dee Three" and b["all_names"]["HOME"] == "Home FC" and b["all_names"]["D0"] == "D0" and b["all_names"]["AWAY"] == "AWAY"
    assert b["meta"][(2, "D3", "OFF")] == {"date": "2026-09-20", "venue": "Home", "def_score": 20.0, "off_score": 10.0}
    assert PD.build_bundle("NFL", "HOME", "AWAY", [], {}, [])["meta"] == {}


def test_football_log_end_to_end_has_venue_and_result_from_the_schedule(fake_nfl):
    b = PD.load_bundle("NFL", "2026-10-07", PD.list_games("NFL", "2026-10-07")[0])
    log = PM.slot_game_log(b["allowed"], "AWAY", "WR1", "NFL", b["meta"], n=10)
    assert [r["order"] for r in log["rows"]] == [4, 3, 2, 1]                      # newest first
    wk3 = [r for r in log["rows"] if r["order"] == 3][0]
    assert (wk3["venue"], wk3["result"], wk3["score"], wk3["date"], wk3["who"], wk3["opp"]) == ("Home", "W", "24-20", "2026-09-27", "Rival", "OFF2")
    assert [r["venue"] for r in log["rows"] if r["order"] != 3] == [None, None, None]      # weeks the schedule fake doesn't list
    home_only = PM.slot_game_log(b["allowed"], "AWAY", "WR1", "NFL", b["meta"], n=10, venue="Home")
    assert [r["order"] for r in home_only["rows"]] == [3]


def test_previous_season_log_uses_last_seasons_schedule(fake_nfl):
    b = PD.load_bundle("NFL", "2026-10-07", PD.list_games("NFL", "2026-10-07")[0], use_previous_season=True)
    assert (2, "AWAY", "HOME") in b["meta"] and b["meta"][(2, "AWAY", "HOME")]["def_score"] == 17.0
    assert (3, "AWAY", "OFF2") not in b["meta"]                                      # this season's schedule is not mixed in


def test_nba_log_names_every_team_and_dates_each_game(basketball):
    events = league_events()
    for e in events:
        for c in e["competitions"][0]["competitors"]:
            c["team"]["displayName"] = f"Team {c['team']['id']}"
            c["score"] = "110" if c["homeAway"] == "home" else "100"
    fake = FakeBasketball(events)
    basketball("NBA", fake, scoreboard=events)
    b = PD.load_basketball("NBA", "2026-10-01", 1, 2, "Team One", "Team Two", "T1", "T2")
    assert b["all_names"][5] == "Team 5" and b["all_names"][1] == "Team One" and len(b["all_names"]) >= 20
    log = PM.slot_game_log(b["allowed"], 2, "G", "NBA", b["meta"], n=10)
    by_opp = {}
    for r in log["rows"]:
        by_opp.setdefault(r["opp"], []).append((r["venue"], r["result"], r["score"], r["who"]))
    assert set(by_opp[1]) == {("Away", "L", "100-110", "G1")}                      # team 1 hosts team 2: the defense lost on the road
    assert set(by_opp[3]) == {("Home", "W", "110-100", "G3")}                      # team 2 hosts team 3: the defense won at home


def test_ncaamb_games_are_labelled_with_the_real_home_side_and_both_names(basketball):
    events = league_events(n_teams=6, days=5, start="2026-11-20")
    fake = FakeBasketball(events)
    basketball("NCAAMB", fake)
    b = PD.load_basketball("NCAAMB", "2026-12-01", 1, 2, "One", "Two", "T1", "T2")
    assert set(b["all_names"]) >= {1, 2} and b["all_names"][1] == "One" and b["all_names"][3] == "Team 3"       # an opponent's name comes off the scoreboard
    log = PM.slot_game_log(b["allowed"], 1, "G", "NCAAMB", b["meta"], n=10)
    assert log["rows"] and all(r["venue"] in ("Home", "Away") and r["result"] in ("W", "L") for r in log["rows"])
    expect = {}
    for e in events:
        sides = {c["homeAway"]: int(c["team"]["id"]) for c in e["competitions"][0]["competitors"]}
        if 1 in sides.values():
            expect[(e["date"], sides["away"] if sides["home"] == 1 else sides["home"])] = "Home" if sides["home"] == 1 else "Away"
    assert all(r["venue"] == expect[(r["order"], r["opp"])] for r in log["rows"])
    assert {"Home", "Away"} == {r["venue"] for r in log["rows"]}                      # the sample really has both, so the check above bites
