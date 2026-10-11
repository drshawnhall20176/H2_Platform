"""analyst_context.py + the game-script / opponent-matchup angles: separate evidence from separate data."""
import pytest

import analyst as A
import analyst_context as AC
import odds_api as O


def play(**kw):
    p = {"Player": "Pat Player", "PlayerId": 1, "Team": "NYK", "Game": "BOS @ NYK", "Market": "Points",
         "Side": "Under", "Line": 24.5, "ModelProb": 0.62, "Conviction": 1.2, "ConvictionSource": "model_typical", "Why": "w"}
    p.update(kw)
    return p


def entry(home_spread=-12.0, total=None, pct=None):
    return {"home_name": "NYK", "away_name": "BOS", "home_spread": home_spread,
            "away_spread": None if home_spread is None else -home_spread, "total": total, "total_pct": pct}


def ctx(sport="NBA", env=None, matchups=None):
    return {"sport_key": sport, "offer_index": {}, "odds_map": {}, "history_fn": None,
            "game_env": {"BOS @ NYK": env} if env is not None else {}, "matchups": matchups or {}}


# ------------------------------------------------------------------ game script: basketball blowouts
def test_a_lopsided_basketball_game_points_starters_stats_under():
    r = A.detect_game_script(play(), ctx(env=entry(-12.0)))
    assert r and "NYK is a 12-point favorite" in r["evidence"] and "minutes" in r["evidence"]
    assert r["strength"] == pytest.approx(0.6)                      # 0.4 + (12 - 10) / 10


def test_the_blowout_line_is_ten_in_the_nba_fourteen_in_college_and_inclusive():
    assert A.detect_game_script(play(), ctx(env=entry(-10.0)))
    assert A.detect_game_script(play(), ctx(env=entry(-9.5))) is None
    assert A.detect_game_script(play(), ctx("NCAAMB", env=entry(-13.5))) is None
    assert A.detect_game_script(play(), ctx("NCAAMB", env=entry(-14.0)))
    assert A.detect_game_script(play(), ctx("WNBA", env=entry(-10.0)))


def test_the_blowout_rule_reads_the_favorites_side_the_stat_and_the_pick():
    assert A.detect_game_script(play(Team="BOS"), ctx(env=entry(-12.0))) is None          # the underdog's player
    assert A.detect_game_script(play(Team="XYZ"), ctx(env=entry(-12.0))) is None          # a team not in the game
    assert A.detect_game_script(play(Side="Over"), ctx(env=entry(-12.0))) is None         # it argues for the Under only
    assert A.detect_game_script(play(Market="Rebounds"), ctx(env=entry(-12.0)))           # any counting stat of a starter
    assert A.detect_game_script(play(Market="Pass Yards"), ctx(env=entry(-12.0))) is None  # a football stat in a basketball game
    assert A.detect_game_script(play(), ctx(env=entry(None))) is None                     # no spread posted


def test_a_play_with_no_game_environment_gets_no_script_angle():
    assert A.detect_game_script(play(), ctx(env=None)) is None
    c = ctx(env=entry(-12.0))
    c["game_env"] = {"Other @ Game": entry(-12.0)}
    assert A.detect_game_script(play(), c) is None


# ------------------------------------------------------------------ game script: totals
def test_a_high_total_favors_the_over_a_low_total_the_under_on_scoring_stats():
    hi = A.detect_game_script(play(Side="Over", Team="BOS"), ctx(env=entry(-3.0, total=232.5, pct=0.8)))
    assert hi and "game total of 232.5 is among the highest" in hi["evidence"] and hi["strength"] == pytest.approx(0.4)
    assert A.detect_game_script(play(Side="Over", Team="BOS"), ctx(env=entry(-3.0, total=232.5, pct=0.79))) is None
    top = A.detect_game_script(play(Side="Over", Team="BOS"), ctx(env=entry(-3.0, total=240, pct=1.0)))
    assert top["strength"] == pytest.approx(1.0)
    lo = A.detect_game_script(play(Side="Under", Team="BOS"), ctx(env=entry(-3.0, total=208.5, pct=0.2)))
    assert lo and "among the lowest" in lo["evidence"] and lo["strength"] == pytest.approx(0.4)
    assert A.detect_game_script(play(Side="Under", Team="BOS"), ctx(env=entry(-3.0, total=208.5, pct=0.21))) is None
    bottom = A.detect_game_script(play(Side="Under", Team="BOS"), ctx(env=entry(-3.0, total=200, pct=0.0)))
    assert bottom["strength"] == pytest.approx(1.0)


