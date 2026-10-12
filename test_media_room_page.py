"""
test_media_room_page.py — renders views/21_Media_Room.py end to end with Streamlit's AppTest on a
synthetic NFL week (network-free): a Sunday slate + one Monday-night game. Covers the reported gap —
the page must focus on the date's game(s), not the whole week, and discuss sportsbook promotions.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import media_focus as MF
import nfl_engine
import nfl_projections

PAGE = str(Path(__file__).parent / "views" / "21_Media_Room.py")
MNF = "2026-10-06T00:15:00+00:00"
SUN = "2026-10-04T17:00:00+00:00"


def _p(name, team, game, gd, market, prob, conv, rec_yds=0, rec=0, rush_yds=0, car=0, pid="x"):
    log = [{"receiving_yards": rec_yds, "receptions": rec, "rushing_yards": rush_yds, "carries": car}] * 4
    return {"Player": name, "PlayerId": pid or name, "Team": team, "Game": game, "Opp": "OPP", "GameDate": gd,
            "Market": market, "Side": "Over", "Line": 0.5, "ModelProb": prob, "Fair": 140, "Conviction": conv,
            "Why": "recent form", "Position": "WR", "RealPrice": None, "PriceSource": "model_fair",
            "_game_log": log}


def _plays():
    mnf = "ATL @ NO"
    return [_p("Drake London", "ATL", mnf, MNF, "Anytime TD", .45, 1.5, rec_yds=70, rec=6),
            _p("Alvin Kamara", "NO", mnf, MNF, "Anytime TD", .52, 1.7, rush_yds=45, car=11, rec_yds=20, rec=4),
            _p("Bijan Robinson", "ATL", mnf, MNF, "Anytime TD", .50, 1.6, rush_yds=70, car=14),
            _p("Kirk Cousins", "ATL", mnf, MNF, "Pass Attempts", .6, 1.4),
            _p("Josh Allen", "BUF", "KC @ BUF", SUN, "Anytime TD", .40, 1.9, rush_yds=30, car=6),
            _p("Travis Kelce", "KC", "KC @ BUF", SUN, "Anytime TD", .48, 1.8, rec_yds=60, rec=6)]


def _meta():
    return [{"label": "KC @ BUF", "game_date": SUN}, {"label": "ATL @ NO", "game_date": MNF}]


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(nfl_engine, "build_slate", lambda d: ([], _meta()))
    monkeypatch.setattr(nfl_projections, "build_best_bets", lambda rows, *a, **k: _plays())
    monkeypatch.setattr(MF, "today_eastern", lambda: __import__("datetime").date(2026, 10, 5))


def _app():
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.session_state["sport"] = "NFL"
    return at


def _text(at):
    return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption] + [c.value for c in at.code])


def test_monday_night_focuses_on_the_single_game_not_the_whole_week(patched):
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "Monday night — one game on the ticket: Falcons at Saints" in t
    assert "Kirk Cousins" in t and "Alvin Kamara" in t
    assert "Josh Allen" not in t and "Travis Kelce" not in t          # Sunday's game excluded
    assert not at.selectbox or all("Focus" != s.label for s in at.selectbox)   # single game: no picker


def test_default_book_shows_its_monday_promotions_with_picks(patched):
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [s for s in at.selectbox if s.label == "📖 Book"][0].value == "DraftKings"
    t = _text(at)
    assert "DraftKings promotions" in t
    assert "DraftKings — King of the End Zone" in t and "DraftKings — MNF SGP No Sweat" in t
    assert "50% Boost Every Gameday" in t
    assert "confirm" in t.lower()                                      # honesty about unverified terms
    promo_block = t.split("Who we like for it")[1]
    assert "Drake London" in promo_block and "yds/touch" in promo_block
    copy = at.code[-1].value
    assert "💰 DraftKings promotions" in copy and "Who we like" in copy and "📖 Prices/promotions: DraftKings" in copy
    assert "TD Jackpot" not in t                                       # FanDuel's, and Thursday-only


def test_switching_book_switches_the_promotions_and_unlisted_books_say_so(patched):
    at = _app()
    at.run()
    [s for s in at.selectbox if s.label == "📖 Book"][0].set_value("FanDuel")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "FanDuel promotions" in t and "Free Full-Game Injury Protection" in t
    assert "DraftKings — King of the End Zone" not in t and "FanDuel — King of the End Zone" not in t
    assert "TD Jackpot" not in t                                       # Thursday-only promo, today is Monday
    [s for s in at.selectbox if s.label == "📖 Book"][0].set_value("Hard Rock Bet")
    at.run()
    assert not at.exception
    assert any("No Hard Rock Bet promotions on file" in i.value and "DraftKings" in i.value for i in at.info)


def test_pickem_book_prices_from_a_sportsbook_and_explains(patched):
    at = _app()
    at.run()
    [s for s in at.selectbox if s.label == "📖 Book"][0].set_value("PrizePicks")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("PrizePicks" in c.value and "DraftKings prices" in c.value for c in at.caption)


def test_sgp_promo_suggests_one_leg_per_player_in_the_game(patched):
    at = _app()
    at.run()
    t = _text(at)
    sgp = t.split("MNF SGP No Sweat")[1].split("50% Boost")[0]
    assert "Who we like for it — Falcons at Saints" in sgp
    assert "Pass Attempts Over" in sgp or "Anytime TD" in sgp


def test_multi_game_day_offers_a_picker_and_breakdown_and_focus_filters(patched, monkeypatch):
    monkeypatch.setattr(MF, "today_eastern", lambda: __import__("datetime").date(2026, 10, 4))
    meta = _meta() + [{"label": "DAL @ NYG", "game_date": "2026-10-04T20:25:00+00:00"}]
    plays = _plays() + [_p("CeeDee Lamb", "DAL", "DAL @ NYG", "2026-10-04T20:25:00+00:00",
                           "Anytime TD", .44, 1.6, rec_yds=80, rec=7)]
    monkeypatch.setattr(nfl_engine, "build_slate", lambda d: ([], meta))
    monkeypatch.setattr(nfl_projections, "build_best_bets", lambda rows, *a, **k: plays)
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "Sunday afternoon — 2 games on the ticket" in t
    assert "Josh Allen" in t and "CeeDee Lamb" in t and "Drake London" not in t   # Monday's game excluded
    assert "Chiefs at Bills" in t and "Cowboys at Giants" in t                    # per-game sections
    assert [s.label for s in at.selectbox][:3] == ["📖 Book", "Time slot", "Game"]
    game = [s for s in at.selectbox if s.label == "Game"][0]
    assert game.options[0] == "All games in this slot"
    assert game.options[1:] == ["1:00 PM ET — KC @ BUF", "4:25 PM ET — DAL @ NYG"]
    game.set_value("DAL @ NYG")
    at.run()
    assert not at.exception
    t2 = _text(at)
    assert "CeeDee Lamb" in t2 and "Josh Allen" not in t2


def test_no_games_on_date_explains_where_games_are(patched, monkeypatch):
    monkeypatch.setattr(MF, "today_eastern", lambda: __import__("datetime").date(2026, 10, 7))
    at = _app()
    at.run()
    assert not at.exception
    assert any("No games on this date" in i.value for i in at.info)
    assert any("2026-10-04" in c.value and "2026-10-05" in c.value for c in at.caption)


def test_owner_can_add_a_custom_promotion_for_the_selected_book(patched):
    at = _app()
    at.run()
    [s for s in at.selectbox if s.label == "📖 Book"][0].set_value("FanDuel")
    at.run()
    [t for t in at.text_input if t.label == "Promotion name"][0].set_value("TD Boost")
    [s for s in at.selectbox if s.label.startswith("What kind")][0].set_value("anytime_td")
    [b for b in at.button if b.label == "Add promotion"][0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [(p["book"], p["name"]) for p in at.session_state["custom_promos"]] == [("fanduel", "TD Boost")]
    assert "FanDuel — TD Boost" in _text(at)
    [s for s in at.selectbox if s.label == "📖 Book"][0].set_value("DraftKings")
    at.run()
    assert "TD Boost" not in _text(at)                                  # belongs to FanDuel only


def test_time_slot_filter_narrows_the_game_list(patched, monkeypatch):
    monkeypatch.setattr(MF, "today_eastern", lambda: __import__("datetime").date(2026, 10, 4))
    meta = [{"label": "KC @ BUF", "game_date": SUN}, {"label": "SEA @ LAR", "game_date": "2026-10-05T00:20:00+00:00"}]
    plays = [_p("Travis Kelce", "KC", "KC @ BUF", SUN, "Anytime TD", .48, 1.8, rec_yds=60, rec=6),
             _p("Kenneth Walker", "SEA", "SEA @ LAR", "2026-10-05T00:20:00+00:00", "Anytime TD", .45, 1.6,
                rush_yds=70, car=15)]
    monkeypatch.setattr(nfl_engine, "build_slate", lambda d: ([], meta))
    monkeypatch.setattr(nfl_projections, "build_best_bets", lambda rows, *a, **k: plays)
    at = _app()
    at.run()
    slot = [s for s in at.selectbox if s.label == "Time slot"][0]
    assert slot.options == ["All slate", "Afternoon", "Late"]
    slot.set_value("Late")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [s for s in at.selectbox if s.label == "Game"][0].options == ["All games in this slot", "8:20 PM ET — SEA @ LAR"]
    t = _text(at)
    assert "Kenneth Walker" in t and "Travis Kelce" not in t


def test_podcast_studio_builds_tonights_show_from_the_one_game(patched):
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "22_Podcast_Studio.py"), default_timeout=90)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "TONIGHT'S TICKET: Monday night — one game on the ticket: Falcons at Saints" in t
    assert "Josh Allen" not in t and "1 game tonight" in t


def test_mlb_board_is_priced_for_the_selected_book_and_games_filter_by_time(monkeypatch):
    import best_bets_data as BBD
    import statcast_data as SC
    calls = []
    meta = [{"label": "NYY @ BOS", "game_date": "2026-06-10T17:05:00Z"},
            {"label": "LAD @ SF", "game_date": "2026-06-10T23:45:00Z"}]
    plays = [{"Player": "Aaron Judge", "PlayerId": 1, "Team": "NYY", "Game": "NYY @ BOS", "Opp": "Sale",
              "GameDate": "2026-06-10T17:05:00Z", "Market": "Batter HR", "Side": "Over", "Line": 0.5,
              "ModelProb": .3, "Fair": 230, "Conviction": 1.8, "Why": "hot bat", "RealPrice": None,
              "PriceSource": "model_fair", "_game_log": []},
             {"Player": "Shohei Ohtani", "PlayerId": 2, "Team": "LAD", "Game": "LAD @ SF", "Opp": "Webb",
              "GameDate": "2026-06-10T23:45:00Z", "Market": "Batter HR", "Side": "Over", "Line": 0.5,
              "ModelProb": .32, "Fair": 210, "Conviction": 1.9, "Why": "hot bat", "RealPrice": None,
              "PriceSource": "model_fair", "_game_log": []}]

    def fake_board(date_str, fip, odds_api_key=None, preferred_book="draftkings", **k):
        calls.append(preferred_book)
        return [], meta, plays, []

    monkeypatch.setattr(BBD, "build_mlb_board", fake_board)
    monkeypatch.setattr(SC, "load_cached", lambda: (None, None))
    monkeypatch.setattr(MF, "today_eastern", lambda: __import__("datetime").date(2026, 6, 10))
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.session_state["sport"] = "MLB"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert calls[-1] == "draftkings" and "Aaron Judge" in _text(at) and "Shohei Ohtani" in _text(at)
    [s for s in at.selectbox if s.label == "📖 Book"][0].set_value("FanDuel")
    [s for s in at.selectbox if s.label == "Time slot"][0].set_value("Evening")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert calls[-1] == "fanduel"                                        # the board is rebuilt for that book
    t = _text(at)
    assert "Shohei Ohtani" in t and "Aaron Judge" not in t
    assert any("No FanDuel promotions on file for MLB" in i.value for i in at.info)


def _pool():
    """The wider TD field: every player with the market, including low-chance ones best-bets drops."""
    mnf = "ATL @ NO"
    def row(name, team, prob, ypt_rec_yds, rec, tgt, tds=0):
        log = [{"receiving_yards": ypt_rec_yds, "receptions": rec, "targets": tgt, "carries": 0, "rushing_yards": 0,
                "receiving_tds": tds, "rushing_tds": 0}] * 3
        p = _p(name, team, mnf, MNF, "Anytime TD", prob, round(prob / .3, 2))
        p.update({"_game_log": log, "_pool_only": True})
        return p
    return [row("Drake London", "ATL", .286, 65, 4, 6), row("Jahan Dotson", "ATL", .286, 11, 2, 3),
            row("Chris Olave", "NO", .429, 70, 9, 12, tds=1), row("Devaughn Vele", "NO", .429, 40, 5, 7, tds=1),
            row("Bijan Robinson", "ATL", .571, 40, 3, 4, tds=1)]


@pytest.fixture
def pooled(patched, monkeypatch):
    monkeypatch.setattr(nfl_projections, "build_td_pool", lambda rows, offers=None, preferred_book=None: _pool())


def test_king_of_the_end_zone_picks_use_the_whole_field_so_explosive_scoreless_receivers_appear(pooled):
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    block = _text(at).split("Who we like for it — Falcons at Saints")[1].split("Check a player")[0]
    assert "Drake London" in block                                     # no TD yet, but 16 yds/touch: now in the field
    assert all(block.index(n) < block.index("Jahan Dotson") for n in ("Drake London", "Bijan Robinson"))   # 5.5 yds/touch: last of five
    assert block.index("Bijan Robinson") < block.index("Drake London")  # still led by the likelier scorer


def test_player_check_ranks_the_player_in_his_game_with_caveats(pooled):
    at = _app()
    at.run()
    [t for t in at.text_input if t.label == "Player"][0].set_value("dotson")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "Jahan Dotson (ATL, WR) — Weak fit for King of the End Zone" in t and "of 5 in ATL @ NO" in t
    assert "Only 3 game(s) of data" in t and "No TD yet" in t
    assert "🔎 Player check" in at.code[-1].value and "Jahan Dotson" in at.code[-1].value
    [t for t in at.text_input if t.label == "Player"][0].set_value("vele")
    at.run()
    assert "Devaughn Vele (NO, WR) — " in _text(at) and "3 TD game(s)" in _text(at)


def test_player_check_handles_no_match_and_other_sports(pooled):
    at = _app()
    at.run()
    [t for t in at.text_input if t.label == "Player"][0].set_value("zzzz nobody")
    at.run()
    assert not at.exception
    assert any("No player matching" in w.value for w in at.warning)


def test_player_check_not_available_without_a_td_pool(patched, monkeypatch):
    monkeypatch.setattr(nfl_projections, "build_td_pool", lambda *a, **k: [])
    at = _app()
    at.run()
    [t for t in at.text_input if t.label == "Player"][0].set_value("vele")
    at.run()
    assert not at.exception
    assert any("player check isn't available" in i.value for i in at.info)


def test_player_check_ranks_only_within_the_players_own_game(pooled, monkeypatch):
    other = _pool()[0].copy()
    other.update({"Player": "Kenneth Walker", "Team": "SEA", "Game": "SEA @ LAR", "_game_log": _pool()[0]["_game_log"]})
    monkeypatch.setattr(nfl_projections, "build_td_pool",
                        lambda rows, offers=None, preferred_book=None: _pool() + [other])
    at = _app()
    at.run()
    [t for t in at.text_input if t.label == "Player"][0].set_value("dotson")
    at.run()
    assert "of 5 in ATL @ NO" in _text(at)                            # the SEA @ LAR player isn't counted


def test_nba_preseason_slate_shows_the_warning_and_the_last_season_note(monkeypatch):
    import nba_engine
    import nba_projections
    meta = [{"label": "Minnesota Timberwolves @ Indiana Pacers", "game_date": "2026-10-07T23:00:00Z"}]
    plays = [{"Player": "Tyrese Haliburton", "PlayerId": 1, "Team": "Indiana Pacers", "Game": meta[0]["label"],
              "Opp": "Minnesota Timberwolves", "GameDate": "2026-10-07T23:00:00Z", "Market": "Assists", "Side": "Over",
              "Line": 8.5, "ModelProb": .6, "Fair": -150, "Conviction": 1.4, "RealPrice": None,
              "PriceSource": "model_fair", "Why": "averaging 9.1 over his last 10 [7 of last 10 games are from last season]",
              "_game_log": []}]
    monkeypatch.setattr(nba_engine, "build_slate", lambda d: ([], meta))
    monkeypatch.setattr(nba_projections, "build_best_bets", lambda rows, *a, **k: plays)
    monkeypatch.setattr(MF, "today_eastern", lambda: __import__("datetime").date(2026, 10, 7))
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("NBA preseason" in i.value for i in at.info)
    assert "Tyrese Haliburton" in _text(at) and "7 of last 10 games are from last season" in _text(at)


# --- the independent ranking (td_evidence): season role, book price, injuries, spread/total ---------------
def _slate_rows():
    return [{"_pid": "g1", "Team": "ATL"}, {"_pid": "g2", "Team": "NO"}, {"_pid": "g3", "Team": "NO"}]


def _evidence_pool():
    mnf = "ATL @ NO"
    def pl(name, team, pid, price=None):
        p = _p(name, team, mnf, MNF, "Anytime TD", .3, 1.0, pid=pid)
        p.update({"_pool_only": True, "_stat_key": "scrimmage_tds", "RealPrice": price, "RealPriceBook": "draftkings" if price else None,
                  "PriceSource": "book" if price else "model_fair", "Position": "WR"})
        return p
    return [pl("Chris Olave", "NO", "g2", -120), pl("Rashid Shaheed", "NO", "g3", +250), pl("Drake London", "ATL", "g1", +150)]


def _season(tds, games=6, yds=80, rec=6):
    return [{"receiving_yards": yds, "receptions": rec, "targets": rec + 2, "carries": 0, "rushing_yards": 0,
             "receiving_tds": 1 if i < tds else 0, "rushing_tds": 0, "receiving_air_yards": 70} for i in range(games)]


@pytest.fixture
def evidence(patched, monkeypatch):
    import analyst_context as AC
    st_cache = __import__("streamlit")
    monkeypatch.setattr(nfl_engine, "build_slate", lambda d: (_slate_rows(), _meta()))
    monkeypatch.setattr(nfl_projections, "build_td_pool", lambda rows, offers=None, preferred_book=None: _evidence_pool())
    monkeypatch.setattr(nfl_engine, "get_season_logs", lambda d, pids: {"g1": _season(4), "g2": _season(5), "g3": _season(1, yds=20, rec=3)}, raising=False)
    monkeypatch.setattr(nfl_engine, "get_team_injuries_for_date", lambda t, d: [{"player": "Chris Olave", "status": "Out"}] if t == "NO" else [], raising=False)
    monkeypatch.setattr(AC, "load_game_env", lambda *a, **k: ({}, ""))
    st_cache.cache_data.clear()


def test_a_player_listed_out_is_not_picked_and_the_check_says_why(evidence):
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    block = _text(at).split("Who we like for it — Falcons at Saints")[1].split("Check a player")[0]
    assert "Drake London" in block and "Rashid Shaheed" in block
    assert "Chris Olave" not in block.split("MNF SGP No Sweat")[0]                  # Out: left out of King of the End Zone
    [t for t in at.text_input if t.label == "Player"][0].set_value("olave")
    at.run()
    t = _text(at)
    assert "Listed Out — not picked" in t and "left out of the ranking" in t


def test_each_pick_shows_where_its_number_comes_from(evidence):
    at = _app()
    at.run()
    t = _text(at)
    block = t.split("Who we like for it — Falcons at Saints")[1].split("MNF SGP No Sweat")[0]
    assert "Drake London (ATL)" in block and "season role" in block and "TDs in 4 of 6 game(s) this season" in block
    assert "book +150 at draftkings" in block and "yds/touch (season" in block
    assert "three shortest touchdown prices" in t


def test_a_missing_source_is_named_and_the_ranking_still_runs(evidence, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("feed down")
    monkeypatch.setattr(nfl_engine, "get_season_logs", boom, raising=False)
    monkeypatch.setattr(nfl_engine, "get_team_injuries_for_date", boom, raising=False)
    __import__("streamlit").cache_data.clear()
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "Heads up: season-long stats couldn't be loaded" in t and "the injury report couldn't be loaded" in t
    assert "Drake London" in t.split("Who we like for it — Falcons at Saints")[1]


def test_the_player_check_shows_the_book_and_role_numbers_and_says_when_there_is_no_price(evidence, monkeypatch):
    at = _app()
    at.run()
    [t for t in at.text_input if t.label == "Player"][0].set_value("shaheed")
    at.run()
    t = _text(at)
    assert "Rashid Shaheed (NO, WR)" in t and "book 26% after the hold, season role 19%" in t        # priced at +250
    assert "No sportsbook TD price was found" not in t
    unpriced = _evidence_pool()
    unpriced[1].update({"RealPrice": None, "RealPriceBook": None, "PriceSource": "model_fair"})
    monkeypatch.setattr(nfl_projections, "build_td_pool", lambda rows, offers=None, preferred_book=None: unpriced)
    __import__("streamlit").cache_data.clear()
    at = _app()
    at.run()
    [t for t in at.text_input if t.label == "Player"][0].set_value("shaheed")
    at.run()
    t = _text(at)
    assert "season role 19%, no book price" in t and "No sportsbook TD price was found" in t


def test_a_slate_with_no_player_rows_is_not_enriched_and_shows_no_source_notes(patched, monkeypatch):
    monkeypatch.setattr(nfl_projections, "build_td_pool", lambda rows, offers=None, preferred_book=None: _evidence_pool())
    monkeypatch.setattr(nfl_engine, "get_season_logs", lambda d, pids: pytest.fail("no rows, so nothing to enrich"), raising=False)
    __import__("streamlit").cache_data.clear()
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "Heads up: season-long" not in t and "three shortest touchdown prices" not in t
