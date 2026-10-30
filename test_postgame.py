"""Oct 30: the Postgame Review -- kickoff snapshots, ESPN box-score grading, miss causes, suggestions, approvals."""
import json
from pathlib import Path

import model_store as MS
import model_tuning as MT
import postgame as PG
import props_engine as PE

SUMMARY = json.loads((Path(__file__).parent / "test_fixtures" / "espn_nfl_summary_401873023.json").read_text())
BOARD = {"events": [{"id": "401873023", "competitions": [{"competitors": [
    {"team": {"abbreviation": "GB", "displayName": "Green Bay Packers", "id": "9"}},
    {"team": {"abbreviation": "CAR", "displayName": "Carolina Panthers", "id": "29"}}]}]}]}


def fetch(url, params=None):
    return BOARD if url.endswith("scoreboard") else SUMMARY


def snap(player, team, market, proj, line, side, opp=None, flags=(), use=None, chance=0.55, gap=None, slot="WR1"):
    return {"sport": "NFL", "slate_date": "2026-10-29", "game": "CAR @ GB", "team": team,
            "opp": "GB" if team == "CAR" else "CAR", "player": player, "market": market, "slot": slot,
            "projection": proj, "proj_opp": opp, "line": line, "side": side, "chance": chance, "use_tag": use,
            "flags": json.dumps(list(flags)), "gap": gap}


def test_box_score_reads_every_stat_the_markets_need():
    box = PG.football_box(SUMMARY)
    love = box["teams"]["GB"]["jordan love"]
    assert (love["pass_cmp"], love["pass_att"], love["pass_yds"], love["pass_td"], love["sacked"]) == (30, 41, 288, 3, 0)
    young = box["teams"]["CAR"]["bryce young"]
    assert young["sacked"] == 6 and young["pass_yds"] == 209
    jacobs = box["teams"]["GB"]["josh jacobs"]
    assert (jacobs["rush_att"], jacobs["rush_yds"], jacobs["rec"], jacobs["tgt"], jacobs["rec_td"]) == (21, 39, 6, 6, 1)
    assert box["teams"]["CAR"]["ryan fitzgerald"]["kick_pts"] == 7 and box["teams"]["CAR"]["ryan fitzgerald"]["fg_made"] == 2
    assert box["teams"]["GB"]["evan williams"]["tkl"] == 10 and box["teams"]["GB"]["lukas van ness"]["sacks"] == 1
    assert box["score"] == {"GB": 27, "CAR": 19} and box["final"]


def test_grading_hits_misses_voids_and_causes():
    snaps = [snap("Jordan Love", "GB", "Pass Attempts", 38.2, 35.5, "Over", opp=38.2),
             snap("MarShawn Lloyd", "GB", "Rush Attempts", 7.8, 5.5, "Over", opp=7.8,
                  flags=["↓ Josh Jacobs back: volume from games with him active"], slot="RB2"),
             snap("Chuba Hubbard", "CAR", "Receptions", 2.4, 2.5, "Under", opp=3.0, slot="RB1"),
             snap("Tetairoa McMillan", "CAR", "Receiving Yards", 86.9, 74.5, "Over", opp=9.3),
             snap("Josh Jacobs", "GB", "Rush Yards", 45.8, 58.5, "Over", opp=12.0, slot="RB1"),
             snap("Nobody Here", "GB", "Receptions", 3.0, 2.5, "Over", opp=4.0),
             snap("Ryan Fitzgerald", "CAR", "Kicking Points", 5.2, 6.5, "Under", slot="K")]
    res = PG.fetch_results("NFL", "2026-10-29", [(s["team"], s["opp"]) for s in snaps], fetch=fetch)
    g = {r["player"] + r["market"]: r for r in PG.grade(snaps, res)}
    assert g["Jordan LovePass Attempts"]["result"] == "hit" and g["Jordan LovePass Attempts"]["actual"] == 41
    assert g["MarShawn LloydRush Attempts"]["cause"] == PG.CAUSE_ROLE                     # 3 carries vs 7.8, flagged
    assert g["Chuba HubbardReceptions"]["cause"] == PG.CAUSE_VOLUME                       # 8 targets vs 3
    assert g["Tetairoa McMillanReceiving Yards"]["cause"] == PG.CAUSE_PLAYER              # 11 targets came, 58 yards
    assert g["Josh JacobsRush Yards"]["cause"] == PG.CAUSE_PLAYER                         # MORE carries, still missed
    assert g["Nobody HereReceptions"]["result"] == "void"
    assert g["Ryan FitzgeraldKicking Points"]["result"] == "miss" and g["Ryan FitzgeraldKicking Points"]["margin"] == -8
    assert PG.model_record(PG.grade(snaps[:1], res)) == (1, 1)


