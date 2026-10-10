"""analyst.py — the angle detectors, hidden-gem rule, scoreboard, weights and commentary."""
import pytest

import analyst as A


def play(**kw):
    p = {"Player": "Pat Player", "PlayerId": 1, "Team": "DAL", "Game": "TB @ DAL", "Market": "Pass Yards",
         "Side": "Over", "Line": 240.5, "ModelProb": 0.62, "Conviction": 1.2, "ConvictionSource": "model_typical",
         "Why": "w"}
    p.update(kw)
    return p


def ctx(**kw):
    c = {"sport_key": "NBA", "offer_index": {}, "odds_map": {}, "history_fn": None}
    c.update(kw)
    return c


# ------------------------------------------------------------------ market gap
def test_market_gap_needs_a_real_book_reference_and_a_five_point_gap():
    assert A.detect_market_gap(play(ConvictionSource="model_typical", Conviction=1.4), ctx()) is None
    r = A.detect_market_gap(play(ConvictionSource="book", ModelProb=0.66, Conviction=1.3), ctx())          # market 50.8%
    assert r and "model 66% vs market 51%" in r["evidence"] and 0.9 < r["strength"] <= 1.0
    assert A.detect_market_gap(play(ConvictionSource="book", ModelProb=0.60, Conviction=0.60 / 0.56), ctx()) is None   # a 4-pt gap
    edge = A.detect_market_gap(play(ConvictionSource="book", ModelProb=0.60, Conviction=0.60 / 0.54), ctx())          # a 6-pt gap
    assert edge and edge["strength"] == pytest.approx(0.06 / 0.15, abs=0.01)


# ------------------------------------------------------------------ soft book
def offer(point=240.5, over=None, under=None, player="Pat Player", market="player_pass_yds"):
    return {"market": market, "player": player, "point": point, "over": over or {}, "under": under or {}}


def soft_ctx(*offers):
    return ctx(offer_index=A.index_offers(list(offers)), odds_map={"Pass Yards": "player_pass_yds"})


def test_soft_book_fires_when_one_book_pays_well_above_the_median():
    o = offer(over={"draftkings": -110, "fanduel": -115, "betmgm": -112, "caesars": +105})
    r = A.detect_soft_book(play(), soft_ctx(o))
    assert r and "pays +105" in r["evidence"] and "median of 4 books" in r["evidence"]
    assert 0.4 < r["strength"] < 0.6


def test_soft_book_stays_quiet_without_enough_books_the_same_line_or_a_gap():
    assert A.detect_soft_book(play(), soft_ctx(offer(over={"draftkings": -110, "fanduel": +120}))) is None            # 2 books
    far = offer(point=250.5, over={"a": -110, "b": -115, "c": -112, "d": +105})
    assert A.detect_soft_book(play(), soft_ctx(far)) is None                                                         # different line
    flat = offer(over={"a": -110, "b": -111, "c": -110, "d": -109})
    assert A.detect_soft_book(play(), soft_ctx(flat)) is None
    assert A.detect_soft_book(play(), ctx()) is None                                                                 # no odds at all
    assert A.detect_soft_book(play(Market="Nope"), soft_ctx(flat)) is None                                           # market has no odds key


def test_soft_book_reads_the_under_side_for_an_under_play():
    o = offer(over={"a": -300, "b": -300, "c": -300}, under={"a": +200, "b": +205, "c": +260, "d": +201})
    r = A.detect_soft_book(play(Side="Under"), soft_ctx(o))
    assert r and "pays +260" in r["evidence"]


# ------------------------------------------------------------------ form run / role surge
def log(values, key="pass_yds"):
    return {"_stat_key": key, "_game_log": [{key: v} for v in values]}


def test_form_run_counts_the_last_eight_games_and_respects_log_order():
    oldest_first = log([200, 210, 250, 260, 270, 255, 262, 280, 290])           # last 8 games: 210 misses, the other 7 clear
    r = A.detect_form_run(play(**oldest_first), ctx(sport_key="NBA"))
    assert r and "cleared 240.5 in 7 of his last 8" in r["evidence"]
    newest_first = log(list(reversed([200, 210, 250, 260, 270, 255, 262, 280, 290])))
    assert A.detect_form_run(play(**newest_first), ctx(sport_key="NFL"))["evidence"].endswith("7 of his last 8")
    # same list read the wrong way round (as NBA/oldest-first) would see the recent games as 280,290... reversed
    mixed = log([300, 310, 100, 90, 95, 100, 98, 99, 101])
    assert A.detect_form_run(play(**mixed), ctx(sport_key="NBA")) is None