def test_the_total_rule_covers_scoring_stats_only_and_needs_a_ranked_total():
    e = entry(-3.0, total=240, pct=1.0)
    assert A.detect_game_script(play(Side="Over", Market="Assists", Team="BOS"), ctx(env=e))
    assert A.detect_game_script(play(Side="Over", Market="Threes Made", Team="BOS"), ctx(env=e))
    assert A.detect_game_script(play(Side="Over", Market="Rebounds", Team="BOS"), ctx(env=e)) is None
    assert A.detect_game_script(play(Side="Over", Team="BOS"), ctx(env=entry(-3.0, total=None, pct=1.0))) is None
    assert A.detect_game_script(play(Side="Over", Team="BOS"), ctx(env=entry(-3.0, total=240, pct=None))) is None
    assert A.detect_game_script(play(Side="Under", Team="BOS"), ctx(env=e)) is None       # a high total never argues for the Under


def test_both_rules_can_apply_and_the_strongest_sets_the_strength():
    r = A.detect_game_script(play(Side="Under"), ctx(env=entry(-14.0, total=205, pct=0.0)))
    assert "14-point favorite" in r["evidence"] and "among the lowest" in r["evidence"] and "; " in r["evidence"]
    assert r["strength"] == pytest.approx(1.0)                      # the total rule's 1.0 beats the spread rule's 0.8


# ------------------------------------------------------------------ game script: football
def fb(sport="NFL", **kw):
    return play(Market=kw.pop("Market", "Rush Yards"), Side=kw.pop("Side", "Over"), Team="NYK", **kw), sport


def test_a_football_favorite_runs_more_and_an_underdog_less():
    p, s = fb()
    r = A.detect_game_script(p, ctx(s, env=entry(-6.5)))
    assert r and "favorite — favorites run more" in r["evidence"] and r["strength"] == pytest.approx(0.4)
    assert A.detect_game_script(p, ctx(s, env=entry(-6.0))) is None
    assert A.detect_game_script(p, ctx(s, env=entry(-10.0)))["strength"] == pytest.approx(0.4 + 3.5 / 8)
    p, s = fb(Side="Under")
    r = A.detect_game_script(p, ctx(s, env=entry(6.5)))
    assert r and "6.5-point underdog — trailing teams run less" in r["evidence"] and r["strength"] == pytest.approx(0.4)
    assert A.detect_game_script(p, ctx(s, env=entry(6.0))) is None
    assert A.detect_game_script(fb(Side="Under", Market="Rush Attempts")[0], ctx(s, env=entry(8.0)))
    assert A.detect_game_script(fb(Side="Under")[0], ctx(s, env=entry(-8.0))) is None      # a favorite never argues for the Under here


def test_a_football_underdog_throws_more_and_a_big_favorite_throws_less():
    p, s = fb(Market="Pass Yards")
    r = A.detect_game_script(p, ctx(s, env=entry(7.0)))
    assert r and "7-point underdog — trailing teams throw more" in r["evidence"]
    assert r["strength"] == pytest.approx(0.4 + 0.5 / 8)
    assert A.detect_game_script(p, ctx(s, env=entry(6.0))) is None
    for market in ("Pass Attempts", "Pass Completions", "Receptions", "Receiving Yards"):
        assert A.detect_game_script(fb(Market=market)[0], ctx(s, env=entry(7.0))), market
    p, s = fb(Market="Receiving Yards", Side="Under")
    r = A.detect_game_script(p, ctx(s, env=entry(-10.0)))
    assert r and "10-point favorite — big favorites throw less" in r["evidence"] and r["strength"] == pytest.approx(0.4)
    assert A.detect_game_script(p, ctx(s, env=entry(-9.5))) is None
    assert A.detect_game_script(fb(Market="Pass Yards", Side="Under")[0], ctx(s, env=entry(7.0))) is None


