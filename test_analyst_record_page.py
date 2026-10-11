"""views/40_Analyst_Record.py — the public, read-only, verifiable record."""
import csv
import hashlib
import io

import pytest
from streamlit.testing.v1 import AppTest

import analyst_ledger as AL
import analyst_tools as AT

PAGE = "views/40_Analyst_Record.py"
_SQL = ("INSERT INTO analyst_calls (logged_at, call_date, sport, game, player, market, side, line, model_prob, price, price_book, angles, gem, "
        "hit, actual, settled_at, published_at) VALUES ('{ts}', '{d}', '{sp}', 'A @ B', '{pl}', 'Points', '{sd}', 20.5, {mp}, -115, 'draftkings', "
        "'[\"form_run\"]', {gem}, {hit}, {act}, {st}, {pub})")


def add(db, pl, d="2026-10-01", sp="NBA", sd="Over", mp=0.6, gem=0, hit="NULL", act="NULL", settled=False, pub=False, ts=None):
    AL._run(db, _SQL.format(ts=ts or f"{d}T18:00:00+00:00", d=d, sp=sp, pl=pl, sd=sd, mp=mp, gem=gem, hit=hit, act=act,
                            st="'x'" if settled else "NULL", pub="'2026-10-01T19:00:00+00:00'" if pub else "NULL"))


@pytest.fixture
def db(monkeypatch, tmp_path):
    path = str(tmp_path / "ledger.db")
    monkeypatch.setattr(AL, "DB_PATH", path)
    return path


def run():
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def texts(at):
    return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption] + [i.value for i in at.info] + [w.value for w in at.warning])


def seed(db):
    add(db, "Hit One", hit=1, act=25, settled=True, pub=True, gem=1)
    add(db, "Hit Two", hit=1, act=22, settled=True, mp=0.7)
    add(db, "Miss One", hit=0, act=10, settled=True, sp="NFL", sd="Under")
    add(db, "Void One", settled=True)
    add(db, "Open One", d="2026-10-02")


def test_an_empty_record_says_nothing_has_been_locked_and_invents_nothing(db):
    at = run()
    assert any("No calls have been locked yet" in i.value for i in at.info) and not at.metric and not at.tabs


def test_the_headline_numbers_are_the_graded_record_and_the_status_waits_for_enough_calls(db):
    seed(db)
    at = run()
    m = {x.label: x.value for x in at.metric}
    assert m["Calls locked"] == "5" and m["Graded"] == "3" and m["Hit rate"] == "67%" and m["Model said"] == "63%"
    joined = texts(at)
    assert f"A verdict needs 30 graded calls" in joined or "Collecting data (3/30)" in joined
    assert "Status: Collecting data (3/30)." in joined and "does not mean the calls were profitable" in joined
    assert [t.label for t in at.tabs] == ["🧭 By angle", "🎯 Calibration", "📋 Every call", "🔐 Verify it", "📖 Method & limits"]


def test_the_page_can_be_narrowed_to_a_sport_or_to_what_was_actually_published(db):
    seed(db)
    at = run()
    [s for s in at.selectbox if s.label == "Sport"][0].set_value("NFL").run()
    m = {x.label: x.value for x in at.metric}
    assert m["Calls locked"] == "1" and m["Graded"] == "1" and m["Hit rate"] == "0%"
    at = run()
    [r for r in at.radio if r.label == "Record basis"][0].set_value("Published to the audience only").run()
    m = {x.label: x.value for x in at.metric}
    assert m["Calls locked"] == "1" and m["Graded"] == "1" and m["Hit rate"] == "100%"


def test_every_call_is_listed_with_its_lock_time_and_result_and_can_be_filtered(db):
    seed(db)
    at = run()
    table = [d.value for d in at.dataframe if "Locked at (UTC)" in d.value.columns][0]
    assert len(table) == 5 and set(table["Result"]) == {"Hit", "Miss", "Void", "Open"}
    row = table[table["Player"] == "Hit One"].iloc[0]
    assert row["Locked at (UTC)"] == "2026-10-01T18:00:00+00:00" and row["Play"] == "Over 20.5 Points" and row["Gem"] == "💎"
    assert row["Published"] == "2026-10-01T19:00:00+00:00" and row["Book"] == "draftkings" and row["Actual"] == 25
    [x for x in at.multiselect if x.label == "Result"][0].set_value(["Miss", "Void"]).run()
    table = [d.value for d in at.dataframe if "Locked at (UTC)" in d.value.columns][0]
    assert set(table["Player"]) == {"Miss One", "Void One"} and any("2 of 5 calls" in m.value for m in at.markdown)


