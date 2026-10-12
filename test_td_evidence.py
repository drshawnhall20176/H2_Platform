"""td_evidence.py — the independent read behind King of the End Zone, and its wiring into promotions / the NFL engine."""
import pandas as pd
import pytest

import nfl_engine as NE
import promotions as PR
import td_evidence as TE


def g(tds=0, yds=50, rec=5, car=0, tgt=7, air=60, rush=0):
    return {"receiving_yards": yds, "receptions": rec, "carries": car, "targets": tgt, "receiving_air_yards": air,
            "rushing_yards": rush, "receiving_tds": tds, "rushing_tds": 0}


def play(name="A Player", team="BUF", pos="WR", price=None, pid="p1", game="LA @ BUF", **kw):
    p = {"Player": name, "PlayerId": pid, "Team": team, "Game": game, "Position": pos, "Market": "Anytime TD", "Side": "Over",
         "ModelProb": 0.3, "RealPrice": price, "RealPriceBook": "draftkings" if price is not None else None,
         "PriceSource": "book" if price is not None else "model_fair", "_game_log": [g()] * 4}
    p.update(kw)
    return p


ENV = {"LA @ BUF": {"home_name": "BUF", "away_name": "LA", "home_spread": -3.0, "away_spread": 3.0, "total": 48.0, "total_pct": 0.5}}


# --- season_summary ---------------------------------------------------------
def test_a_short_log_is_pulled_toward_the_positions_typical_rate_not_toward_fifty_percent():
    s = TE.season_summary("WR", [g(tds=1), g(), g()], None)
    assert s["games"] == 3 and s["td_games"] == 1
    assert s["td_rate"] == pytest.approx((1 + 6 * 0.22) / (3 + 6))                  # 0.258, nowhere near 0.5
    assert TE.season_summary("RB", [], None)["td_rate"] == pytest.approx(0.30)       # no games: the position's rate
    assert TE.season_summary("XX", [], None)["td_rate"] == pytest.approx(0.15)       # unknown position


def test_many_games_let_his_own_rate_take_over():
    s = TE.season_summary("WR", [g(tds=1)] * 12 + [g()] * 8, None)
    assert s["td_rate"] == pytest.approx((12 + 6 * 0.22) / 26)


def test_yards_per_touch_is_shrunk_until_there_are_enough_touches():
    few = TE.season_summary("WR", [g(yds=107, rec=4)], None)                          # 26.8 raw on 4 touches
    assert few["ypt_raw"] == pytest.approx(26.75)
    assert few["ypt"] == pytest.approx((107 + 20 * 11.0) / (4 + 20)) and few["ypt"] < 14
    many = TE.season_summary("WR", [g(yds=120, rec=6)] * 10, None)
    assert many["ypt"] == pytest.approx((1200 + 20 * 11.0) / (60 + 20))
    assert TE.season_summary("WR", [], None)["ypt_raw"] is None


def test_depth_of_target_needs_the_air_yards_column_and_is_shrunk():
    s = TE.season_summary("WR", [g(tgt=10, air=150)] * 3, None)
    assert s["adot"] == pytest.approx((450 + 15 * 9.0) / (30 + 15))
    no_air = [{k: v for k, v in x.items() if k != "receiving_air_yards"} for x in [g()] * 3]
    assert TE.season_summary("WR", no_air, None)["adot"] is None


def test_the_recent_log_is_used_only_when_there_is_no_season_log():
    assert TE.season_summary("WR", [g()] * 6, [g(tds=1)] * 2)["src"] == "season"
    s = TE.season_summary("WR", None, [g(tds=1)] * 2)
    assert s["src"] == "recent" and s["games"] == 2
    assert TE.season_summary("WR", [], [])["games"] == 0


def test_a_rush_and_a_receiving_td_in_one_game_count_once_and_a_blank_is_not_a_crash():
    both = {"receiving_tds": 1, "rushing_tds": 1, "carries": 2, "receptions": 2}
    assert TE.season_summary("RB", [both, {}], None)["td_games"] == 1
    assert TE.season_summary("RB", [{"scrimmage_tds": 2}], None)["td_games"] == 1
    assert TE.season_summary("RB", [{"receiving_tds": None, "carries": float("nan")}], None)["games"] == 1