def test_form_run_needs_five_games_eighty_percent_and_a_real_edge():
    assert A.detect_form_run(play(**log([260, 270, 280, 290])), ctx()) is None
    assert A.detect_form_run(play(**log([260, 270, 100, 100, 280, 290])), ctx()) is None                              # 4/6
    assert A.detect_form_run(play(ModelProb=0.5, **log([260] * 6)), ctx()) is None
    under = A.detect_form_run(play(Side="Under", **log([200, 210, 190, 205, 220])), ctx())
    assert under and "stayed under 240.5 in 5 of his last 5" in under["evidence"]
    assert A.detect_form_run(play(), ctx()) is None                                                                    # no log


def test_role_surge_over_wants_a_bigger_recent_role_and_a_line_that_has_not_caught_up():
    base = [200, 205, 195, 200, 210]
    r = A.detect_role_surge(play(Line=225.5, **log(base + [290, 300, 285])), ctx())
    assert r and "last 3 games average 291.7 against 202.0" in r["evidence"]
    assert A.detect_role_surge(play(Line=280.5, **log(base + [290, 300, 285])), ctx()) is None                         # line already moved up
    assert A.detect_role_surge(play(Line=225.5, **log(base + [205, 210, 200])), ctx()) is None                          # no surge
    assert A.detect_role_surge(play(Line=225.5, **log([200, 205, 195, 290, 300])), ctx()) is None                       # too few games


def test_role_surge_under_mirrors_it():
    r = A.detect_role_surge(play(Side="Under", Line=225.5, **log([250, 260, 255, 250, 240, 150, 140, 160])), ctx())
    assert r and "last 3 games average 150.0" in r["evidence"]
    assert A.detect_role_surge(play(Side="Under", Line=150.5, **log([250, 260, 255, 250, 240, 150, 140, 160])), ctx()) is None


# ------------------------------------------------------------------ team / due / movement
def test_team_surge_pairs_hot_with_overs_and_cold_with_unders_and_cautions_the_reverse():
    hot = A.detect_team_surge(play(TeamTrend="📈 Hot", TeamTrendRatio=1.3), ctx())
    assert hot and "DAL is scoring above its own norm (x1.30)" in hot["evidence"]
    assert A.detect_team_surge(play(TeamTrend="📉 Cold", Side="Under", TeamTrendRatio=0.7), ctx())
    assert A.detect_team_surge(play(TeamTrend="📈 Hot", Side="Under"), ctx()) is None
    assert A.detect_team_surge(play(TeamTrend="➡️ Steady"), ctx()) is None
    assert any("below its own norm" in c for c in A.cautions_for(play(TeamTrend="📉 Cold"), ctx()))
    assert any("above its own norm" in c for c in A.cautions_for(play(TeamTrend="📈 Hot", Side="Under"), ctx()))


def test_regression_due_is_batter_hr_over_only():
    hr = play(Market="Batter HR", Due=0.03)
    assert A.detect_regression_due(hr, ctx())["strength"] == 1.0
    assert A.detect_regression_due(play(Market="Batter HR", Due=0.005), ctx()) is None
    assert A.detect_regression_due(play(Market="Batter HR", Due=0.03, Side="Under"), ctx()) is None
    assert A.detect_regression_due(play(Market="Batter Total Bases", Due=0.03), ctx()) is None


def history(prices, line=240.5, book="draftkings"):
    return lambda *a: [{"price": p, "line": line, "book": book} for p in prices]


def test_line_move_toward_the_side_fires_and_away_becomes_a_caution():
    toward = ctx(history_fn=history([-110, -125, -140]))
    r = A.detect_line_move(play(), toward)
    assert r and "moved" in r["evidence"] and "toward this side" in r["evidence"]
    away = ctx(history_fn=history([-140, -125, -110]))
    assert A.detect_line_move(play(), away) is None
    assert any("away from this side" in c for c in A.cautions_for(play(), away))
    assert A.detect_line_move(play(), ctx(history_fn=history([-110]))) is None                    # one snapshot is not a move
    assert A.detect_line_move(play(), ctx(history_fn=history([-110, -140], line=250.5))) is None  # a different line
    assert A.detect_line_move(play(), ctx()) is None                                               # no history at all


def test_a_broken_history_source_never_breaks_the_scan():
    def boom(*a):
        raise RuntimeError("db down")
    assert A.line_move_toward(play(), ctx(history_fn=boom)) is None


# ------------------------------------------------------------------ scan, gems, chalk
def board(n=12, **gem):
    """n filler plays with rising conviction in one market, plus any extras."""
    return [play(Player=f"F{i}", PlayerId=100 + i, Conviction=1.4 + i * 0.01, ModelProb=0.6) for i in range(n)]


def gem_play(**kw):
    p = play(Player="Gem", PlayerId=7, ConvictionSource="book", ModelProb=0.66, Conviction=1.3,
             TeamTrend="📈 Hot", TeamTrendRatio=1.3)
    p.update(kw)
    return p