def test_the_page_shows_the_fingerprint_and_the_csv_lets_anyone_recompute_it(db):
    seed(db)
    at = run()
    fp = AL.record_fingerprint(AL.fetch_calls(db_path=db))
    assert any(f"`{fp}`" in m.value and "5 locked calls" in m.value for m in at.markdown)
    text = AT.record_csv(AL.fetch_calls(db_path=db))
    rows = list(csv.reader(io.StringIO(text)))[1:]                                             # exactly the snippet the page prints
    assert hashlib.sha256("\n".join("|".join(r[:10]) for r in rows).encode("utf-8")).hexdigest()[:16] == fp
    code = [c.value for c in at.code][0]
    assert "csv.reader" in code and "r[:10]" in code and "hexdigest()[:16]" in code and "'\\n'.join" in code


def test_the_csv_is_the_whole_record_whatever_filter_is_picked(db):
    seed(db)
    csv_text = AT.record_csv(AL.fetch_calls(db_path=db))
    assert len(list(csv.reader(io.StringIO(csv_text)))) == 6                                  # header + 5 calls
    header = csv_text.splitlines()[0].split(",")
    assert header[:10] == list(AL.FINGERPRINT_FIELDS) and header[10:] == list(AT.RECORD_EXTRA_COLUMNS)


def test_the_method_page_names_the_brand_and_states_the_limits_and_the_helpline(db):
    seed(db)
    joined = texts(run())
    for needle in ("H2 Sports Media", "not a profit claim", "never rewrites it", "void, not a loss", "1-800-GAMBLER",
                   "two different *kinds* of evidence", "capped (4 for 4 shows as 75%)"):
        assert needle in joined, needle


def test_the_page_never_writes_and_a_broken_ledger_is_reported_not_hidden(db, monkeypatch):
    seed(db)
    before = AL.fetch_calls(db_path=db)
    run()
    assert AL.fetch_calls(db_path=db) == before
    monkeypatch.setattr(AL, "fetch_calls", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    assert not at.exception and any("couldn't be read right now" in w.value for w in at.warning)


def test_there_is_a_calibration_table_once_calls_are_graded(db):
    seed(db)
    at = run()
    cal = [d.value for d in at.dataframe if "Avg stated" in d.value.columns][0]
    assert cal["Calls"].sum() == 3
    add(db, "x", d="2026-10-03")                                                               # an open call changes nothing
    assert [d.value for d in run().dataframe if "Avg stated" in d.value.columns][0]["Calls"].sum() == 3


def test_the_csv_and_the_fingerprint_always_cover_the_whole_record_whatever_is_filtered(db, monkeypatch):
    seed(db)
    seen = []
    real = AT.record_csv
    monkeypatch.setattr(AT, "record_csv", lambda rows: seen.append(len(rows)) or real(rows))
    at = run()
    [s for s in at.selectbox if s.label == "Sport"][0].set_value("NFL").run()
    [r for r in at.radio if r.label == "Record basis"][0].set_value("Published to the audience only").run()
    assert seen and set(seen) == {5}                                                          # never the filtered subset
    fp = AL.record_fingerprint(AL.fetch_calls(db_path=db))
    assert any(f"`{fp}`" in m.value and "5 locked calls" in m.value for m in at.markdown)


def test_the_sport_list_names_every_sport_the_desk_covers_even_before_it_has_calls(db):
    add(db, "Only NFL", sp="NFL", hit=1, act=250, settled=True)
    at = run()
    sport = [s for s in at.selectbox if s.label == "Sport"][0]
    assert sport.options == ["All sports", "MLB", "NFL", "WNBA", "NBA", "NHL", "NCAAF", "NCAAMB"]        # UFC has no Desk, so it is not listed


def test_a_sport_with_no_calls_yet_says_so_and_the_record_stays_whole(db):
    seed(db)
    at = run()
    [s for s in at.selectbox if s.label == "Sport"][0].set_value("NHL").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("No NHL calls have been locked yet" in i.value for i in at.info)
    assert {x.label: x.value for x in at.metric}["Calls locked"] == "0"
    assert any("5 locked calls" in m.value for m in at.markdown)                                      # the fingerprint still covers everything


def test_a_sport_in_the_ledger_but_no_longer_covered_is_still_listed(db):
    add(db, "Old Sport", sp="XFL", hit=1, act=20, settled=True)
    at = run()
    assert "XFL" in [s for s in at.selectbox if s.label == "Sport"][0].options