# --- team points / market / chance ------------------------------------------
def test_a_teams_implied_points_come_from_the_total_and_its_own_spread():
    assert TE.team_points(ENV["LA @ BUF"], "home") == pytest.approx(25.5)            # 24 + 1.5
    assert TE.team_points(ENV["LA @ BUF"], "away") == pytest.approx(22.5)
    assert TE.team_points(None, "home") is None and TE.team_points(ENV["LA @ BUF"], None) is None
    assert TE.team_points({"total": None, "home_spread": -3.0}, "home") is None
    assert TE.team_points({"total": 48.0, "home_spread": None}, "home") is None


def test_the_books_price_becomes_a_chance_less_the_hold():
    assert TE.market_chance(None) is None
    assert TE.market_chance(+150) == pytest.approx(0.4 / 1.10)
    assert TE.market_chance(-200) == pytest.approx((2 / 3) / 1.10)
    assert TE.market_chance(+100000) == 0.01 and TE.market_chance(-100000) == pytest.approx(0.9082, abs=1e-3)


def test_with_a_price_the_chance_is_sixty_percent_market_and_forty_role():
    s = {"td_rate": 0.30}
    c = TE.scoring_chance(s, +150, None)
    assert c["market"] == pytest.approx(0.4 / 1.1) and c["role"] == pytest.approx(0.30) and c["script"] == 1.0
    assert c["chance"] == pytest.approx(0.6 * (0.4 / 1.1) + 0.4 * 0.30)
    assert TE.scoring_chance(s, None, None)["chance"] == pytest.approx(0.30)          # no price: role alone


def test_a_high_scoring_game_lifts_and_a_low_one_trims_the_role_chance_within_bounds():
    s = {"td_rate": 0.30}
    hi, lo = TE.scoring_chance(s, None, 27.0), TE.scoring_chance(s, None, 15.0)
    assert hi["script"] == pytest.approx((27 / 22.5) ** 0.8) and hi["role"] > 0.30 > lo["role"]
    assert TE.scoring_chance(s, None, 60.0)["script"] == 1.25 and TE.scoring_chance(s, None, 5.0)["script"] == 0.8
    assert TE.scoring_chance({"td_rate": 5.0}, None, None)["role"] == 0.85                 # a role chance is capped…
    assert TE.scoring_chance({"td_rate": 0.0}, None, None)["role"] == 0.02                 # …and floored
    assert TE.scoring_chance({"td_rate": 0.0}, -100000, None)["chance"] == pytest.approx(0.6 * 0.9082 + 0.4 * 0.02, abs=1e-3)


# --- big-play index ---------------------------------------------------------
def test_big_play_index_is_neutral_at_eight_yards_and_clipped():
    assert TE.explosive_index("RB", {"ypt": 8.0}) == 1.0
    assert TE.explosive_index("RB", {"ypt": 40.0}) == 1.8 and TE.explosive_index("RB", {"ypt": 0.5}) == 0.5
    assert TE.explosive_index("QB", {"ypt": 30.0}) == 0.2


def test_pass_catchers_also_count_depth_of_target():
    deep = TE.explosive_index("WR", {"ypt": 8.0, "adot": 14.0})
    short = TE.explosive_index("WR", {"ypt": 8.0, "adot": 5.0})
    assert deep == pytest.approx(0.6 * 1.0 + 0.4 * (14 / 9)) and short < 1.0 < deep
    assert TE.explosive_index("WR", {"ypt": 8.0, "adot": None}) == 1.0
    assert TE.explosive_index("RB", {"ypt": 8.0, "adot": 20.0}) == 1.0                # a back's depth of target is not read


# --- evaluate / enrich ------------------------------------------------------
@pytest.mark.parametrize("status,out", [("Out", True), ("out", True), ("Doubtful", True), (" Doubtful ", True),
                                        ("Questionable", False), ("", False), (None, False)])
def test_only_out_and_doubtful_players_are_screened_out(status, out):
    assert TE.evaluate(play(), [g()] * 5, status, None)["out"] is out


def test_the_book_price_is_used_only_when_it_really_came_from_the_book():
    assert TE.evaluate(play(price=+150), [g()] * 5, None, None)["market"] is not None
    fake = play(price=None, RealPrice=-133, PriceSource="model_fair")                  # a model "fair" number is not the market
    ev = TE.evaluate(fake, [g()] * 5, None, None)
    assert ev["market"] is None and ev["price"] is None