def test_two_independent_angles_off_the_chalk_list_make_a_gem():
    calls = A.scan(board() + [gem_play()], "NBA", "2026-10-08")
    g = [c for c in calls if c["player"] == "Gem"][0]
    assert {a["angle"] for a in g["angles"]} == {"market_gap", "team_surge"}
    assert g["gem"] and not g["chalk"] and calls[0]["player"] == "Gem"          # gems sort first
    assert g["key"] == "NBA|2026-10-08|Gem|Pass Yards|Over"


def test_one_angle_is_not_a_gem_and_chalk_is_never_a_gem():
    one = A.scan(board() + [gem_play(TeamTrend="steady")], "NBA", "d")
    assert not [c for c in one if c["player"] == "Gem"][0]["gem"]
    top = A.scan(board() + [gem_play(Conviction=9.0)], "NBA", "d")               # conviction tops the day's list
    t = [c for c in top if c["player"] == "Gem"][0]
    assert t["chalk"] and not t["gem"]


def test_a_thin_market_has_no_chalk_so_nothing_is_called_overlooked_by_accident():
    calls = A.scan([gem_play()], "NBA", "d")
    assert not calls[0]["chalk"] and calls[0]["gem"]


def test_gems_need_a_real_probability_and_at_most_one_caution():
    low = A.scan(board() + [gem_play(ModelProb=0.54, Conviction=1.2)], "NBA", "d")
    assert not [c for c in low if c["player"] == "Gem"][0]["gem"]
    # market_gap + form_run agree; a cold team is one caution, a market moving away is a second
    base = dict(TeamTrend="steady", **log([300] * 6, key="pass_yds"))
    one = A.scan(board() + [gem_play(**{**base, "TeamTrend": "📉 Cold"})], "NBA", "d")
    g1 = [c for c in one if c["player"] == "Gem"][0]
    assert [a["angle"] for a in g1["angles"]] == ["market_gap", "form_run"] and len(g1["cautions"]) == 1 and g1["gem"]
    two = A.scan(board() + [gem_play(**{**base, "TeamTrend": "📉 Cold"})], "NBA", "d", history_fn=history([-140, -110]))
    g2 = [c for c in two if c["player"] == "Gem"][0]
    assert len(g2["cautions"]) == 2 and not g2["gem"] and len(g2["angles"]) == 2


def test_plays_without_angles_or_a_side_are_skipped_and_cautions_lower_the_score():
    plain = A.scan([play()], "NBA", "d")
    assert plain == []
    assert A.scan([play(Side=None)], "NBA", "d") == []
    clean = A.scan([gem_play()], "NBA", "d")[0]["score"]
    cautioned = A.scan([gem_play()], "NBA", "d", history_fn=history([-140, -110]))[0]["score"]
    assert cautioned < clean


def test_learned_weights_reorder_calls_but_never_touch_probabilities():
    a = gem_play(Player="A", PlayerId=1, TeamTrend="steady")                    # market_gap only
    b = gem_play(Player="B", PlayerId=2, ConvictionSource="model_typical", ModelProb=0.62)  # team_surge only
    flat = [c["player"] for c in A.scan([a, b], "NBA", "d")]
    boosted = A.scan([a, b], "NBA", "d", weights={"team_surge": 1.5, "market_gap": 0.5})
    assert [c["player"] for c in boosted][0] == "B" and flat[0] == "A"
    assert {c["player"]: c["model_prob"] for c in boosted} == {"A": 0.66, "B": 0.62}


def test_line_history_is_only_looked_up_for_the_top_plays():
    seen = []

    def hist(sport, player, market, side):
        seen.append(player)
        return []
    plays = [play(Player=f"P{i}", Conviction=1.0 + i) for i in range(10)]
    A.scan(plays, "NBA", "d", history_fn=hist, history_limit=3)
    assert sorted(seen) == ["P7", "P8", "P9"]


# ------------------------------------------------------------------ scoreboard / weights / reliability
def rows(n, hits, prob=0.6, angles=("market_gap",), gem=False):
    return [{"hit": 1 if i < hits else 0, "model_prob": prob, "angles": list(angles), "gem": gem} for i in range(n)]


def test_wilson_interval_is_sane():
    assert A.wilson(0, 0) == (None, None)
    lo, hi = A.wilson(50, 100)
    assert 0.40 < lo < 0.41 and 0.59 < hi < 0.60
    lo, hi = A.wilson(10, 10)
    assert hi == 1.0 and lo > 0.69


def test_scoreboard_refuses_to_claim_anything_below_the_sample_floor():
    b = {r["angle"]: r for r in A.scoreboard(rows(20, 18))}
    assert b["market_gap"]["status"] == "Collecting data (20/30)" and b["ALL"]["n"] == 20
    assert b["form_run"]["n"] == 0 and b["gem"]["n"] == 0