def test_football_totals_apply_to_passing_markets_and_ncaaf_follows_the_nfl_rules():
    p, s = fb(Market="Pass Yards")
    assert A.detect_game_script(p, ctx(s, env=entry(0.0, total=55, pct=0.9)))
    assert A.detect_game_script(fb(Market="Rush Yards")[0], ctx(s, env=entry(0.0, total=55, pct=0.9))) is None
    assert A.detect_game_script(p, ctx("NCAAF", env=entry(7.0)))
    assert A.detect_game_script(fb(Side="Under")[0], ctx("NCAAF", env=entry(7.0)))


def test_sports_without_a_rule_get_no_script_angle():
    for sport in ("NHL", "MLB"):
        assert A.detect_game_script(play(Market="Points", Side="Under"), ctx(sport, env=entry(-12.0, total=200, pct=0.0))) is None


def test_a_script_that_points_the_other_way_is_a_caution_not_an_angle():
    over = play(Side="Over")
    cs = A.cautions_for(over, ctx(env=entry(-12.0)))
    assert any(c.startswith("game script points the other way: NYK is a 12-point favorite") for c in cs)
    assert not any("game script" in c for c in A.cautions_for(play(Side="Under"), ctx(env=entry(-12.0))))
    assert not any("game script" in c for c in A.cautions_for(over, ctx(env=entry(-3.0))))


# ------------------------------------------------------------------ opponent matchup
def mu(factor, allows=24.5, opp="BOS"):
    return {("patplayer", "Points"): {"factor": factor, "opp": opp, "allows": allows}}


def test_a_generous_opponent_backs_an_over_and_a_stingy_one_an_under():
    r = A.detect_matchup(play(Side="Over"), ctx(matchups=mu(1.125)))
    assert r and r["strength"] == pytest.approx(0.5)
    assert "BOS has allowed more of this stat than the typical opponent on the slate — 1.12x (24.5 per game)" in r["evidence"] \
        or "1.13x (24.5 per game)" in r["evidence"]
    assert A.detect_matchup(play(Side="Over"), ctx(matchups=mu(1.08)))
    assert A.detect_matchup(play(Side="Over"), ctx(matchups=mu(1.07))) is None
    r = A.detect_matchup(play(Side="Under"), ctx(matchups=mu(0.92)))
    assert r and "has allowed less of this stat" in r["evidence"]
    assert A.detect_matchup(play(Side="Under"), ctx(matchups=mu(0.93))) is None


def test_the_matchup_has_to_point_the_plays_way_and_exist():
    assert A.detect_matchup(play(Side="Over"), ctx(matchups=mu(0.8))) is None
    assert A.detect_matchup(play(Side="Under"), ctx(matchups=mu(1.3))) is None
    assert A.detect_matchup(play(Side="Over"), ctx(matchups={})) is None
    assert A.detect_matchup(play(Side="Over", Market="Assists"), ctx(matchups=mu(1.3))) is None     # a different stat
    assert A.detect_matchup(play(Side="Over", Player="Someone Else"), ctx(matchups=mu(1.3))) is None
    assert A.detect_matchup(play(Side="Over"), ctx(matchups={("patplayer", "Points"): {"factor": None}})) is None


def test_the_matchup_name_lookup_is_the_platforms_matcher_and_missing_details_are_left_out():
    m = {("patplayer", "Points"): {"factor": 1.3, "opp": None, "allows": None}}
    r = A.detect_matchup(play(Side="Over", Player="Pat Player Jr."), ctx(matchups=m))
    assert r and r["evidence"].startswith("the opponent has allowed more") and "per game" not in r["evidence"]
    assert r["strength"] == pytest.approx(1.0)                      # 0.30 / 0.25 clips at 1


