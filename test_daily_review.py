"""Oct 31: the 3:30 AM ET morning review (daily_review.py) -- grade, suggest, settle, store."""
import json
from datetime import datetime, timezone
from pathlib import Path

import betlog as B
import daily_review as D
import model_store as MS
import props_engine as PE

SUMMARY = json.loads((Path(__file__).parent / "test_fixtures" / "espn_ncaaf_summary_401856844_trimmed.json")
                     .read_text())
BOARD = {"events": [{"id": "401856844", "competitions": [{"competitors": [
    {"team": {"abbreviation": "UCF", "displayName": "UCF Knights", "location": "UCF", "id": "2116"}},
    {"team": {"abbreviation": "BAY", "displayName": "Baylor Bears", "location": "Baylor", "id": "239"}}]}]}]}
CALLS = []


def fetch(url, params=None):
    CALLS.append(url)
    return BOARD if url.endswith("scoreboard") else SUMMARY


def snap(player, team, market, proj, line, side, use=PE.USE_PARLAY, gap=None, flags=()):
    rec = {c: None for c in MS.SNAP_COLS}
    rec.update(sport="NCAAF", slate_date="2026-10-30", game="Baylor @ UCF", team=team,
               opp="UCF" if team == "Baylor" else "Baylor", player=player, market=market, slot="WR1",
               projection=proj, line=line, side=side, chance=0.62, use_tag=use, gap=gap,
               flags=json.dumps(list(flags)), kickoff="2099-01-01T00:00:00Z", ts="2026-10-30T20:00:00Z")
    return rec


def test_due_only_at_3am_new_york_on_both_sides_of_daylight_saving():
    assert D.due(datetime(2026, 10, 31, 7, 30, tzinfo=timezone.utc))        # EDT: 07:30 UTC = 3:30 AM
    assert not D.due(datetime(2026, 10, 31, 8, 30, tzinfo=timezone.utc))
    assert D.due(datetime(2026, 11, 2, 8, 30, tzinfo=timezone.utc))         # EST: 08:30 UTC = 3:30 AM
    assert not D.due(datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc))
    assert D.morning_of(datetime(2026, 11, 2, 8, 30, tzinfo=timezone.utc)) == "2026-11-02"


