"""hot_tickets (Nov 22): the day's most probable picks that still pay, posted once, graded with everything else."""
from datetime import datetime, timezone

import pytest

import analyst_ledger as AL
import hot_tickets as HT
import pick_ledger as PL

DAY = "2026-11-22"          # a Sunday
NOON = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)   # 10 AM New York


def _r(pick, sport, earned, price, game, time="7:00 PM", **kw):
    r = {"pick": pick, "sport": sport, "earned": earned, "price": price, "game": game, "time": time,
         "player": pick.split()[0], "market": "Points", "side": "Over", "line": 10.5, "book": "draftkings"}
    r.update(kw)
    return r


ROWS = {
    "NBA": [_r("Alpha Over", "NBA", 0.64, -150, "A @ B"),            # needs 60%: pays
            _r("Beta Over", "NBA", 0.70, -300, "C @ D"),             # too short a price
            _r("Gamma Over", "NBA", 0.50, -150, "E @ F"),            # doesn't pay
            _r("Delta Over", "NBA", 0.62, -140, "A @ B"),            # same game as Alpha
            _r("Eps Over", "NBA", 0.66, -120, "G @ H", pickem_only=True),
            _r("Zeta Over", "NBA", 0.61, -130, "I @ J", time="9:00 AM")],   # already started
    "NFL": [_r("Kappa Under", "NFL", 0.60, -120, "K @ L", time="1:00 PM"),
            _r("Lambda Over", "NFL", 0.58, -110, "M @ N", time="4:25 PM")],
}


def _cands(off=lambda *a: False):
    return HT.candidates(DAY, NOON, keys=["NBA", "NFL"], load_props=lambda k, d: {"rows": ROWS[k]}, games=[], off=off)


def test_the_most_probable_picks_that_still_pay_one_per_game():
    names = [r["pick"] for r in _cands()]
    assert names == ["Alpha Over", "Delta Over", "Kappa Under", "Lambda Over"]
    ch = HT.choose(_cands(), DAY)
    assert [r["pick"] for r in ch["singles"]] == ["Alpha Over", "Kappa Under", "Lambda Over"]
    p = ch["parlay"]
    assert [r["pick"] for r in p["legs"]] == ["Alpha Over", "Kappa Under"]
    assert abs(p["chance"] - 0.64 * 0.60) < 1e-9 and p["price"] > 100
    assert ch["potw"]["pick"] == "Kappa Under"                       # Sunday: the top NFL pick


def test_a_market_the_shut_off_pulled_is_left_out():
    names = [r["pick"] for r in _cands(off=lambda sport, market, kind: sport == "NFL")]
    assert names == ["Alpha Over", "Delta Over"]


def test_the_post_reads_like_a_card_and_carries_the_record_and_disclaimer():
    ch = HT.choose(_cands(), DAY)
    t = HT.post_text(DAY, ch, "📒 **Hot Tickets record:** singles 4–2")
    assert "HOT TICKETS" in t and "TICKET OF THE DAY" in t and "**Alpha Over**" in t and "ALSO HOT" in t
    assert "HOT TICKET PARLAY" in t and "about 38% to hit" in t
    assert "NFL PICK OF THE WEEK:** Kappa Under — on the card above" in t
    assert "singles 4–2" in t and "1-800-GAMBLER" in t
    assert HT.post_text(DAY, {"singles": [], "parlay": None, "potw": None}) == ""


@pytest.fixture
def store(monkeypatch, tmp_path):
    s = {}
    import model_store as MS
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None: s.get(k, d))
    monkeypatch.setattr(MS, "save_setting", lambda k, v: s.__setitem__(k, v))
    monkeypatch.setattr(AL, "DB_PATH", str(tmp_path / "ledger.db"))
    return s