def test_a_matchup_against_the_pick_is_a_caution_with_the_same_thresholds():
    assert any("BOS has been tough on this stat (0.92x" in c for c in A.cautions_for(play(Side="Over"), ctx(matchups=mu(0.92))))
    assert not any("tough" in c for c in A.cautions_for(play(Side="Over"), ctx(matchups=mu(0.93))))
    assert any("BOS has been generous on this stat (1.08x" in c for c in A.cautions_for(play(Side="Under"), ctx(matchups=mu(1.08))))
    assert not any("generous" in c for c in A.cautions_for(play(Side="Under"), ctx(matchups=mu(1.07))))
    assert not A.cautions_for(play(Side="Over"), ctx(matchups={("patplayer", "Points"): {"factor": None}}))
    cs = A.cautions_for(play(Side="Over"), ctx(matchups={("patplayer", "Points"): {"factor": 0.8, "opp": None}}))
    assert any("the opponent has been tough" in c for c in cs)


# ------------------------------------------------------------------ families and gems
def test_the_new_angles_are_registered_with_their_own_families():
    for name in ("game_script", "matchup"):
        assert name in A.ANGLES and name in A.DETECTORS
    assert A.ANGLE_FAMILY["game_script"] == "game environment" and A.ANGLE_FAMILY["matchup"] == "opponent defense"
    assert len({A.ANGLE_FAMILY["game_script"], A.ANGLE_FAMILY["matchup"], A.ANGLE_FAMILY["market_gap"]}) == 3


def gem_play(**kw):
    kw.setdefault("Side", "Under")
    return play(ModelProb=0.66, Conviction=1.3, ConvictionSource="book", **kw)


def test_scan_hands_the_game_environment_and_matchups_to_the_detectors_and_they_make_a_gem():
    calls = A.scan([gem_play()], "NBA", "2026-10-11", game_env={"BOS @ NYK": entry(-12.0)},
                   matchups={("patplayer", "Points"): {"factor": 0.85, "opp": "BOS", "allows": 20.0}})
    (c,) = calls
    assert [a["angle"] for a in c["angles"]] == ["market_gap", "game_script", "matchup"]
    assert c["gem"] and A.angle_families(c["angles"]) == {"his recent games", "game environment", "opponent defense"}


def test_without_the_new_evidence_the_same_play_is_not_a_gem():
    (c,) = A.scan([gem_play()], "NBA", "2026-10-11")
    assert [a["angle"] for a in c["angles"]] == ["market_gap"] and not c["gem"]


def test_one_caution_still_allows_a_gem_but_two_do_not():
    env = {"BOS @ NYK": entry(-12.0)}                               # a big favorite: argues against an Over
    good = {("patplayer", "Points"): {"factor": 1.2, "opp": "BOS", "allows": 20.0}}
    (c,) = A.scan([gem_play(Side="Over")], "NBA", "2026-10-11", game_env=env, matchups=good)
    assert [a["angle"] for a in c["angles"]] == ["market_gap", "matchup"] and len(c["cautions"]) == 1 and c["gem"]
    bad = {("patplayer", "Points"): {"factor": 0.8, "opp": "BOS", "allows": 20.0}}      # and a tough defense: a second caution
    (c,) = A.scan([gem_play(Side="Over")], "NBA", "2026-10-11", game_env=env, matchups=bad)
    assert [a["angle"] for a in c["angles"]] == ["market_gap"] and len(c["cautions"]) == 2 and not c["gem"]


# ------------------------------------------------------------------ build_game_env
def ev(home, away, spreads, total=None):
    return {"home_team": home, "away_team": away, "spreads": spreads, "total": total}


META = [{"label": "Boston Celtics @ New York Knicks", "home_name": "New York Knicks", "away_name": "Boston Celtics"}]


def test_the_environment_matches_slate_games_to_odds_events_by_both_teams():
    env = AC.build_game_env(META, [ev("New York Knicks", "Boston Celtics", {"New York Knicks": -7.5, "Boston Celtics": 7.5}, 221.5)], "NBA")
    e = env["Boston Celtics @ New York Knicks"]
    assert (e["home_spread"], e["away_spread"], e["total"], e["home_name"], e["away_name"]) == \
        (-7.5, 7.5, 221.5, "New York Knicks", "Boston Celtics")
    assert e["total_pct"] is None                                   # one game is not a slate