def test_unfinished_game_stays_pending():
    live = json.loads(json.dumps(SUMMARY))
    live["header"]["competitions"][0]["status"]["type"]["completed"] = False
    res = PG.fetch_results("NFL", "2026-10-29", [("GB", "CAR")],
                           fetch=lambda u, p=None: BOARD if u.endswith("scoreboard") else live)
    assert PG.grade([snap("Jordan Love", "GB", "Pass Attempts", 38, 35.5, "Over")], res)[0]["result"] == "pending"


def test_use_record_and_suggestions():
    rows = []
    for i in range(20):                       # pass attempts running 20% over the projections
        rows.append({"sport": "NFL", "market": "Pass Attempts", "slot": "QB", "projection": 30.0, "actual": 36.0,
                     "result": "hit", "model_hit": True, "use_tag": PE.USE_PARLAY, "chance": 0.62, "gap": None,
                     "cause": None, "line": 29.5})
    sug = PG.suggestions(rows)
    t = [s for s in sug if s["kind"] == "tuning"]
    assert t and t[0]["market"] == "Pass Attempts" and t[0]["factor"] == 1.1 and t[0]["slot"] == ""
    assert PG.suggestions(rows[:10]) == []                                              # too few to act on
    assert PG.use_record(rows)[0]["Hit rate"] == 1.0
    bad = [dict(r, result="miss", model_hit=False, actual=30.0) for r in rows]
    assert any("Tighten" in s["text"] for s in PG.suggestions(bad))


def test_snapshot_store_upserts_and_tuning_round_trip(tmp_path, monkeypatch):
    db = str(tmp_path / "m.db")
    row = {"player": "Jordan Love", "pid": "00-1", "projection": 38.2, "line": 35.5, "side": "Over", "p_final": 0.6,
           "over_price": -110, "under_price": -110, "opp": 38.2, "slot": "QB", "flags": ["x"], "ev": 0.05, "lean": "Over"}
    rec = MS.snapshot_record("NFL", "2026-10-29", "CAR @ GB", row, "Pass Attempts", "GB", "CAR", kickoff="2099-01-01T00:00:00Z")
    assert rec["chance"] == 0.6 and rec["use_tag"] and rec["cushion"] > 0
    assert MS.save([rec], db) == 1
    assert MS.save([dict(rec, projection=40.0)], db) == 1                                # same key: updated, not added
    got = MS.load_snapshots("NFL", None, db)
    assert len(got) == 1 and got[0]["projection"] == 40.0
    assert MS.save([dict(rec, kickoff="2000-01-01T00:00:00Z")], db) == 0                 # after kickoff: never saved
    assert MS.snapshot_record("NFL", "d", "g", dict(row, line=None), "Pass Attempts") is None
    monkeypatch.setattr(MS, "DB_PATH", db)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert MS.approve_tuning("NFL", "Pass Attempts", 1.06, "results ran high", db_path=db)
    MT.clear_cache()
    assert abs(MT.factor("NFL", "Pass Attempts", "QB") - 1.06) < 1e-9 and MT.factor("NFL", "Receptions") == 1.0
    tid = MS.list_tuning(db_path=db)[0]["id"]
    assert MS.retire_tuning(tid, db_path=db)
    MT.clear_cache()
    assert MT.factor("NFL", "Pass Attempts") == 1.0


def test_postgame_page_grades_a_slate_and_offers_an_approval(monkeypatch):
    from streamlit.testing.v1 import AppTest
    snaps = [snap("Jordan Love", "GB", "Pass Attempts", 30.0, 29.5, "Over", opp=30.0, use=PE.USE_PARLAY, slot="QB")
             for _ in range(1)]
    many = [dict(snaps[0], player=f"QB{i}") for i in range(16)]
    monkeypatch.setattr(MS, "snapshot_dates", lambda sport, db_path=None: ["2026-10-29"])
    monkeypatch.setattr(MS, "load_snapshots", lambda sport=None, dates=None, db_path=None: snaps + many)
    monkeypatch.setattr(MS, "list_tuning", lambda active_only=True, db_path=None: [])
    box = PG.football_box(SUMMARY)
    for i in range(16):
        box["teams"]["GB"][f"qb{i}"] = {"pass_att": 41.0}
    monkeypatch.setattr(PG, "fetch_results", lambda sport, d, games, fetch=None: {("GB", "CAR"): box})
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "41_Postgame_Review.py"), default_timeout=30)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    txt = " ".join(m.value for m in at.markdown)
    assert "Was the Use tag right?" in txt and "Pass Attempts: results ran" in txt
    assert any(b.label == "Approve" for b in at.button)
