import media_focus as MF
import projections as P

MNF = "2026-10-06T00:15:00+00:00"      # Mon Oct 5, 8:15 PM ET
SUN = "2026-10-04T17:00:00+00:00"      # Sun Oct 4, 1:00 PM ET


def _meta():
    return [{"label": "KC @ BUF", "game_date": SUN}, {"label": "ATL @ NO", "game_date": MNF},
            {"label": "DAL @ NYG", "game_date": "2026-10-04"}]


def test_day_of_handles_utc_rollover_bare_date_and_garbage():
    assert MF.day_of(MNF) == "2026-10-05"            # 00:15 UTC is still Monday night in Eastern
    assert MF.day_of("2026-10-04") == "2026-10-04"
    assert MF.day_of(None) is None and MF.day_of("") is None and MF.day_of("garbage") is None


def test_games_on_date_keeps_only_that_day_in_kickoff_order():
    g = MF.games_on_date(_meta(), [], "2026-10-05")
    assert [x["label"] for x in g] == ["ATL @ NO"]
    assert g[0]["matchup"] == "Falcons at Saints" and g[0]["slot"] == "Late"
    assert g[0]["time_text"] == "8:15 PM ET"
    sunday = MF.games_on_date(_meta(), [], "2026-10-04")
    assert [x["label"] for x in sunday] == ["KC @ BUF", "DAL @ NYG"]   # timed game before bare-date one


def test_plays_on_date_filters_other_days_but_keeps_undated():
    plays = [{"Player": "a", "GameDate": MNF}, {"Player": "b", "GameDate": SUN}, {"Player": "c"}]
    assert [p["Player"] for p in MF.plays_on_date(plays, "2026-10-05")] == ["a", "c"]


def test_slate_phrase_single_game_monday_night():
    g = MF.games_on_date(_meta(), [], "2026-10-05")
    s = MF.slate_phrase(g, "2026-10-05")
    assert s == "Monday night — one game on the ticket: Falcons at Saints (8:15 PM ET)"
    assert "2 games" in MF.slate_phrase(MF.games_on_date(_meta(), [], "2026-10-04"), "2026-10-04")
    assert MF.slate_phrase([], "2026-10-05") == "No games on the ticket"


def test_other_days_and_fallback_to_plays_when_meta_empty():
    assert MF.other_days_with_games(_meta(), "2026-10-05") == ["2026-10-04"]
    g = MF.games_on_date([], [{"Game": "ATL @ NO", "GameDate": MNF}], "2026-10-05")
    assert [x["label"] for x in g] == ["ATL @ NO"]


def test_nice_matchup_unknown_names_pass_through():
    assert MF.nice_matchup("Aces @ Liberty") == "Aces at Liberty"
    assert MF.nice_matchup("") == ""


def test_curate_per_game_returns_every_game_even_if_empty():
    games = MF.games_on_date(_meta(), [], "2026-10-04")
    plays = [{"Game": "KC @ BUF", "Market": "Pass Yds", "Conviction": 2.0, "Player": "x"},
             {"Game": "KC @ BUF", "Market": "Pass Yds", "Conviction": 1.5, "Player": "y"},
             {"Game": "KC @ BUF", "Market": "Pass Yds", "Conviction": 1.0, "Player": "z"}]
    out = MF.curate_per_game(plays, games, P.curate_selections, per_game=3, per_market_cap=2)
    assert [g["label"] for g, _ in out] == ["KC @ BUF", "DAL @ NYG"]
    assert [p["Player"] for p in out[0][1]] == ["x", "y"] and out[1][1] == []   # cap of 2 per market