def test_one_posted_side_fills_in_the_other_and_a_missing_event_leaves_the_game_out():
    env = AC.build_game_env(META, [ev("New York Knicks", "Boston Celtics", {"Boston Celtics": 4.0})], "NBA")
    e = env["Boston Celtics @ New York Knicks"]
    assert e["home_spread"] == -4.0 and e["away_spread"] == 4.0
    env = AC.build_game_env(META, [ev("New York Knicks", "Boston Celtics", {"New York Knicks": -4.5})], "NBA")
    assert env["Boston Celtics @ New York Knicks"]["away_spread"] == 4.5
    env = AC.build_game_env(META, [ev("New York Knicks", "Boston Celtics", {})], "NBA")
    e = env["Boston Celtics @ New York Knicks"]
    assert e["home_spread"] is None and e["away_spread"] is None
    assert AC.build_game_env(META, [ev("Miami Heat", "Boston Celtics", {})], "NBA") == {}
    assert AC.build_game_env(META, [ev("Boston Celtics", "New York Knicks", {})], "NBA") == {}   # home and away must agree
    assert AC.build_game_env(META, [], "NBA") == {} and AC.build_game_env(META, None, "NBA") == {}
    assert AC.build_game_env([{"label": "x"}, {"home_name": "a", "away_name": "b"}], [ev("a", "b", {})], "NBA") == {}


def test_nfl_abbreviations_are_matched_to_the_odds_feeds_full_names_by_mascot():
    meta = [{"label": "PHI @ JAX", "home_name": "JAX", "away_name": "PHI"}]
    env = AC.build_game_env(meta, [ev("Jacksonville Jaguars", "Philadelphia Eagles",
                                      {"Jacksonville Jaguars": 3.5, "Philadelphia Eagles": -3.5}, 45.5)], "NFL")
    e = env["PHI @ JAX"]
    assert e["home_spread"] == 3.5 and e["away_spread"] == -3.5 and e["total"] == 45.5
    assert AC.names_match("NFL", "LA", "Los Angeles Rams") and AC.names_match("NFL", "wsh", "Washington Commanders")
    assert not AC.names_match("NFL", "XYZ", "Los Angeles Rams") and not AC.names_match("NFL", None, "Los Angeles Rams")
    assert not AC.names_match("NFL", "PHI", "Jacksonville Jaguars")
    assert AC.names_match("NCAAF", "Ohio State", "Ohio State Buckeyes") and not AC.names_match("NCAAF", "Ohio State", "Michigan Wolverines")


def test_the_total_rank_needs_four_games_and_is_the_share_at_or_below():
    metas = [{"label": f"A{i} @ H{i}", "home_name": f"H{i}", "away_name": f"A{i}"} for i in range(5)]
    evs = [ev(f"H{i}", f"A{i}", {}, t) for i, t in enumerate([220.0, 225.0, 230.0, 240.0, 235.0])]
    env = AC.build_game_env(metas[:4], evs[:4], "NBA")
    assert [env[m["label"]]["total_pct"] for m in metas[:4]] == [0.25, 0.5, 0.75, 1.0]
    env3 = AC.build_game_env(metas[:3], evs[:3], "NBA")
    assert all(e["total_pct"] is None for e in env3.values())              # three games is not a slate
    evs[1]["total"] = None                                                 # a game without a total is skipped, not ranked
    env = AC.build_game_env(metas, evs, "NBA")
    assert env[metas[1]["label"]]["total_pct"] is None
    assert env[metas[3]["label"]]["total_pct"] == 1.0 and env[metas[0]["label"]]["total_pct"] == 0.25
    evs[2]["total"] = None
    assert all(e["total_pct"] is None for e in AC.build_game_env(metas, evs, "NBA").values())    # only 3 totals left


# ------------------------------------------------------------------ matchup_index
def test_matchup_index_keys_by_platform_name_and_market_and_skips_rows_without_a_factor():
    idx = AC.matchup_index([
        {"Player": "Pat Player Jr.", "Market": "Points", "Matchup Factor": 1.2, "Opp": "BOS", "Opp Allows": 25.1},
        {"Player": "No Factor", "Market": "Points"},
        {"Player": "", "Market": "Points", "Matchup Factor": 1.1},
        {"Player": "No Market", "Matchup Factor": 1.1},
        {"Player": "Neutral", "Market": "Assists", "Matchup Factor": 1.0},
    ])
    assert idx == {("patplayer", "Points"): {"factor": 1.2, "opp": "BOS", "allows": 25.1},
                   ("neutral", "Assists"): {"factor": 1.0, "opp": None, "allows": None}}
    assert AC.matchup_index(None) == {}


