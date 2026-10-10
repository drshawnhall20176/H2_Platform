"""analyst_tools.py — closing-line tracking, locked-call status, Discord text/posting, Ask the Analyst."""
import json

import pytest

import analyst as A
import analyst_tools as AT


def row(**kw):
    r = {"player": "Pat Player", "market": "Pass Yards", "side": "Over", "line": 240.5, "price": -110, "price_book": "draftkings",
         "last_line": 240.5, "last_price": -110, "angles": ["form_run"], "gem": False, "model_prob": 0.6, "game": "TB @ DAL"}
    r.update(kw)
    return r


# --------------------------------------------------------------- closing-line tracking
def test_a_shorter_price_on_the_same_line_is_the_market_moving_toward_the_call():
    m = AT.clv_move(row(last_price=-130))
    assert m["kind"] == "price" and m["toward"] is True and m["move"] == pytest.approx(0.0414, abs=1e-3)
    assert AT.clv_move(row(last_price=+100))["toward"] is False
    flat = AT.clv_move(row(last_price=-111))
    assert flat["toward"] is None and abs(flat["move"]) < AT.FLAT_BAND


def test_a_moved_line_counts_toward_when_it_moves_to_agree_with_the_side():
    assert AT.clv_move(row(last_line=245.5))["toward"] is True                                  # Over took the lower number
    assert AT.clv_move(row(last_line=235.5))["toward"] is False
    assert AT.clv_move(row(side="Under", last_line=235.5))["toward"] is True
    assert AT.clv_move(row(side="Under", last_line=245.5))["toward"] is False
    assert AT.clv_move(row(last_line=245.5))["move"] == 5.0 and AT.clv_move(row(last_line=235.5))["move"] == -5.0


def test_an_unmarked_or_uncomparable_row_has_no_move():
    assert AT.clv_move(row(last_line=None)) is None
    assert AT.clv_move(row(last_price=None)) is None                                            # same line, no price to compare
    assert AT.clv_move(row(line=None)) is None
    assert AT.clv_move(row(last_line=245.5, last_price=None))["toward"] is True                 # a line move needs no price


def test_clv_board_counts_by_angle_and_waits_for_enough_moves_before_judging():
    rows = [row(last_price=-130, angles=["form_run"]), row(last_price=+100, angles=["form_run"]),
            row(last_line=250.5, angles=["market_gap"], gem=True), row(last_price=-110, angles=["market_gap"]),
            row(last_line=None, angles=["market_gap"])]
    b = {r["angle"]: r for r in AT.clv_board(rows)}
    assert b["ALL"]["marked"] == 4 and b["ALL"]["toward"] == 2 and b["ALL"]["away"] == 1 and b["ALL"]["flat"] == 1
    assert b["ALL"]["toward_rate"] == pytest.approx(2 / 3) and b["ALL"]["status"] == f"Collecting data (3/{AT.CLV_MIN_N})"
    assert b["form_run"]["toward"] == 1 and b["form_run"]["away"] == 1 and b["gem"]["marked"] == 1
    assert b["soft_book"]["marked"] == 0 and b["soft_book"]["toward_rate"] is None


def test_clv_status_judges_only_after_enough_moves():
    win = AT.clv_board([row(last_price=-130)] * 40 + [row(last_price=+100)] * 5)[0]
    assert win["n"] == 45 and win["status"] == "Beating the close" and win["ci_low"] > 0.5
    lose = AT.clv_board([row(last_price=-130)] * 5 + [row(last_price=+100)] * 40)[0]
    assert lose["status"] == "Losing to the close"
    noise = AT.clv_board([row(last_price=-130)] * 18 + [row(last_price=+100)] * 17)[0]
    assert noise["status"] == "Within the noise"
    edge = AT.clv_board([row(last_price=-130)] * (AT.CLV_MIN_N - 1))[0]
    assert edge["status"].startswith("Collecting")
    assert AT.clv_board([row(last_price=-130)] * AT.CLV_MIN_N)[0]["status"] != f"Collecting data ({AT.CLV_MIN_N}/{AT.CLV_MIN_N})"