def test_the_team_side_picks_the_right_spread():
    home = TE.evaluate(play(team="BUF"), [g()] * 5, None, ENV["LA @ BUF"])
    away = TE.evaluate(play(team="LA"), [g()] * 5, None, ENV["LA @ BUF"])
    assert home["points"] == pytest.approx(25.5) and away["points"] == pytest.approx(22.5)
    assert TE.evaluate(play(team="XYZ"), [g()] * 5, None, ENV["LA @ BUF"])["points"] is None


def test_enriching_a_pool_adds_the_read_without_touching_the_original():
    pool = [play(name="Puka Nacua", pid="a"), play(name="Davante Adams", pid="b")]
    out = TE.enrich_pool(pool, {"a": [g(tds=1)] * 4}, {"pukanacua": "Questionable", "davanteadams": "Out"}, ENV)
    assert "_td_ev" not in pool[0] and all("_td_ev" in p for p in out)
    assert out[0]["_td_ev"]["status"] == "Questionable" and out[0]["_td_ev"]["summary"]["src"] == "season"
    assert out[1]["_td_ev"]["out"] and out[1]["_td_ev"]["summary"]["src"] == "recent"   # no season log for him
    assert TE.enrich_pool(pool, None, None, None)[0]["_td_ev"]["status"] is None


def test_popular_names_are_the_shortest_prices_else_the_likeliest_and_never_an_injured_player():
    pool = TE.enrich_pool([play(name="Short", pid="a", price=-200), play(name="Mid", pid="b", price=+100),
                           play(name="Long", pid="c", price=+800), play(name="Hurt", pid="d", price=-400),
                           play(name="NoPrice", pid="e")], None, {"hurt": "Out"}, None)
    ids = TE.popular_ids(pool, 2)
    names = {p["Player"] for p in pool if id(p) in ids}
    assert names == {"Short", "Mid"}                                                    # Hurt has the shortest price but is Out
    assert "Long" not in {p["Player"] for p in pool if id(p) in TE.popular_ids(pool, 3)}


def test_the_evidence_text_names_each_source():
    ev = TE.evaluate(play(), [g(tds=1)] * 3 + [g()] * 3, None, ENV["LA @ BUF"])
    t = TE.evidence_text(ev)
    assert "TDs in 3 of 6 game(s) this season" in t and "yds/touch (season, 30 touches)" in t
    assert "7.0 targets/game" in t and "team implied ~" in t
    recent = TE.evaluate(play(), None, None, None)
    assert "(recent games only)" in TE.evidence_text(recent) and "team implied" not in TE.evidence_text(recent)


# --- load_context -----------------------------------------------------------
class FakeEngine:
    def __init__(self, logs=None, injuries=None, boom_logs=False, boom_inj=False):
        self.logs, self.injuries, self.boom_logs, self.boom_inj, self.calls = logs, injuries, boom_logs, boom_inj, []

    def get_season_logs(self, d, pids):
        self.calls.append(("logs", d, list(pids)))
        if self.boom_logs:
            raise RuntimeError("stats down")
        return self.logs or {}

    def get_team_injuries_for_date(self, team, d):
        self.calls.append(("inj", team))
        if self.boom_inj:
            raise RuntimeError("report down")
        return (self.injuries or {}).get(team, [])


ROWS = [{"_pid": "b", "Team": "BUF"}, {"_pid": "a", "Team": "LA"}, {"_pid": "b", "Team": "BUF"}, {"_pid": None, "Team": None}]


def test_the_context_loads_each_source_once_and_reports_nothing_when_all_is_well():
    eng = FakeEngine({"a": [g()]}, {"BUF": [{"player": "Josh Palmer", "status": "Out"}], "LA": []})
    logs, inj, env, notes = TE.load_context("NFL", "2026-10-12", eng, ROWS, [], "KEY", "americanfootball_nfl",
                                            env_loader=lambda *a: (ENV, ""))
    assert logs == {"a": [g()]} and inj == {"joshpalmer": "Out"} and env == ENV and notes == []
    assert ("logs", "2026-10-12", ["a", "b"]) in eng.calls                              # distinct ids, one call
    assert [c for c in eng.calls if c[0] == "inj"] == [("inj", "BUF"), ("inj", "LA")]


