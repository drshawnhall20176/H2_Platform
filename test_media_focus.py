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


def test_slot_and_game_options_match_the_site_wide_filters():
    games = MF.games_on_date([{"label": "KC @ BUF", "game_date": SUN},
                              {"label": "SEA @ LAR", "game_date": "2026-10-04T20:25:00+00:00"}], [], "2026-10-04")
    assert MF.slot_options(games) == ["All slate", "Afternoon"]
    assert MF.game_options(games) == [("KC @ BUF", "1:00 PM ET — KC @ BUF"), ("SEA @ LAR", "4:25 PM ET — SEA @ LAR")]
    # a bare-date game (day known, kickoff unknown) shows up under TBD, with no time prefix
    tbd = MF.games_on_date(_meta(), [], "2026-10-04")
    assert MF.slot_options(tbd) == ["All slate", "Afternoon", "TBD"]
    assert ("DAL @ NYG", "DAL @ NYG") in MF.game_options(tbd, "TBD")
    assert MF.game_options(games, "Afternoon") == MF.game_options(games)        # both before 5 PM ET
    assert MF.game_options(games, "Late") == []


def test_select_games_applies_slot_then_game_like_other_pages():
    games = MF.games_on_date(_meta(), [], "2026-10-04")
    assert [g["label"] for g in MF.select_games(games, MF.ALL_SLATE, MF.ALL_GAMES_IN_SLOT)] == ["KC @ BUF", "DAL @ NYG"]
    assert [g["label"] for g in MF.select_games(games, MF.ALL_SLATE, "DAL @ NYG")] == ["DAL @ NYG"]
    assert MF.select_games(games, "Late", MF.ALL_GAMES_IN_SLOT) == []


def test_doubleheader_games_get_their_own_keys_and_plays_are_split_by_start_time():
    meta = [{"label": "NYY @ BOS", "game_date": "2026-06-10T17:05:00Z"},
            {"label": "NYY @ BOS", "game_date": "2026-06-10T23:10:00Z"}]
    g = MF.games_on_date(meta, [], "2026-06-10")
    assert len(g) == 2 and g[0]["key"] != g[1]["key"]
    assert [x["game_no"] for x in g] == [1, 2] and g[1]["matchup"].endswith("(Game 2)")
    plays = [{"Player": "a", "Game": "NYY @ BOS", "GameDate": "2026-06-10T17:05:00Z"},
             {"Player": "b", "Game": "NYY @ BOS", "GameDate": "2026-06-10T23:10:00Z"}]
    assert [p["Player"] for p in MF.plays_for_game(plays, g[0])] == ["a"]
    assert [p["Player"] for p in MF.plays_for_game(plays, g[1])] == ["b"]
    assert MF.game_options(g)[1][1].startswith("7:10 PM ET — NYY @ BOS (Game 2)")