# --------------------------------------------------------------- locked-call status
OMAP = {"Pass Yards": "player_pass_yds"}


def _idx(point, over, player="Pat Player"):
    return A.index_offers([{"market": "player_pass_yds", "player": player, "point": point, "over": over, "under": {}}])


def test_locked_status_says_what_the_book_shows_now():
    still = AT.locked_status([row()], _idx(240.5, {"draftkings": -110}), OMAP, "draftkings")[0]
    assert still["state"] == "posted" and still["text"] == "Unchanged" and still["move_pts"] == pytest.approx(0)
    shorter = AT.locked_status([row()], _idx(240.5, {"draftkings": -135}), OMAP, "draftkings")[0]
    assert shorter["text"] == "Price -110 → -135 (toward the call)" and shorter["move_pts"] > 0
    longer = AT.locked_status([row()], _idx(240.5, {"draftkings": +100}), OMAP, "draftkings")[0]
    assert "away from the call" in longer["text"] and longer["move_pts"] < 0
    moved = AT.locked_status([row()], _idx(245.5, {"draftkings": -110}), OMAP, "draftkings")[0]
    assert moved["state"] == "other_line" and moved["text"] == "Line moved — DraftKings now posts 245.5"
    pulled = AT.locked_status([row()], _idx(240.5, {"fanduel": -110}), OMAP, "draftkings")[0]
    assert pulled["state"] == "not_posted" and pulled["text"] == "Pulled — no longer posted"
    none = AT.locked_status([row()], {}, OMAP, "draftkings")[0]
    assert none["state"] == "unverified" and none["text"].startswith("Can't check")


def test_locked_status_skips_calls_locked_at_another_book_or_without_a_line():
    idx = _idx(240.5, {"draftkings": -110, "fanduel": -110})
    assert AT.locked_status([row(price_book="fanduel")], idx, OMAP, "draftkings") == []
    assert AT.locked_status([row(line=None)], idx, OMAP, "draftkings") == []
    assert AT.locked_status([row()], idx, OMAP, None) == []
    assert len(AT.locked_status([row(price_book="fanduel")], idx, OMAP, "fanduel")) == 1


def test_locked_status_carries_the_gem_flag_and_price_less_rows():
    out = AT.locked_status([row(gem=True, price=None)], _idx(240.5, {"draftkings": -120}), OMAP, "draftkings")[0]
    assert out["gem"] is True and out["text"] == "Still posted at -120" and out["move_pts"] is None


# --------------------------------------------------------------- Discord
def call(i=0, gem=False, score=1.0, price=-115, **kw):
    c = {"player": f"Player {i}", "side": "Over", "line": 20.5, "market": "Points", "model_prob": 0.6, "gem": gem, "score": score,
         "price": price, "kickoff": "7:30 PM ET", "angles": [{"label": "Form run", "evidence": "e1"}, {"label": "Soft price", "evidence": "e2"}]}
    c.update(kw)
    return c


def test_discord_picks_lead_with_gems_then_the_strongest_and_cap_the_list():
    calls = [call(1, score=0.5), call(2, gem=True, score=0.2), call(3, score=2.0)] + [call(i, score=0.1) for i in range(10, 20)]
    text = AT.discord_picks_text(calls, sport_label="NBA", date_str="2026-10-10", book_label="DraftKings", max_calls=3)
    lines = text.split("\n")
    assert lines[0] == "🎙️ **H2 Analyst Desk — NBA, 2026-10-10**" and "Lines are from DraftKings at the time of posting." in lines[1]
    assert lines[2].startswith("💎 **Player 2 Over 20.5 Points (60%)** at -115 · 7:30 PM ET — Form run, Soft price")
    assert lines[3].startswith("• **Player 3") and lines[4].startswith("• **Player 1")
    assert text.endswith(AT.DISCLAIMER) and "Player 10" not in text