def test_each_failed_source_is_named_and_the_others_still_load():
    eng = FakeEngine(None, {"BUF": [{"player": "X Y", "status": "Out"}]}, boom_logs=True)
    logs, inj, env, notes = TE.load_context("NFL", "d", eng, ROWS, [], "KEY", "k", env_loader=lambda *a: (ENV, ""))
    assert logs == {} and inj == {"xy": "Out"} and env == ENV
    assert len(notes) == 1 and "season-long stats couldn't be loaded" in notes[0] and "last few games" in notes[0]
    eng = FakeEngine({"a": [g()]}, None, boom_inj=True)
    _, inj, _, notes = TE.load_context("NFL", "d", eng, ROWS, [], "KEY", "k", env_loader=lambda *a: (ENV, ""))
    assert inj == {} and notes == ["the injury report couldn't be loaded (report down), so nobody was screened out"]
    def boom_env(*a):
        raise RuntimeError("odds down")
    _, _, env, notes = TE.load_context("NFL", "d", FakeEngine({"a": [g()]}, {"BUF": [{"player": "P", "status": "Out"}]}),
                                       ROWS, [], "KEY", "k", env_loader=boom_env)
    assert env == {} and notes == ["the spreads and totals couldn't be loaded (odds down), so game script is left out"]


def test_empty_sources_say_so_in_plain_words():
    _, _, _, notes = TE.load_context("NFL", "d", FakeEngine({}, {}), ROWS, [], None, "k",
                                     env_loader=lambda *a: ({}, "no Odds API key is configured, so the game-script angle is off"))
    assert notes == ["season-long stats aren't available, so the ranking uses each player's last few games only",
                     "no injury report is posted yet, so nobody was screened out",
                     "no Odds API key is configured, so game script is left out"]


# --- the ranking in promotions ---------------------------------------------
LONGEST = {"kind": "longest_td"}


def _ranked(pool, n=5):
    return PR.promo_picks(pool, LONGEST, n=n)


def test_the_ranking_is_chance_times_big_play_and_skips_players_listed_out():
    big = [g(tds=2, yds=130, rec=6, air=130)] * 5                                      # a deep, productive receiver
    flat = [g(tds=2, yds=30, rec=6, air=30)] * 5                                       # same TD rate, short and slow
    pool = TE.enrich_pool([play(name="Deep", pid="a"), play(name="Short", pid="b"), play(name="Hurt", pid="c")],
                          {"a": big, "b": flat, "c": big}, {"hurt": "Out"}, None)
    picks = _ranked(pool)
    assert [p["play"]["Player"] for p in picks] == ["Deep", "Short"]
    assert picks[0]["score"] > picks[1]["score"] and picks[0]["kind"] == "longest_td"
    assert picks[0]["ypt"] == pool[0]["_td_ev"]["summary"]["ypt"]


def test_the_ranking_can_be_cut_to_n_and_tags_the_three_shortest_prices_as_popular():
    pool = TE.enrich_pool([play(name=f"P{i}", pid=str(i), price=p_) for i, p_ in enumerate((-300, -250, -200, 100, 300))], None, None, None)
    picks = _ranked(pool, n=4)
    assert len(picks) == 4 and _ranked(pool, n=0) == []
    chalk = {p["play"]["Player"] for p in _ranked(pool) if p["tag"] == "chalk"}
    assert chalk == {"P0", "P1", "P2"} and all(p["tag"] == "leverage" for p in _ranked(pool) if p["play"]["Player"] in ("P3", "P4"))


def test_plays_without_the_independent_read_keep_the_original_ranking():
    old = [dict(play(name="Likely", pid="a"), ModelProb=0.6), dict(play(name="Unlikely", pid="b"), ModelProb=0.2)]
    assert [p["play"]["Player"] for p in _ranked(old)] == ["Likely", "Unlikely"]
    assert "_td_ev" not in old[0]


def test_the_pick_line_says_where_each_number_comes_from():
    pool = TE.enrich_pool([play(name="Josh Allen", team="BUF", pid="a", price=-130)], {"a": [g(tds=1)] * 3 + [g()] * 3},
                          {"joshallen": "Questionable"}, ENV)
    line = PR.pick_line(_ranked(pool)[0])
    assert line.startswith("Josh Allen (BUF) · ~") and "to score (book -130 at draftkings, season role " in line
    assert "TDs in 3 of 6 game(s) this season" in line and "team implied ~26 pts" in line
    assert "injury report: Questionable" in line and "likely a popular name" in line
    nopr = TE.enrich_pool([play(name="No Price", pid="a")], None, None, None)
    assert "no book price found" in PR.pick_line(_ranked(nopr)[0]) and "(recent games only)" in PR.pick_line(_ranked(nopr)[0])


