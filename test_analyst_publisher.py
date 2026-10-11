"""analyst_publisher.py — the scheduled Desk: lock, grade, post the card and the recap, each exactly once."""
from datetime import datetime, timedelta, timezone

import pytest
import pytz

import analyst as A
import analyst_ledger as AL
import analyst_publisher as PUB
import analyst_tools as AT
import sports

ET = pytz.timezone("US/Eastern")
HOOK = "https://discord.com/api/webhooks/1/abc"


def _iso(days, hour=19, minute=30):
    d = (datetime.now(ET) + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=None)
    return ET.localize(d).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(days=0):
    return (datetime.now(ET) + timedelta(days=days)).strftime("%Y-%m-%d")


def _gem(game="BOS @ NYK", when=None, name="Gem Guy", pid=7, market="Points"):
    return {"Player": name, "PlayerId": pid, "Team": "NYK", "Game": game, "GameDate": when or _iso(1), "Market": market,
            "Side": "Over", "Line": 20.5, "ModelProb": 0.66, "Conviction": 1.3, "ConvictionSource": "book",
            "TeamTrend": "📈 Hot", "TeamTrendRatio": 1.3, "RealPrice": -115, "RealPriceBook": "draftkings", "Why": "w"}


def _offers(plays, sport="NBA"):
    mm = sports.get(sport).market_map
    return [{"market": mm[p["Market"]], "player": p["Player"], "point": p["Line"], "over": {"draftkings": -115},
             "under": {"draftkings": 100}} for p in plays]


class Sender:
    def __init__(self, status=204):
        self.status, self.sent = status, []

    def __call__(self, url, json=None, timeout=None):
        self.sent.append(json["content"])

        class R:
            status_code = self.status
        return R()


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(AL, "DB_PATH", str(tmp_path / "ledger.db"))
    plays = [_gem()]
    state = {"plays": plays, "meta": [{"label": "BOS @ NYK", "game_date": _iso(1), "away_name": "BOS", "home_name": "NYK"}],
             "results": {}, "key": "KEY", "offers_error": None}

    def fetch_offers(sport, d, key):
        if state["offers_error"]:
            raise RuntimeError(state["offers_error"])
        return _offers(state["plays"], sport)
    deps = {"api_key": lambda: state["key"],
            "load_board": lambda sport, d, book: (state["plays"], state["meta"], ["draftkings"]),
            "fetch_offers": fetch_offers,
            "game_env": lambda *a: ({}, ""), "matchups": lambda *a: ({}, ""),
            "history_fn": lambda *a: [],
            "results": lambda sport, d: state["results"]}
    state["deps"] = deps
    return state


def go(env, post=True, send=None, hook=HOOK, today=None):
    send = send or Sender()
    r = PUB.publish_sport("NBA", today or _day(0), today or _day(0), env["deps"], book="draftkings", webhook=hook, post=post, send=send)
    return r, send


# ------------------------------------------------------------------ the card
def test_a_dry_run_shows_the_card_and_writes_and_sends_nothing(env):
    r, send = go(env, post=False)
    assert r["picks"] == "dry run" and r["locked"] == 0 and send.sent == []
    assert "Gem Guy" in r["text"]["picks"]
    assert AL.fetch_calls() == [] and not AL.posted("picks", "NBA", _day(0))


def test_posting_locks_the_call_posts_the_branded_card_and_stamps_it_published(env):
    r, send = go(env)
    assert r["picks"] == "posted" and r["locked"] == 1
    (text,) = send.sent
    assert "H2 Sports Media — Analyst Desk · NBA" in text and "Over 20.5 Points" in text and "Gem Guy" in text
    assert "Record fingerprint (1 locked calls to date)" in text and AT.DISCLAIMER in text and "DraftKings" in text
    (row,) = AL.fetch_calls()
    assert row["player"] == "Gem Guy" and row["published_at"] and row["gem"]
    assert AL.posted("picks", "NBA", _day(0))


def test_the_card_goes_out_once_even_if_the_job_runs_again(env):
    go(env)
    r, send = go(env)
    assert r["picks"] == "already posted" and r["locked"] == 0 and send.sent == []
    assert len(AL.fetch_calls()) == 1


def test_a_failed_post_gives_the_claim_back_so_the_next_run_retries(env):
    r, send = go(env, send=Sender(500))
    assert r["picks"] == "failed: Discord answered 500"
    assert not AL.posted("picks", "NBA", _day(0)) and AL.fetch_calls()[0]["published_at"] is None
    r, send = go(env)
    assert r["picks"] == "posted" and AL.fetch_calls()[0]["published_at"]