def test_scoreboard_statuses_follow_the_interval_against_the_stated_chance():
    beating = {r["angle"]: r for r in A.scoreboard(rows(200, 150, prob=0.55))}["market_gap"]
    assert beating["status"] == "Beating its stated odds" and beating["gap"] == pytest.approx(0.20)
    short = {r["angle"]: r for r in A.scoreboard(rows(200, 70, prob=0.60))}["market_gap"]
    assert short["status"] == "Falling short of its stated odds"
    ok = {r["angle"]: r for r in A.scoreboard(rows(60, 36, prob=0.60))}["market_gap"]
    assert ok["status"] == "Calibrated"
    noise = {r["angle"]: r for r in A.scoreboard(rows(40, 29, prob=0.60))}["market_gap"]       # 72.5% vs 60%, interval still spans it
    assert noise["status"] == "Within the noise"
    assert ok["brier"] == pytest.approx((36 * 0.16 + 24 * 0.36) / 60)


def test_voids_and_open_calls_are_excluded_and_gems_are_scored_separately():
    r = rows(10, 5, gem=True) + [{"hit": None, "model_prob": 0.9, "angles": ["market_gap"], "gem": True}]
    b = {x["angle"]: x for x in A.scoreboard(r)}
    assert b["ALL"]["n"] == 10 and b["gem"]["n"] == 10


def test_learned_weights_start_neutral_and_move_with_evidence_but_stay_bounded():
    assert set(A.learned_weights([]).values()) == {1.0}
    good = A.learned_weights(rows(300, 270, prob=0.55))["market_gap"]
    bad = A.learned_weights(rows(300, 60, prob=0.55))["market_gap"]
    small = A.learned_weights(rows(5, 5, prob=0.55))["market_gap"]
    assert good == 1.5 and bad == 0.5 and 1.0 < small < 1.5
    assert A.learned_weights(rows(300, 270, prob=0.55))["form_run"] == 1.0


def test_reliability_buckets_stated_vs_actual():
    r = rows(10, 5, prob=0.55) + rows(10, 8, prob=0.75)
    out = A.reliability(r)
    assert [o["bucket"] for o in out] == ["50%–60%", "70%–80%"]
    assert out[0]["actual"] == 0.5 and out[1]["actual"] == 0.8 and out[0]["stated"] == pytest.approx(0.55)


# ------------------------------------------------------------------ game notes
def test_game_notes_flag_a_big_rest_gap_only():
    meta = [{"label": "A @ B", "home_name": "B", "away_name": "A", "home_rest": 10, "away_rest": 6},
            {"label": "C @ D", "home_name": "D", "away_name": "C", "home_rest": 7, "away_rest": 6},
            {"label": "E @ F", "home_name": "F", "away_name": "E", "home_rest": None, "away_rest": 7}, {}]
    n = A.game_notes(meta)
    assert n == {"A @ B": ["B has 4 more days of rest than A"]}


# ------------------------------------------------------------------ commentary
def test_commentary_is_honest_when_nothing_clears_a_bar():
    d = A.write_commentary([], sport_label="NFL", date_str="2026-10-08", n_games=2)
    assert "no play had a single angle" in d["overview"] and d["focus"] == [] and d["games"] == []
    assert "1 game" in A.write_commentary([], sport_label="NFL", date_str="d", n_games=1)["overview"]


def test_commentary_restates_only_numbers_from_the_calls_and_pluralizes():
    calls = A.scan(board() + [gem_play()], "NBA", "2026-10-08")
    d = A.write_commentary(calls, sport_label="NBA", date_str="2026-10-08", n_games=1, notes={"TB @ DAL": ["B has 4 more days of rest than A"]})
    assert "1 game on the slate" in d["overview"] and "hidden-gem candidate" in d["overview"]
    assert d["focus"] and "model 66% vs market 51%" in d["focus"][0]["text"]
    g = d["games"][0]
    assert g["game"] == "TB @ DAL" and "Gem" in g["text"] and "B has 4 more days of rest than A." in g["text"]
    assert d["facts"]["calls"][0]["gem"] is True and d["facts"]["game_notes"]
    again = A.write_commentary(calls, sport_label="NBA", date_str="2026-10-08", n_games=1)
    assert again["headline"] == d["headline"]                                   # deterministic wording


def test_commentary_carries_the_track_record_into_the_facts_when_there_is_one():
    calls = A.scan([gem_play()], "NBA", "d")
    d = A.write_commentary(calls, sport_label="NBA", date_str="d", n_games=1, board=A.scoreboard(rows(40, 28, prob=0.6)))
    tr = d["facts"]["track_record"]
    assert tr[0]["angle"] == "All published calls" and tr[0]["settled_calls"] == 40
    assert "track_record" not in A.write_commentary(calls, sport_label="NBA", date_str="d", n_games=1)["facts"]


# ------------------------------------------------------------------ the optional language-model layer
class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._b = status, body if body is not None else {}

    def json(self):
        return self._b