# ------------------------------------------------------------------ loaders
class FakeBasketball:
    def __init__(self):
        self.seen = {}

    def build_slate(self, d):
        self.seen["slate"] = d
        return [{"Player": "P", "_opp_id": 7}, {"Player": "Q", "_opp_id": 7}, {"Player": "R", "_opp_id": 9}, {"Player": "S"}], []

    def get_team_recent_allowed_stats(self, oid, d):
        self.seen.setdefault("allowed", []).append((oid, d))
        return {"pts": oid}


class FakeProj:
    def __init__(self, board):
        self.board, self.seen = board, {}

    def build_hot_hand_board(self, rows, allowed):
        self.seen["bb"] = (rows, allowed)
        return self.board

    def build_ncaaf_hot_hand_board(self, rows, allowed):
        self.seen["cf"] = (rows, allowed)
        return self.board


BOARD = [{"Player": "P", "Market": "Points", "Matchup Factor": 1.2, "Opp": "BOS", "Opp Allows": 25.0}]


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_basketball_matchups_use_each_unique_opponent_once(sport):
    eng, proj = FakeBasketball(), FakeProj(BOARD)
    idx, note = AC.load_matchups(sport, "2026-10-11", eng, proj)
    assert note == "" and idx == {("p", "Points"): {"factor": 1.2, "opp": "BOS", "allows": 25.0}}
    assert eng.seen["allowed"] == [(7, "2026-10-11"), (9, "2026-10-11")] and eng.seen["slate"] == "2026-10-11"
    assert proj.seen["bb"][1] == {7: {"pts": 7}, 9: {"pts": 9}}


class FakeFootball:
    def __init__(self):
        self.calls = []

    def build_slate(self, d):
        return [{"Player": "P", "Opp": "BOS"}, {"Player": "Q", "Opp": "BOS"}, {"Player": "R", "Opp": "NYK"}, {"Player": "S"}], []

    def get_team_allowed_stats(self, team, d, n="unset"):
        self.calls.append((team, d, n))
        return {"rushing_yards": 100}


def test_nfl_uses_the_nfl_board_and_ncaaf_the_college_one_with_the_full_season_window():
    eng, proj = FakeFootball(), FakeProj(BOARD)
    idx, note = AC.load_matchups("NFL", "2026-10-11", eng, proj)
    assert note == "" and idx and eng.calls == [("BOS", "2026-10-11", "unset"), ("NYK", "2026-10-11", "unset")]
    assert "bb" in proj.seen and "cf" not in proj.seen
    eng, proj = FakeFootball(), FakeProj(BOARD)
    idx, note = AC.load_matchups("NCAAF", "2026-10-11", eng, proj)
    assert note == "" and idx and eng.calls == [("BOS", "2026-10-11", None), ("NYK", "2026-10-11", None)]
    assert "cf" in proj.seen and "bb" not in proj.seen


def test_sports_without_a_board_and_failing_sources_degrade_to_a_plain_note():
    assert AC.load_matchups("NHL", "2026-10-11", None, None) == ({}, "there is no opponent-matchup board for NHL")

    class Boom(FakeBasketball):
        def build_slate(self, d):
            raise RuntimeError("x" * 200)
    idx, note = AC.load_matchups("NBA", "2026-10-11", Boom(), FakeProj(BOARD))
    assert idx == {} and note.startswith("the opponent-matchup data couldn't be loaded (xxx") and len(note) < 140
    idx, note = AC.load_matchups("NBA", "2026-10-11", FakeBasketball(), FakeProj([]))
    assert idx == {} and note == "no opponent-matchup data is available for this slate yet"