def test_discord_picks_stay_under_the_character_limit_and_say_what_was_dropped():
    many = [call(i, score=1.0 - i / 1000, player=f"A Very Long Player Name Number {i}") for i in range(200)]
    text = AT.discord_picks_text(many, sport_label="NCAA Football", date_str="2026-10-10", book_label="FanDuel", max_calls=200)
    assert len(text) <= AT.DISCORD_LIMIT and "more plays on the Desk." in text and text.endswith(AT.DISCLAIMER)
    n_listed = text.count("**Player") + text.count("**A Very")
    assert f"…and {200 - n_listed} more plays on the Desk." in text
    assert AT.discord_picks_text([], sport_label="NBA", date_str="d", book_label="DK") == ""
    nokick = AT.discord_picks_text([call(kickoff="time TBD", price=None)], sport_label="NBA", date_str="d", book_label="DK")
    assert "time TBD" not in nokick and "-115" not in nokick


def _g(player, hit, actual=22.0, settled="x"):
    return {"player": player, "side": "Over", "line": 20.5, "market": "Points", "hit": hit, "actual": actual, "settled_at": settled}


def test_discord_recap_lists_hits_misses_voids_and_the_running_record():
    rows = [_g("Hit One", 1), _g("Miss One", 0, 12.0), _g("Void One", None, None), _g("Open One", None, None, settled=None)]
    board = [{"angle": "ALL", "n": 10, "hits": 6, "hit_rate": 0.6, "mean_prob": 0.62, "status": "Calibrated"}]
    t = AT.discord_recap_text(rows, sport_label="NBA", date_str="2026-10-09", board=board)
    assert "recap — NBA, 2026-10-09" in t and "1-1 (1 void — didn't play) on the day's locked calls." in t
    assert "✅ Hit One Over 20.5 Points (actual 22)" in t and "❌ Miss One Over 20.5 Points (actual 12)" in t
    assert "Void One" not in t and "Open One" not in t
    assert "Record so far: 6-4 (60%); the model said 62% on average — calibrated." in t and t.endswith(AT.DISCLAIMER)
    assert AT.discord_recap_text([_g("Open", None, None, settled=None)], sport_label="NBA", date_str="d") == ""
    assert "Record so far" not in AT.discord_recap_text(rows, sport_label="NBA", date_str="d", board=[{"angle": "ALL", "n": 0}])


class Resp:
    def __init__(self, status=204):
        self.status_code = status


def test_posting_to_discord_sends_the_text_without_pings_and_explains_every_failure():
    seen = {}

    def ok(url, json, timeout):
        seen.update(url=url, **json)
        return Resp(204)
    url = "https://discord.com/api/webhooks/1/abc"
    AT.post_to_discord(url, "hello @everyone", post=ok)
    assert seen["url"] == url and seen["content"] == "hello @everyone" and seen["allowed_mentions"] == {"parse": []}
    AT.post_to_discord(url, "x" * 5000, post=ok)
    assert len(seen["content"]) == AT.DISCORD_LIMIT
    for bad in (None, "", "http://discord.com/api/webhooks/1/a", "https://evil.example/api/webhooks/1/a"):
        with pytest.raises(RuntimeError, match="no Discord webhook"):
            AT.post_to_discord(bad, "hi", post=ok)
    with pytest.raises(RuntimeError, match="nothing to post"):
        AT.post_to_discord(url, "   ", post=ok)
    with pytest.raises(RuntimeError, match="Discord answered 404 — the webhook link may have been deleted"):
        AT.post_to_discord(url, "hi", post=lambda *a, **k: Resp(404))
    with pytest.raises(RuntimeError, match="Discord answered 500") as e:
        AT.post_to_discord(url, "hi", post=lambda *a, **k: Resp(500))
    assert "deleted" not in str(e.value)

    def boom(*a, **k):
        raise TimeoutError("slow")
    with pytest.raises(RuntimeError, match="could not reach Discord"):
        AT.post_to_discord(url, "hi", post=boom)
    AT.post_to_discord(url, "hi", post=lambda *a, **k: Resp(200))