def test_llm_sends_only_the_facts_and_returns_the_text():
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json)
        return Resp(200, {"content": [{"type": "text", "text": "Good evening."}, {"type": "text", "text": " Here we go."}]})
    out = A.llm_commentary({"calls": [1]}, "KEY", model="m-1", post=post)
    assert out == "Good evening. Here we go."
    assert sent["url"] == A.LLM_URL and sent["headers"]["x-api-key"] == "KEY" and sent["body"]["model"] == "m-1"
    assert "never add a stat" in sent["body"]["system"] and sent["body"]["messages"][0]["content"] == '{"calls": [1]}'


def test_llm_defaults_to_the_configured_model_name():
    seen = {}
    A.llm_commentary({}, "K", post=lambda *a, **k: seen.update(m=k["json"]["model"]) or Resp(200, {"content": [{"type": "text", "text": "x"}]}))
    assert seen["m"] == A.LLM_DEFAULT_MODEL


@pytest.mark.parametrize("resp,expect", [
    (Resp(401, {"error": {"message": "invalid x-api-key"}}), "answered 401: invalid x-api-key"),
    (Resp(529, {}), "answered 529"),
    (Resp(400, {"error": {"message": "bad model"}}), "answered 400: bad model"),
    (Resp(200, {"content": []}), "returned no text"),
])
def test_llm_failures_say_why(resp, expect):
    with pytest.raises(RuntimeError) as e:
        A.llm_commentary({}, "KEY", post=lambda *a, **k: resp)
    assert expect in str(e.value)


def test_llm_with_no_key_or_no_network_says_why():
    with pytest.raises(RuntimeError, match="no Anthropic API key"):
        A.llm_commentary({}, "")

    def down(*a, **k):
        raise ConnectionError("blocked")
    with pytest.raises(RuntimeError, match="could not reach the Anthropic API"):
        A.llm_commentary({}, "KEY", post=down)


def test_facts_hash_is_stable_and_changes_with_content():
    assert A.facts_hash({"a": 1, "b": 2}) == A.facts_hash({"b": 2, "a": 1}) != A.facts_hash({"a": 1, "b": 3})


# ------------------------------------------------------------------ game times: slot + kickoff
def test_time_info_buckets_by_eastern_start_and_marks_unknown_times():
    aft = A.time_info("2026-10-10T17:00:00Z")                      # 1:00 PM ET
    eve = A.time_info("2026-10-10T23:30:00Z")                      # 7:30 PM ET
    late = A.time_info("2026-10-11T01:00:00Z")                     # 9:00 PM ET
    assert (aft["slot"], aft["kickoff"]) == ("Afternoon", "1:00 PM ET")
    assert (eve["slot"], eve["kickoff"]) == ("Evening", "7:30 PM ET")
    assert (late["slot"], late["kickoff"]) == ("Late", "9:00 PM ET")
    assert A.time_info("2026-10-10T23:30:00Z", with_day=True)["kickoff"] == "Sat 7:30 PM ET"
    tbd = A.time_info("2026-10-10")                                # a bare date is not a start time
    assert tbd == {"start": None, "slot": "TBD", "kickoff": "time TBD"}
    assert A.time_info(None)["slot"] == "TBD"


def test_game_times_covers_every_game_in_meta_and_chrono_key_orders_slots_then_starts():
    t = A.game_times([{"label": "B", "game_date": "2026-10-11T01:00:00Z"}, {"label": "A", "game_date": "2026-10-10T17:00:00Z"},
                      {"label": "C", "game_date": None}, {"game_date": "x"}])
    assert set(t) == {"A", "B", "C"}
    assert sorted(t, key=lambda g: A.chrono_key(t[g]["slot"], t[g]["start"])) == ["A", "B", "C"]      # afternoon, late, TBD last
    same_slot = [("2026-10-10T23:30:00Z", 1), ("2026-10-10T22:00:00Z", 1), ("2026-10-10T23:30:00Z", 5)]
    assert [x[1] for x in sorted(same_slot, key=lambda x: A.chrono_key("Evening", x[0], -x[1]))] == [1, 5, 1]


def test_scan_stamps_each_call_with_its_games_slot_and_kickoff():
    times = A.game_times([{"label": "TB @ DAL", "game_date": "2026-10-11T01:00:00Z"}])
    c = A.scan(board() + [gem_play()], "NBA", "d", times=times)[0]
    assert (c["slot"], c["kickoff"], c["start"]) == ("Late", "9:00 PM ET", "2026-10-11T01:00:00Z")
    via_play = A.scan([gem_play(GameDate="2026-10-10T17:00:00Z")], "NBA", "d")[0]            # no times map: read off the play
    assert (via_play["slot"], via_play["kickoff"]) == ("Afternoon", "1:00 PM ET")
    assert A.scan([gem_play()], "NBA", "d")[0]["slot"] == "TBD"