def test_game_env_loader_reports_each_way_it_can_be_empty():
    assert AC.load_game_env("NBA", "d", META, None, "basketball_nba") == ({}, "no Odds API key is configured, so the game-script angle is off")
    seen = {}

    def fetch(d, key, sport=None):
        seen.update(d=d, key=key, sport=sport)
        return [ev("New York Knicks", "Boston Celtics", {"New York Knicks": -7.5}, 221.5)], {}
    env, note = AC.load_game_env("NBA", "2026-10-11", META, "KEY", "basketball_nba", fetch=fetch)
    assert note == "" and env["Boston Celtics @ New York Knicks"]["home_spread"] == -7.5
    assert seen == {"d": "2026-10-11", "key": "KEY", "sport": "basketball_nba"}

    def boom(*a, **k):
        raise RuntimeError("quota " + "y" * 200)
    env, note = AC.load_game_env("NBA", "d", META, "KEY", "basketball_nba", fetch=boom)
    assert env == {} and note.startswith("the game-lines fetch failed (quota yyy") and note.endswith("so the game-script angle is off")
    env, note = AC.load_game_env("NBA", "d", META, "KEY", "basketball_nba", fetch=lambda *a, **k: ([], {}))
    assert env == {} and note == "no game spreads or totals are posted yet, so the game-script angle is quiet"


# ------------------------------------------------------------------ odds_api additions
def test_parse_game_total_averages_the_over_line_across_books():
    ej = {"bookmakers": [
        {"markets": [{"key": "totals", "outcomes": [{"name": "Over", "point": 220.5}, {"name": "Under", "point": 220.5}]}]},
        {"markets": [{"key": "totals", "outcomes": [{"name": "Over", "point": 221.5}, {"name": "Under", "point": 221.5}]},
                     {"key": "spreads", "outcomes": [{"name": "Over", "point": 99}]}]}]}
    assert O.parse_game_total(ej) == 221.0
    assert O.parse_game_total({"bookmakers": []}) is None
    assert O.parse_game_total({"bookmakers": [{"markets": [{"key": "totals", "outcomes": [{"name": "Over"}]}]}]}) is None


def test_fetch_slate_game_lines_asks_once_per_event_for_spreads_and_totals(monkeypatch):
    asked = []
    monkeypatch.setattr(O, "fetch_events_all", lambda key, sport=None: [
        {"id": "e1", "commence_time": "2026-10-11T23:00:00Z", "home_team": "H1", "away_team": "A1"},
        {"id": "e2", "commence_time": "2026-10-11T23:30:00Z", "home_team": "H2", "away_team": "A2"},
        {"id": "e3", "commence_time": "2026-10-13T23:00:00Z", "home_team": "H3", "away_team": "A3"}])

    def fake(eid, key, markets, regions="us", sport=None, bookmakers=None):
        asked.append((eid, tuple(markets)))
        if eid == "e2":
            raise O.OddsAPIError("429")
        return {"home_team": "H1", "away_team": "A1", "bookmakers": [{"markets": [
            {"key": "spreads", "outcomes": [{"name": "H1", "point": -3.0}, {"name": "A1", "point": 3.0}]},
            {"key": "totals", "outcomes": [{"name": "Over", "point": 45.5}]}]}]}, {"remaining": "400"}
    monkeypatch.setattr(O, "fetch_event_props", fake)
    games, info = O.fetch_slate_game_lines("2026-10-11", "KEY", sport="americanfootball_nfl")
    assert asked == [("e1", ("spreads", "totals")), ("e2", ("spreads", "totals"))]
    assert games == [{"event_id": "e1", "home_team": "H1", "away_team": "A1", "commence_time": "2026-10-11T23:00:00Z",
                      "spreads": {"H1": -3.0, "A1": 3.0}, "total": 45.5}]
    assert info == {"events_total": 2, "events_fetched": 1, "remaining": "400"}


def test_the_pass_game_script_boundary_is_inclusive_at_six_and_a_half():
    p, s = fb(Market="Pass Yards")
    assert A.detect_game_script(p, ctx(s, env=entry(6.5)))
    assert A.detect_game_script(p, ctx(s, env=entry(6.4))) is None


def test_both_posted_spreads_are_kept_as_they_are_when_the_books_disagree_slightly():
    env = AC.build_game_env(META, [ev("New York Knicks", "Boston Celtics", {"New York Knicks": -7.5, "Boston Celtics": 7.0})], "NBA")
    e = env["Boston Celtics @ New York Knicks"]
    assert (e["home_spread"], e["away_spread"]) == (-7.5, 7.0)