# --------------------------------------------------------------- Ask the Analyst
def test_qa_facts_keep_bettable_plays_and_not_at_book_plays_apart():
    ok = call(1, bettable=True, game="A @ B", cautions=["c"], chalk=False)
    ok["angles"] = [{"label": "Form run", "evidence": "7 of 8"}]
    off = call(2, bettable=False, book_state="not_posted", book_elsewhere=["FanDuel"], game="A @ B")
    board = [{"label": "All", "n": 12, "hit_rate": 0.58333, "mean_prob": 0.6, "status": "Calibrated"}, {"label": "x", "n": 0}]
    clv = [{"label": "All", "marked": 5, "toward_rate": 0.6, "status": "Collecting data (5/30)"}, {"label": "x", "marked": 0}]
    f = AT.qa_facts([ok, off], sport_label="NBA", date_str="d", book_label="DraftKings", coverage_note="DK has 9", board=board, clv=clv)
    assert [p["play"] for p in f["plays"]] == ["Player 1 Over 20.5 Points (60%)"] and f["plays"][0]["angles"] == ["7 of 8"]
    assert f["not_at_book"] == [{"play": "Player 2 Over 20.5 Points (60%)", "game": "A @ B", "status": "Not posted at DraftKings (at FanDuel)"}]
    assert f["sportsbook"] == "DraftKings" and f["props_posted"] == "DK has 9"
    assert f["track_record"] == [{"angle": "All", "graded": 12, "hit_rate": 0.583, "avg_stated_chance": 0.6, "status": "Calibrated"}]
    assert f["market_moves"] == [{"angle": "All", "marked": 5, "toward_rate": 0.6, "status": "Collecting data (5/30)"}]
    bare = AT.qa_facts([], sport_label="NBA", date_str="d", book_label="DK")
    assert "props_posted" not in bare and "track_record" not in bare and "market_moves" not in bare
    json.dumps(f)                                                                                 # must be JSON-able


def test_qa_facts_cap_how_many_plays_are_sent():
    many = [dict(call(i), bettable=True, game="g") for i in range(AT.ASK_MAX_PLAYS + 25)]
    assert len(AT.qa_facts(many, sport_label="S", date_str="d", book_label="B")["plays"]) == AT.ASK_MAX_PLAYS


class LLMResp:
    status_code = 200

    def json(self):
        return {"content": [{"type": "text", "text": "Answer."}]}


def test_ask_analyst_sends_the_question_the_facts_and_recent_chat_under_the_strict_prompt():
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(json)
        return LLMResp()
    hist = [{"q": f"q{i}", "a": "a" * 900} for i in range(5)]
    out = AT.ask_analyst("  Who is the gem?  ", {"plays": []}, "key", history=hist, post=post)
    assert out == "Answer." and seen["system"] == AT.ASK_SYSTEM and seen["max_tokens"] == 700
    payload = json.loads(seen["messages"][0]["content"])
    assert payload["question"] == "Who is the gem?" and payload["facts"] == {"plays": []}
    assert [h["q"] for h in payload["earlier_in_this_chat"]] == ["q2", "q3", "q4"]
    assert all(len(h["a"]) == 600 for h in payload["earlier_in_this_chat"])
    AT.ask_analyst("x" * 900, {}, "key", post=post)
    assert len(json.loads(seen["messages"][0]["content"])["question"]) == AT.ASK_MAX_QUESTION
    AT.ask_analyst("hi", {}, "key", post=post)
    assert "earlier_in_this_chat" not in json.loads(seen["messages"][0]["content"])


def test_ask_analyst_explains_why_it_could_not_answer():
    with pytest.raises(RuntimeError, match="type a question first"):
        AT.ask_analyst("   ", {}, "key", post=lambda *a, **k: LLMResp())
    with pytest.raises(RuntimeError, match="no Anthropic API key"):
        AT.ask_analyst("hi", {}, None)


def test_the_ask_prompt_forbids_inventing_facts_or_suggesting_unavailable_plays():
    s = AT.ASK_SYSTEM
    assert "ONLY from the JSON facts" in s and "doesn't contain the answer" in s.replace("don't contain", "doesn't contain") or "say the desk doesn't have it" in s
    assert "not_at_book" in s and "never suggest them as bets" in s and "never tell anyone how much to bet" in s