def test_commentary_lists_every_game_in_start_order_with_its_slot_even_with_no_call():
    times = A.game_times([{"label": "Late @ Game", "game_date": "2026-10-11T01:00:00Z"},
                          {"label": "Quiet @ Game", "game_date": "2026-10-10T17:00:00Z"},
                          {"label": "TB @ DAL", "game_date": "2026-10-10T23:30:00Z"},
                          {"label": "Unset @ Game", "game_date": None}])
    calls = A.scan(board() + [gem_play()], "NBA", "d", times=times)
    d = A.write_commentary(calls, sport_label="NBA", date_str="d", n_games=4, times=times)
    assert [(g["game"], g["slot"], g["kickoff"]) for g in d["games"]] == [
        ("Quiet @ Game", "Afternoon", "1:00 PM ET"), ("TB @ DAL", "Evening", "7:30 PM ET"),
        ("Late @ Game", "Late", "9:00 PM ET"), ("Unset @ Game", "TBD", "time TBD")]
    assert d["games"][0]["text"] == "No play clears an angle here." and "Gem" in d["games"][1]["text"]
    assert "(7:30 PM ET)" in d["focus"][0]["text"] and d["facts"]["calls"][0]["kickoff"] == "7:30 PM ET"
    assert set(A.SLOT_TITLES) == {"Afternoon", "Evening", "Late", "TBD"}


# ------------------------------------------------------------------ sportsbook: only lines the book really posts
OMAP = {"Pass Yards": "player_pass_yds"}


def idx(*offers):
    return A.index_offers(list(offers))


def test_book_status_posted_means_the_book_has_that_player_side_and_line():
    o = offer(over={"draftkings": -120, "fanduel": -110}, under={"draftkings": +100})
    s = A.book_status(play(), idx(o), OMAP, "draftkings")
    assert s == {"state": "posted", "price": -120.0, "lines": ["240.5"], "elsewhere": ["FanDuel"]}
    assert A.book_status(play(Side="Under"), idx(o), OMAP, "draftkings")["price"] == 100.0           # the other side is priced separately
    assert A.book_status(play(), idx(o), OMAP, "caesars")["state"] == "not_posted"                    # alias resolves to williamhill_us, which isn't there


def test_a_line_the_book_does_not_post_is_not_available_even_when_other_books_have_it():
    # the platform falls back to the LOWEST line posted anywhere, so a 0.5 can come from a book you aren't using
    other = offer(point=0.5, over={"fanduel": -150}, market="player_pass_yds")
    mine = offer(point=1.5, over={"draftkings": +110}, market="player_pass_yds")
    s = A.book_status(play(Line=0.5), idx(other, mine), OMAP, "draftkings")
    assert s["state"] == "other_line" and s["lines"] == ["1.5"] and s["price"] is None and s["elsewhere"] == ["FanDuel"]
    assert A.book_status(play(Line=1.5), idx(other, mine), OMAP, "draftkings")["state"] == "posted"


def test_book_status_not_posted_names_where_it_can_be_found_and_unverified_means_no_props():
    o = offer(over={"fanduel": -110, "betmgm": -105})
    s = A.book_status(play(), idx(o), OMAP, "draftkings")
    assert s["state"] == "not_posted" and s["elsewhere"] == ["BetMGM", "FanDuel"]
    assert A.book_status(play(), {}, OMAP, "draftkings")["state"] == "unverified"
    assert A.book_status(play(Market="Nope"), idx(o), OMAP, "draftkings")["state"] == "unverified"       # a market with no odds key can't be checked
    assert A.book_status(play(), idx(o), OMAP, None)["state"] == "unchecked"


def test_a_pickem_book_counts_when_it_posts_the_line():
    o = offer(over={"draftkings": -110})
    o["pickem"] = {"prizepicks": {"over": {"price": None}, "under": {"price": None}}}
    assert A.book_status(play(), idx(o), OMAP, "prizepicks")["state"] == "posted"


def test_status_text_reads_plainly():
    assert A.status_text({"book_state": "posted"}, "DraftKings") == "Posted"
    assert A.status_text({"book_state": "other_line", "book_lines": ["1.5", "2.5"]}, "DraftKings") == "DraftKings posts 1.5, 2.5 instead"
    assert A.status_text({"book_state": "not_posted", "book_elsewhere": ["FanDuel"]}, "DraftKings") == "Not posted at DraftKings (at FanDuel)"
    assert A.status_text({"book_state": "not_posted", "book_elsewhere": []}, "DraftKings") == "Not posted at DraftKings"
    assert A.status_text({"book_state": "unverified"}, "DraftKings") == "No props posted yet"
    assert A.status_text({"book_state": "unchecked"}) == ""