def test_morning_review_grades_settles_and_stores(tmp_path):
    model_db, bet_db = str(tmp_path / "m.db"), str(tmp_path / "b.db")
    MS.save([snap("D.J. Lagway", "Baylor", "Pass Yards", 314.2, 256.5, "Over"),                   # 319: hit
             snap("Caden Knighten", "Baylor", "Rush Attempts", 9.1, 6.5, "Over", gap="big"),      # 7: hit
             snap("Duke Watson", "UCF", "Rush Attempts", 16.0, 14.5, "Over", use=PE.USE_SINGLE,   # 7: miss
                  flags=["↑ usage bump: teammate out"])], model_db)
    win = B.add_bet(bet_db, player="D.J. Lagway", game="Baylor @ UCF", market="Pass Yards", side="Over",
                    line=256.5, slate_date="2026-10-30", sport="NCAAF", stake=10, entry_odds=-110)
    dnp = B.add_bet(bet_db, player="Nobody Here", game="Baylor @ UCF", market="Receptions", side="Over",
                    line=2.5, slate_date="2026-10-30", sport="NCAAF", stake=10, entry_odds=-110)
    head = B.add_bet(bet_db, player=None, market="Parlay", side="2-leg parlay", game="Baylor @ UCF",
                     slate_date="2026-10-30", sport="NCAAF", stake=5, entry_odds=250, ticket="T1")
    l1 = B.add_bet(bet_db, player="Duke Watson", game="Baylor @ UCF", market="Rush Attempts", side="Under",
                   line=14.5, slate_date="2026-10-30", sport="NCAAF", stake=0, ticket="T1")
    l2 = B.add_bet(bet_db, player="Caden Knighten", game="Baylor @ UCF", market="Rush Attempts", side="Over",
                   line=6.5, slate_date="2026-10-30", sport="NCAAF", stake=0, ticket="T1")

    out = D.run("2026-10-31", fetch=fetch, db_path=model_db, bet_db=bet_db, sports=("NCAAF", "NBA"))

    assert set(out) == {"NCAAF"}                                     # NBA: no slate, no open bets -> skipped
    rep = out["NCAAF"]
    s = rep["slates"]["2026-10-30"]
    assert s["counts"]["hit"] == 2 and s["counts"]["miss"] == 1
    assert s["model"] == {"right": 2, "graded": 3}
    assert s["big_gap"]["graded"] == 1 and s["star_out"]["graded"] == 1 and s["star_out"]["hit_rate"] == 0
    assert s["top_misses"][0]["player"] == "Duke Watson"
    assert any("model's side was right on 2 of 3" in n for n in rep["notes"])

    res = {b["id"]: b["result"] for b in B.list_bets(bet_db)}
    assert res[win] == "win" and res[l1] == "win" and res[l2] == "win" and res[head] == "win"
    assert res[dnp] in (None, "")                                    # a DNP / unknown name is left for a person
    assert [u["bet_id"] for u in rep["settlement"]["unresolved"]] == [dnp]
    assert rep["settlement"]["tickets"][0]["ticket"] == "T1"

    stored = MS.load_daily_review("NCAAF", "2026-10-31", db_path=model_db)
    assert stored["slates"]["2026-10-30"]["counts"]["hit"] == 2
    assert MS.daily_review_mornings("NCAAF", db_path=model_db) == ["2026-10-31"]
    # Next morning: Oct 30 was fully graded, so it isn't re-reviewed (only suggestions look back at it).
    assert D.slates_for("NCAAF", "2026-11-01", db_path=model_db) == []


def test_runner_refuses_without_the_database(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(B, "USING_POSTGRES", False)
    assert D.main(["--force"]) == 1
    assert "DATABASE_URL not set" in capsys.readouterr().out


def test_morning_report_tab_shows_the_stored_report(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import postgame as PG
    model_db, bet_db = str(tmp_path / "m.db"), str(tmp_path / "b.db")
    snaps = [snap("D.J. Lagway", "Baylor", "Pass Yards", 314.2, 256.5, "Over"),
             snap("Duke Watson", "UCF", "Rush Attempts", 16.0, 14.5, "Over", use=PE.USE_SINGLE)]
    MS.save(snaps, model_db)
    B.add_bet(bet_db, player="Nobody Here", game="Baylor @ UCF", market="Receptions", side="Over",
              line=2.5, slate_date="2026-10-30", sport="NCAAF", stake=10, entry_odds=-110)
    rep = D.run("2026-10-31", fetch=fetch, db_path=model_db, bet_db=bet_db, sports=("NCAAF",))["NCAAF"]
    rep = json.loads(json.dumps(rep, default=str))
    monkeypatch.setattr(MS, "snapshot_dates", lambda sport, db_path=None: ["2026-10-30"])
    monkeypatch.setattr(MS, "load_snapshots", lambda sport=None, dates=None, db_path=None: snaps)
    monkeypatch.setattr(MS, "list_tuning", lambda active_only=True, db_path=None: [])
    monkeypatch.setattr(MS, "daily_review_mornings", lambda sport, db_path=None: ["2026-10-31"])
    monkeypatch.setattr(MS, "load_daily_review", lambda sport, morning, db_path=None: rep)
    monkeypatch.setattr(PG, "fetch_results", lambda sport, d, games, fetch=None: {})
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "41_Postgame_Review.py"), default_timeout=30)
    at.session_state["sport"] = "NCAAF"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    txt = " ".join(m.value for m in at.markdown)
    assert "Slate 2026-10-30" in txt and "model's side was right on 1 of 2" in txt
    assert any("left open for a person" in w.value for w in at.warning)