def test_posting_saves_the_tickets_and_the_parlay_grades_from_its_legs(store):
    ch = HT.choose(_cands(), DAY)
    HT.save_posted(DAY, ch, NOON)
    led = PL.load("hot", "ALL", DAY)["rows"]
    assert len(led) == 3 and all(r.get("rule_v") == 1 for r in led.values())
    assert HT.parlay_result(DAY) is None                             # not graded yet
    for k, r in led.items():
        r["result"] = "loss" if r["pick"] == "Lambda Over" else "win"
    store[PL.KEY.format(kind="hot", sport="ALL", day=DAY)] = {"rows": led, "graded_at": "x"}
    assert HT.parlay_result(DAY) == "win"
    rec = HT.record(DAY)
    assert (rec["w"], rec["l"], rec["pw"], rec["pl"]) == (2, 1, 1, 0) and rec["punits"] > 1
    t = HT.recap_text(DAY)
    assert "✅ NBA · Alpha Over" in t and "❌ NFL · Lambda Over" in t and "✅ 🎰 Hot Ticket parlay" in t


def test_a_losing_or_void_leg(store):
    ch = HT.choose(_cands(), DAY)
    HT.save_posted(DAY, ch, NOON)
    led = PL.load("hot", "ALL", DAY)["rows"]
    res = {"Alpha Over": "void", "Kappa Under": "win", "Lambda Over": "loss"}
    for r in led.values():
        r["result"] = res[r["pick"]]
    store[PL.KEY.format(kind="hot", sport="ALL", day=DAY)] = {"rows": led, "graded_at": "x"}
    assert HT.parlay_result(DAY) == "win"                             # a void leg drops out
    res["Kappa Under"] = "loss"
    for r in led.values():
        r["result"] = res[r["pick"]]
    assert HT.parlay_result(DAY) == "loss"


def test_run_posts_once_and_a_dry_run_posts_nothing(store, monkeypatch):
    import props_engine as PE
    monkeypatch.setattr(PE, "_et_today", lambda: DAY)
    fixed = _cands()
    monkeypatch.setattr(HT, "candidates", lambda day, now=None: fixed)
    sent, out = [], []

    def send(url, json=None, timeout=None):
        sent.append(json["content"])

        class R:
            status_code = 204
        return R()
    hook = "https://discord.com/api/webhooks/1/abc"
    assert HT.run(post=False, out=out.append) == 0 and not sent and "dry run" in out[-1]
    early = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)                 # 7 AM New York
    assert HT.run(post=True, webhook=hook, send=send, out=out.append, now=early) == 0 and not sent
    assert "too early" in out[-1]
    assert HT.run(post=True, webhook=hook, send=send, out=out.append, now=NOON) == 0 and len(sent) == 1
    assert HT.run(post=True, webhook=hook, send=send, out=out.append, now=NOON) == 0 and len(sent) == 1
    assert "already posted" in out[-1]
    assert HT.run(post=True, webhook="", out=out.append) == 1


def test_an_update_replaces_game_line_tickets_and_keeps_the_record(store, monkeypatch):
    import props_engine as PE
    monkeypatch.setattr(PE, "_et_today", lambda: DAY)
    game = _r("Dayton moneyline", "NCAAMB", 0.63, -156, "Dayton @ Northwestern", money_market="Moneyline",
              game_id="g1", money_side="away")
    HT.save_posted(DAY, {"singles": [game, _cands()[0]], "parlay": None, "potw": None}, NOON)
    fixed = _cands()
    monkeypatch.setattr(HT, "candidates", lambda day, now=None: fixed)
    sent = []

    def send(url, json=None, timeout=None):
        sent.append(json["content"])

        class R:
            status_code = 204
        return R()
    hook = "https://discord.com/api/webhooks/1/abc"
    assert HT.revise("Corrected model.", post=True, webhook=hook, send=send, out=lambda m: None) == 0
    t = sent[0]
    assert "UPDATED" in t and "~~NCAAMB · Dayton moneyline (-156)~~" in t and "Corrected model." in t
    assert "Alpha Over" not in t.split("UPDATED TICKETS")[1]          # already posted: not repeated
    rows = PL.rows("hot", "ALL", DAY)
    assert any(r["pick"] == "Dayton moneyline" for r in rows) and len(rows) == 3       # old kept, one new
    assert HT.revise("again", post=True, webhook=hook, send=send, out=lambda m: None) == 0 and len(sent) == 1