def test_scan_with_a_book_prices_the_call_at_that_book_and_flags_what_is_bettable():
    mine = offer(player="Gem", over={"draftkings": -125, "fanduel": -105})
    off = offer(player="Away", over={"fanduel": -105})
    g, a = gem_play(), gem_play(Player="Away", PlayerId=8)
    calls = {c["player"]: c for c in A.scan([g, a], "NBA", "d", offers=[mine, off], odds_map=OMAP, book="draftkings")}
    assert calls["Gem"]["bettable"] and calls["Gem"]["price"] == -125 and calls["Gem"]["price_book"] == "draftkings"
    assert not calls["Away"]["bettable"] and calls["Away"]["price"] is None and calls["Away"]["book_state"] == "not_posted"
    nothing = {c["player"]: c for c in A.scan([g], "NBA", "d", offers=[], odds_map=OMAP, book="draftkings")}
    assert nothing["Gem"]["book_state"] == "unverified" and not nothing["Gem"]["bettable"]
    free = A.scan([g], "NBA", "d")[0]                                                       # no book chosen: nothing is withheld
    assert free["bettable"] and free["book_state"] == "unchecked"


def test_soft_price_is_asked_about_the_selected_book_not_whichever_book_is_richest():
    o = offer(over={"draftkings": -115, "fanduel": -115, "betmgm": -112, "caesars": +110})
    assert A.detect_soft_book(play(), ctx(offer_index=idx(o), odds_map=OMAP))                         # nobody chosen: the rich book is named
    assert A.detect_soft_book(play(), ctx(offer_index=idx(o), odds_map=OMAP, book="draftkings")) is None   # DK is not the soft one
    rich = offer(over={"draftkings": +115, "fanduel": -115, "betmgm": -112, "caesars": -110})
    r = A.detect_soft_book(play(), ctx(offer_index=idx(rich), odds_map=OMAP, book="draftkings"))
    assert r and "DraftKings pays +115" in r["evidence"]
    assert A.detect_soft_book(play(), ctx(offer_index=idx(rich), odds_map=OMAP, book="williamhill_us")) is None   # the chosen book isn't in the quote set at all


def test_line_movement_only_counts_at_the_selected_book():
    def both(*a):
        return ([{"price": -110, "line": 240.5, "book": "fanduel"}, {"price": -150, "line": 240.5, "book": "fanduel"}]
                + [{"price": -110, "line": 240.5, "book": "draftkings"}, {"price": -111, "line": 240.5, "book": "draftkings"}])
    assert A.detect_line_move(play(), ctx(history_fn=both))                                    # no book: biggest move anywhere
    assert A.detect_line_move(play(), ctx(history_fn=both, book="draftkings")) is None         # DK barely moved
    assert A.detect_line_move(play(), ctx(history_fn=both, book="fanduel"))


def test_commentary_says_which_book_it_is_limited_to_and_what_it_left_out():
    calls = A.scan(board() + [gem_play()], "NBA", "d")
    d = A.write_commentary(calls, sport_label="NBA", date_str="d", n_games=1, book_label="DraftKings", not_offered=2)
    assert "limited to lines DraftKings actually posts; 2 more plays with angles are left out" in d["overview"]
    assert d["facts"]["sportsbook"] == "DraftKings" and "available at DraftKings at exactly the stated line" in d["facts"]["lines_note"]
    one = A.write_commentary(calls, sport_label="NBA", date_str="d", n_games=1, book_label="DraftKings", not_offered=1)
    assert "1 more play with angles is left out" in one["overview"] and "doesn't offer it" in one["overview"]
    none_up = A.write_commentary([], sport_label="NBA", date_str="d", n_games=1, book_label="DraftKings", lines_posted=False)
    assert "DraftKings has no player props posted for this slate yet" in none_up["overview"]
    assert "no props posted yet; no plays are listed" in none_up["facts"]["lines_note"]
    assert "every play listed" not in none_up["facts"]["lines_note"]
    assert "Suggestions are limited" not in A.write_commentary(calls, sport_label="NBA", date_str="d", n_games=1)["overview"]


def test_the_ai_is_told_not_to_leave_the_books_lines():
    assert "never suggest a different line, a different book" in A.LLM_SYSTEM


# ------------------------------------------------- why a book shows nothing (Build 231)
def test_player_names_are_matched_the_platform_way_so_suffixes_and_accents_do_not_hide_a_posted_prop():
    o = offer(player="Marvin Harrison Jr.", over={"draftkings": -115})
    assert A.book_status(play(Player="Marvin Harrison"), idx(o), OMAP, "draftkings")["state"] == "posted"
    o2 = offer(player="José Álvarez", over={"draftkings": -115})
    assert A.book_status(play(Player="Jose Alvarez"), idx(o2), OMAP, "draftkings")["state"] == "posted"
    assert A.book_status(play(Player="Marvin Harrison"), idx(offer(player="Someone Else", over={"draftkings": -115})),
                         OMAP, "draftkings")["state"] == "not_posted"          # still not a free-for-all


def _ev(eid, home, away, player, books, point=240.5):
    return {"market": "player_pass_yds", "player": player, "point": point, "event_id": eid, "home_team": home,
            "away_team": away, "over": {b: -110 for b in books}, "under": {b: -110 for b in books}}