def test_only_calls_the_book_really_posts_are_locked_and_posted(env):
    env["plays"].append(_gem(name="Not Posted", pid=8))
    env["deps"]["fetch_offers"] = lambda sport, d, key: _offers([env["plays"][0]], sport)
    r, send = go(env)
    assert [c["player"] for c in AL.fetch_calls()] == ["Gem Guy"] and "Not Posted" not in send.sent[0]


def test_a_game_that_has_started_is_never_locked_or_posted(env):
    env["plays"][0]["GameDate"] = _iso(-1)
    env["meta"][0]["game_date"] = _iso(-1)
    r, send = go(env)
    assert r["picks"] == "nothing to post" and r["locked"] == 0 and send.sent == [] and AL.fetch_calls() == []


def test_an_empty_slate_posts_nothing(env):
    env["plays"].clear()
    r, send = go(env)
    assert r["picks"] == "nothing to post" and r["notes"] == ["no plays on the slate"] and send.sent == []


# ------------------------------------------------------------------ the recap
def _lock_yesterday(env, name="Old Gem", pid=9, published=True, days=-1):
    y = _day(days)
    c = {"key": "k", "sport": "NBA", "date": y, "player": name, "player_id": pid, "team": "NYK", "game": "BOS @ NYK",
         "game_date": "2026-01-01T23:00:00Z", "market": "Points", "side": "Over", "line": 20.5, "model_prob": 0.66,
         "conviction": 1.3, "price": -115, "price_book": "draftkings", "angles": [{"angle": "market_gap"}], "cautions": [],
         "score": 1.0, "gem": True, "chalk": False, "why": "w"}
    AL.record_calls([c], y, now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    if published:
        AL.mark_published([c])
    return y


def test_the_recap_grades_earlier_days_first_then_posts_what_was_published(env):
    y = _lock_yesterday(env)
    _lock_yesterday(env, name="Unseen", pid=10, published=False)
    env["results"] = {9: {"pts": 25}, 10: {"pts": 5}}
    r, send = go(env)
    assert r["graded"] == 2 and r["recap"] == "posted" and len(send.sent) == 2
    recap = send.sent[1]
    assert f"recap · NBA, {y}" in recap and "Old Gem" in recap and "Unseen" not in recap
    assert "1-0" in recap and "Record so far: 1-0" in recap                     # the audience's record counts published calls only
    assert AL.posted("recap", "NBA", y)


def test_the_recap_waits_for_results_and_goes_out_once(env):
    _lock_yesterday(env)
    r, send = go(env)                                                            # no box scores yet
    assert r["graded"] == 0 and r["recap"] == "nothing to post"
    env["results"] = {9: {"pts": 25}}
    assert go(env)[0]["recap"] == "posted"
    r, send = go(env)
    assert r["recap"] == "already posted" and send.sent == []


def test_a_failed_recap_is_retried_and_a_day_with_nothing_published_has_no_recap(env):
    _lock_yesterday(env, published=False)
    env["results"] = {9: {"pts": 25}}
    assert go(env)[0]["recap"] == "nothing to post"
    AL.mark_published([c for c in AL.fetch_calls()])
    r, _ = go(env, send=Sender(404))
    assert r["recap"].startswith("failed: Discord answered 404")
    assert go(env)[0]["recap"] == "posted"


def test_a_dry_run_grades_nothing(env):
    _lock_yesterday(env)
    env["results"] = {9: {"pts": 25}}
    r, _ = go(env, post=False)
    assert r["graded"] == 0 and r["recap"] == "nothing to post" and AL.fetch_calls()[0]["settled_at"] is None


# ------------------------------------------------------------------ building calls
def test_missing_sources_are_reported_not_fatal(env):
    env["state"] = env
    env["key"] = None
    b = PUB.build_calls("NBA", _day(0), "draftkings", env["deps"])
    assert "no Odds API key is configured, so book lines can't be checked" in b["notes"]
    env["key"] = "KEY"
    env["offers_error"] = "quota " + "z" * 200
    b = PUB.build_calls("NBA", _day(0), "draftkings", env["deps"])
    assert b["notes"][0].startswith("the odds fetch failed (quota zzz") and len(b["notes"][0]) < 130
    env["deps"]["game_env"] = lambda *a: ({}, "no spreads")
    env["deps"]["matchups"] = lambda *a: ({}, "no matchups")
    assert PUB.build_calls("NBA", _day(0), "draftkings", env["deps"])["notes"][-2:] == ["no spreads", "no matchups"]

    def boom(*a):
        raise RuntimeError("down")
    env["deps"]["matchups"] = boom
    assert PUB.build_calls("NBA", _day(0), "draftkings", env["deps"])["notes"][-1] == "the extra evidence couldn't be loaded (down)"


def test_the_game_environment_and_matchups_reach_the_scan(env, monkeypatch):
    seen = {}
    real = A.scan
    monkeypatch.setattr(A, "scan", lambda *a, **k: seen.update(k) or real(*a, **k))
    env["deps"]["game_env"] = lambda sport, d, meta, key: ({"BOS @ NYK": {"home_name": "NYK", "away_name": "BOS"}}, "")
    env["deps"]["matchups"] = lambda sport, d: ({("gemguy", "Points"): {"factor": 1.2}}, "")
    PUB.build_calls("NBA", _day(0), "draftkings", env["deps"])
    assert seen["game_env"] == {"BOS @ NYK": {"home_name": "NYK", "away_name": "BOS"}}
    assert seen["matchups"] == {("gemguy", "Points"): {"factor": 1.2}} and seen["book"] == "draftkings" and seen["expect_book_lines"] is True


def test_football_is_scoped_to_the_picked_dates_games(env):
    env["plays"][:] = [_gem(game="BOS @ NYK", when=_iso(1), name="Today Guy", pid=1, market="Pass Yards"),
                       _gem(game="MIA @ BUF", when=_iso(4), name="Later Guy", pid=2, market="Pass Yards")]
    for p in env["plays"]:
        p["Line"] = 240.5
    env["meta"][:] = [{"label": "BOS @ NYK", "game_date": _iso(1)}, {"label": "MIA @ BUF", "game_date": _iso(4)}]
    b = PUB.build_calls("NFL", _day(1), "draftkings", env["deps"])
    assert {c["player"] for c in b["calls"]} == {"Today Guy"} and b["n_games"] == 1


# ------------------------------------------------------------------ the command line
def test_posting_without_a_webhook_is_refused_before_anything_is_locked(env):
    out = []
    assert PUB.run(["NBA"], post=True, webhook="", deps=env["deps"], out=out.append, require_shared_db=False) == 1
    assert "Refusing to run with --post" in out[0] and AL.fetch_calls() == []


def test_one_sport_failing_never_stops_the_others(env):
    base = env["deps"]["load_board"]

    def board(sport, d, book):
        if sport == "NFL":
            raise RuntimeError("feed down")
        return base(sport, d, book)
    env["deps"]["load_board"] = board
    out, send = [], Sender()
    code = PUB.run(["NFL", "NBA"], post=True, webhook=HOOK, deps=env["deps"], send=send, out=out.append, require_shared_db=False)
    assert code == 1 and out[0].startswith("NFL: ERROR RuntimeError: feed down")
    assert out[1].startswith("NBA: locked 1, graded 0, picks: posted") and len(send.sent) == 1


def test_a_failed_post_makes_the_run_exit_nonzero_and_a_dry_run_prints_the_text(env):
    out = []
    assert PUB.run(["NBA"], post=True, webhook=HOOK, deps=env["deps"], send=Sender(500), out=out.append, require_shared_db=False) == 1
    out2 = []
    assert PUB.run(["NBA"], post=False, deps=env["deps"], out=out2.append) == 0
    assert out2[0].startswith("NBA: locked 0, graded 0, picks: dry run") and any("--- NBA picks (dry run) ---" in o and "Gem Guy" in o for o in out2)


def test_sports_default_to_every_live_projection_sport_and_args_are_read(monkeypatch):
    keys = PUB.default_sports()
    assert "NBA" in keys and "NFL" in keys and "UFC" not in keys
    seen = {}
    monkeypatch.setattr(PUB, "run", lambda ks, **k: seen.update(ks=ks, **k) or 0)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", HOOK)
    monkeypatch.delenv("ANALYST_SPORTS", raising=False)
    assert PUB.main(["--post", "--sports", "nba", "nfl", "--book", "fanduel", "--date", "2026-10-11"]) == 0
    assert seen["ks"] == ["NBA", "NFL"] and seen["post"] is True and seen["book"] == "fanduel" and seen["date_str"] == "2026-10-11"
    assert seen["webhook"] == HOOK
    monkeypatch.setenv("ANALYST_SPORTS", "wnba, nhl")
    PUB.main([])
    assert seen["ks"] == ["WNBA", "NHL"] and seen["post"] is False


def test_posting_is_refused_without_the_shared_database(env, monkeypatch):
    out = []
    monkeypatch.setattr(AL, "USING_POSTGRES", False)
    assert PUB.run(["NBA"], post=False, deps=env["deps"], out=out.append) == 0                               # a dry run never needs it
    assert PUB.run(["NBA"], post=True, webhook=HOOK, deps=env["deps"], send=Sender(), out=out.append) == 1
    assert "DATABASE_URL is not set" in out[-1] and AL.fetch_calls() == []
    monkeypatch.setattr(AL, "USING_POSTGRES", True)
    assert PUB.run([], post=True, webhook=HOOK, deps=env["deps"], send=Sender(), out=out.append) == 0          # past the guard once shared


# ------------------------------------------------------------------ edges the mutations probe
def test_only_the_calls_shown_in_the_card_are_stamped_published(env):
    env["plays"][:] = [_gem(name=f"Gem {i}", pid=20 + i) for i in range(10)]
    r, send = go(env)
    assert r["locked"] == 10 and r["picks"] == "posted"
    rows = AL.fetch_calls()
    assert len(rows) == 10 and sum(1 for x in rows if x["published_at"]) == 8          # the card shows eight


def test_a_run_grades_at_most_three_open_days(env):
    for d in (-1, -2, -3, -4):
        _lock_yesterday(env, days=d)
    env["results"] = {9: {"pts": 25}}
    r, _ = go(env)
    assert r["graded"] == 3
    assert sum(1 for x in AL.fetch_calls() if x["settled_at"]) == 3


def test_the_recap_is_for_the_latest_fully_graded_published_day(env):
    _lock_yesterday(env, days=-2, name="Older")
    _lock_yesterday(env, days=-1, name="Newer")
    env["results"] = {9: {"pts": 25}}
    r, send = go(env)
    assert r["recap"] == "posted"
    recap = [t for t in send.sent if "recap" in t][0]
    assert f"NBA, {_day(-1)}" in recap and "Newer" in recap and "Older" not in recap


def test_a_day_with_an_ungraded_published_call_is_not_recapped_yet(env):
    _lock_yesterday(env, days=-1, name="Graded", pid=9)
    _lock_yesterday(env, days=-1, name="Waiting", pid=77)
    env["results"] = {9: {"pts": 25}}                                                  # 77 has no stat line yet… but a non-empty
    AL.settle_day("NBA", _day(-1), {9: {"pts": 25}})                                   # mapping voids him, so grade only one by hand
    with AL._sqlite_conn(AL.DB_PATH) as con:
        con.execute("UPDATE analyst_calls SET settled_at=NULL, hit=NULL WHERE player='Waiting'")
    env["deps"]["results"] = lambda sport, d: {}
    r, _ = go(env)
    assert r["recap"] == "nothing to post"


def test_the_book_comes_from_the_environment_when_not_given(env, monkeypatch):
    out = []
    monkeypatch.delenv("ANALYST_BOOK", raising=False)
    PUB.run(["NBA"], deps=env["deps"], out=out.append)
    assert "picks: dry run" in out[0]
    monkeypatch.setenv("ANALYST_BOOK", "fanduel")                                        # the offers only have DraftKings
    out.clear()
    PUB.run(["NBA"], deps=env["deps"], out=out.append)
    assert "picks: nothing to post" in out[0]
    out.clear()
    PUB.run(["NBA"], book="draftkings", deps=env["deps"], out=out.append)                 # an explicit book wins
    assert "picks: dry run" in out[0]


def test_a_failed_recap_alone_makes_the_run_exit_nonzero(env):
    _lock_yesterday(env)
    env["results"] = {9: {"pts": 25}}
    go(env, send=Sender(204))
    AL.release_post("recap", "NBA", _day(-1))
    out = []
    assert PUB.run(["NBA"], post=True, webhook=HOOK, deps=env["deps"], send=Sender(500), out=out.append, require_shared_db=False) == 1
    assert "picks: already posted, recap: failed" in out[0]


def test_a_later_day_with_only_unpublished_calls_does_not_hide_the_published_day_before_it(env):
    _lock_yesterday(env, days=-2, name="Posted Earlier", pid=9)
    _lock_yesterday(env, days=-1, name="Never Posted", pid=10, published=False)
    env["results"] = {9: {"pts": 25}, 10: {"pts": 25}}
    r, send = go(env)
    assert r["recap"] == "posted"
    recap = [t for t in send.sent if "recap" in t][0]
    assert f"NBA, {_day(-2)}" in recap and "Posted Earlier" in recap