def test_check_a_player_reports_an_injury_and_ranks_the_others():
    pool = TE.enrich_pool([play(name="Hurt", pid="a", price=-150), play(name="Fine", pid="b", price=+120),
                           play(name="Doubt", pid="c")], None, {"hurt": "Out", "doubt": "Questionable"}, None)
    pf = PR.player_profile(pool[0], pool)
    assert pf["verdict"] == "Listed Out — not picked" and pf["rank"] is None and pf["status"] == "Out"
    assert any("left out of the ranking" in n for n in pf["notes"])
    fine = PR.player_profile(pool[1], pool)
    assert fine["rank"] in (1, 2) and fine["verdict"] in ("Strong fit", "Reasonable fit") and fine["market_prob"] is not None
    assert fine["prob"] == pool[1]["_td_ev"]["chance"] and fine["role_prob"] == pool[1]["_td_ev"]["role"]
    doubt = PR.player_profile(pool[2], pool)
    assert any("confirm he plays" in n for n in doubt["notes"]) and any("No sportsbook TD price" in n for n in doubt["notes"])
    lines = PR.profile_lines(fine)
    assert "after the hold, season role" in lines[1] and "to score a TD" in lines[1]
    assert "no book price" in PR.profile_lines(doubt)[1]


def test_check_a_player_flags_a_season_log_that_could_not_be_loaded():
    pool = TE.enrich_pool([play(name="Only Recent", pid="a", price=+100)], None, None, None)
    pf = PR.player_profile(pool[0], pool)
    assert any("Season-long stats weren't available" in n for n in pf["notes"])


# --- the NFL engine helpers -------------------------------------------------
@pytest.fixture
def season(monkeypatch):
    df = pd.DataFrame([
        {"player_id": "a", "week": 1, "receiving_yards": 10}, {"player_id": "a", "week": 2, "receiving_yards": 20},
        {"player_id": "a", "week": 3, "receiving_yards": 30}, {"player_id": "a", "week": 5, "receiving_yards": 50},
        {"player_id": "b", "week": 4, "receiving_yards": 40}, {"player_id": "z", "week": 1, "receiving_yards": 99}])
    monkeypatch.setattr(NE, "get_schedule", lambda s: "SCHED")
    monkeypatch.setattr(NE, "_resolve_week", lambda sched, d: 5)
    monkeypatch.setattr(NE, "load_season_weekly_stats", lambda s: df)
    return df


def test_season_logs_come_from_one_read_newest_first_strictly_before_the_slate_week(season):
    out = NE.get_season_logs("2026-10-12", ["a", "b", "nobody"])
    assert [r["week"] for r in out["a"]] == [3, 2, 1] and [r["week"] for r in out["b"]] == [4]   # week 5 is the game itself
    assert "z" not in out and "nobody" not in out


def test_season_logs_are_capped_per_player(season):
    assert [r["week"] for r in NE.get_season_logs("2026-10-12", ["a"], max_games=2)["a"]] == [3, 2]


def test_season_logs_are_empty_when_nothing_can_be_resolved(season, monkeypatch):
    assert NE.get_season_logs("2026-10-12", []) == {}
    assert NE.get_season_logs("not-a-date", ["a"]) == {}
    monkeypatch.setattr(NE, "_resolve_week", lambda sched, d: None)
    assert NE.get_season_logs("2026-10-12", ["a"]) == {}
    monkeypatch.setattr(NE, "_resolve_week", lambda sched, d: 5)
    monkeypatch.setattr(NE, "load_season_weekly_stats", lambda s: pd.DataFrame())
    assert NE.get_season_logs("2026-10-12", ["a"]) == {}


def test_injuries_are_read_for_the_week_the_date_falls_in(monkeypatch):
    seen = []
    monkeypatch.setattr(NE, "get_schedule", lambda s: "SCHED")
    monkeypatch.setattr(NE, "_resolve_week", lambda sched, d: 6)
    monkeypatch.setattr(NE, "get_team_injuries", lambda t, s, w: seen.append((t, s, w)) or [{"player": "X"}])
    assert NE.get_team_injuries_for_date("BUF", "2026-10-12") == [{"player": "X"}] and seen == [("BUF", 2026, 6)]
    assert NE.get_team_injuries_for_date("BUF", "bad") == []
    monkeypatch.setattr(NE, "_resolve_week", lambda sched, d: None)
    assert NE.get_team_injuries_for_date("BUF", "2026-10-12") == []