def test_event_ids_for_game_matches_by_team_names_or_by_the_games_own_players():
    offs = [_ev("e1", "Notre Dame Fighting Irish", "Stanford Cardinal", "A QB", ["fanduel"]),
            _ev("e2", "Ohio State Buckeyes", "Texas Longhorns", "B QB", ["fanduel"])]
    assert A.event_ids_for_game("Stanford @ Notre Dame", [], offs) == {"e1"}               # teams only
    assert A.event_ids_for_game("Cardinal vs Irish", ["a qb"], offs) == {"e1"}             # a player name alone
    assert A.event_ids_for_game("Nobody @ Nowhere", [], offs) == set()
    assert A.event_ids_for_game("Stanford @ Ohio State", [], offs) == set()               # sharing one team is not the same game
    assert A.event_ids_for_game(None, [], None) == set()


def test_book_coverage_counts_each_books_props_for_the_games_asked_about():
    offs = [_ev("e1", "H", "A", "P1", ["fanduel", "betmgm"]), _ev("e1", "H", "A", "P2", ["fanduel"]),
            _ev("e2", "H2", "A2", "P3", ["draftkings"])]
    assert A.book_coverage(offs) == {"fanduel": 2, "betmgm": 1, "draftkings": 1}
    assert A.book_coverage(offs, {"e1"}) == {"fanduel": 2, "betmgm": 1}
    assert A.book_coverage(offs, set()) == {} and A.book_coverage(None) == {}
    pk = dict(_ev("e1", "H", "A", "P4", []), pickem={"prizepicks": {"over": {"price": 1}}})
    assert A.book_coverage([pk]) == {"prizepicks": 1}


def test_coverage_text_names_the_selected_book_first_and_says_when_it_has_nothing():
    cov = {"fanduel": 12, "betmgm": 7}
    none = A.coverage_text(cov, "draftkings", "Stanford @ Notre Dame")
    assert none.startswith("DraftKings has no player props posted for Stanford @ Notre Dame.")
    assert "FanDuel 12, BetMGM 7" in none and "pick one of them" in none
    some = A.coverage_text({"draftkings": 5, **cov}, "draftkings", "this slate")
    assert some == "Player props posted for this slate: DraftKings 5 · FanDuel 12, BetMGM 7"
    assert A.coverage_text({}, "draftkings", "x") == ""
    assert A.coverage_text(cov, None, "x") == "Player props posted for x: FanDuel 12, BetMGM 7"


def test_book_breakdown_counts_plays_by_what_the_book_does_with_them():
    cs = [{"book_state": "not_posted"}, {"book_state": "not_posted"}, {"book_state": "other_line"}, {}]
    bd = A.book_breakdown(cs)
    assert bd["not_posted"] == 2 and bd["other_line"] == 1 and bd["unchecked"] == 1 and bd["posted"] == 0


def test_plays_withheld_by_the_book_are_not_called_a_quiet_read():
    d = A.write_commentary([], sport_label="NCAA Football", date_str="2026-10-10", n_games=1, book_label="DraftKings",
                           not_offered=19, breakdown={"not_posted": 18, "other_line": 1},
                           coverage_note="DraftKings has no player props posted for X.",
                           withheld_games={"Stanford @ Notre Dame": 19})
    assert d["headline"] == "NCAA Football: nothing I can take at DraftKings for 2026-10-10"
    assert "quiet" not in d["headline"] + d["overview"] and "no play had a single angle" not in d["overview"]
    assert "19 plays have angles behind them, but none is available at DraftKings at the model's line." in d["overview"]
    assert "18 aren't posted at DraftKings at all; 1 is posted there at a different line." in d["overview"]
    assert "DraftKings has no player props posted for X." in d["overview"]
    one = A.write_commentary([], sport_label="S", date_str="d", n_games=1, book_label="DK", not_offered=1,
                             breakdown={"not_posted": 1}, withheld_games={"G": 1}, times={"G": A.time_info(None, False)})
    assert "1 play has angles behind it" in one["overview"] and "1 isn't posted at DK at all." in one["overview"]
    assert "1 play here has angles, but it isn't available at DK at the model's line." in one["games"][0]["text"]
    many = A.write_commentary([], sport_label="S", date_str="d", n_games=1, book_label="DK", not_offered=3,
                              withheld_games={"G": 3}, times={"G": A.time_info(None, False)})
    assert "3 plays here have angles, but they aren't available at DK" in many["games"][0]["text"]


def test_a_genuinely_quiet_day_is_still_called_quiet_and_a_book_with_no_props_keeps_its_own_wording():
    q = A.write_commentary([], sport_label="NBA", date_str="d", n_games=2, book_label="DraftKings", not_offered=0)
    assert q["headline"] == "NBA: a quiet read for d" and "no play had a single angle" in q["overview"]
    none_up = A.write_commentary([], sport_label="NBA", date_str="d", n_games=1, book_label="DraftKings",
                                 not_offered=4, lines_posted=False)
    assert "has no player props posted for this slate yet" in none_up["overview"] and "nothing I can take" not in none_up["headline"]