# --- gaps found by mutation testing ----------------------------------------
def test_popularity_follows_the_price_not_the_chance_when_they_disagree():
    # "Role Heavy" has the best season rate but a long price; "Chalk" has a short price and a thin season.
    pool = TE.enrich_pool([play(name="Role Heavy", pid="a", price=-110), play(name="Chalk", pid="b", price=-250),
                           play(name="Mid1", pid="c", price=+300), play(name="Mid2", pid="d", price=+400)],
                          {"a": [g(tds=6)] * 6, "b": [g()] * 6, "c": [g()] * 6, "d": [g()] * 6}, None, None)
    assert pool[0]["_td_ev"]["role"] > pool[1]["_td_ev"]["role"]                         # the season rate says Role Heavy…
    names = {p["Player"] for p in pool if id(p) in TE.popular_ids(pool, 1)}
    assert names == {"Chalk"}                                                          # …the crowd (the price) says Chalk


def test_an_injury_row_without_a_status_is_ignored_not_recorded_as_none():
    eng = FakeEngine({"a": [g()]}, {"BUF": [{"player": "No Status", "status": None}, {"player": "", "status": "Out"}]})
    _, inj, _, notes = TE.load_context("NFL", "d", eng, ROWS, [], "KEY", "k", env_loader=lambda *a: (ENV, ""))
    assert inj == {} and "no injury report is posted yet, so nobody was screened out" in notes


def test_the_ranking_is_sorted_best_first_whatever_order_the_pool_arrives_in():
    deep, mid, low = [g(tds=3, yds=120, rec=6, air=120)] * 6, [g(tds=2, yds=60, rec=6, air=60)] * 6, [g()] * 6
    pool = TE.enrich_pool([play(name="Low", pid="c"), play(name="Deep", pid="a"), play(name="Mid", pid="b")],
                          {"a": deep, "b": mid, "c": low}, None, None)
    assert [p["play"]["Player"] for p in _ranked(pool)] == ["Deep", "Mid", "Low"]


def test_the_check_reports_season_yards_per_touch_not_the_last_five_games():
    pool = TE.enrich_pool([play(name="Solo", pid="a", price=+200)], {"a": [g(yds=20, rec=5)] * 10}, None, None)
    pf = PR.player_profile(pool[0], pool)
    assert pf["ypt"] == pytest.approx(pool[0]["_td_ev"]["summary"]["ypt"]) and pf["games_used"] == 10


def test_an_empty_player_list_never_reads_the_season_stats(monkeypatch):
    monkeypatch.setattr(NE, "get_schedule", lambda s: pytest.fail("no players, nothing to read"))
    monkeypatch.setattr(NE, "load_season_weekly_stats", lambda s: pytest.fail("no players, nothing to read"))
    assert NE.get_season_logs("2026-10-12", []) == {}


def test_a_quarterback_who_scores_on_sneaks_does_not_beat_a_receiver_for_the_longest_td():
    qb = play(name="Sneak QB", pid="q", pos="QB", price=-300)
    wr = play(name="Deep WR", pid="w", price=+250)
    pool = TE.enrich_pool([qb, wr], {"q": [g(tds=1, yds=0, rec=0, car=6, rush=25)] * 6, "w": [g(tds=1, yds=90, rec=5, air=90)] * 6}, None, None)
    assert pool[0]["_td_ev"]["chance"] > pool[1]["_td_ev"]["chance"]                     # the QB is far likelier to score…
    assert [p["play"]["Player"] for p in _ranked(pool)] == ["Deep WR", "Sneak QB"]        # …and still ranks below the receiver


def test_check_a_player_tells_a_quarterbacks_owner_why_he_is_rated_low():
    pool = TE.enrich_pool([play(name="Sneak QB", pid="q", pos="QB", price=-300), play(name="Deep WR", pid="w", price=+250)], None, None, None)
    notes = PR.player_profile(pool[0], pool)["notes"]
    assert any("sneaks and goal-line runs" in n for n in notes)
    assert not any("sneaks" in n for n in PR.player_profile(pool[1], pool)["notes"])
