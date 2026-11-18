"""Nov 18: each saved prop keeps its first view and the first time it carried a bet tag; closing-line value compares
that entry with the last pre-game view."""
import clv as CLV
import model_store as MS
import props_engine as PE


def _rec(line, over, under, tag, ts, side="Over"):
    return {"sport": "NBA", "slate_date": "2030-01-01", "game": "A @ B", "team": "1", "opp": "2", "player": "P",
            "market": "Points", "projection": 20.0, "line": line, "side": side, "chance": 0.56, "use_tag": tag,
            "over_price": over, "under_price": under, "p_market": 0.5, "kickoff": "2030-01-02T00:00Z", "ts": ts,
            **{f"first_{k}": v for k, v in (("ts", ts), ("line", line), ("side", side), ("use_tag", tag),
                                            ("over_price", over), ("under_price", under))},
            **{f"bet_{k}": (v if tag != PE.USE_PASS else None) for k, v in
               (("ts", ts), ("line", line), ("side", side), ("use_tag", tag), ("over_price", over),
                ("under_price", under))}}


def test_entry_snapshots_survive_later_saves(tmp_path):
    db = str(tmp_path / "m.db")
    MS.save([_rec(19.5, -110, -110, PE.USE_PASS, "2030-01-01T14:00")], db_path=db)
    MS.save([_rec(19.5, -110, -110, PE.USE_SINGLE, "2030-01-01T15:00")], db_path=db)
    MS.save([_rec(20.5, -115, -105, PE.USE_PASS, "2030-01-01T23:00")], db_path=db)
    r = MS.load_snapshots("NBA", ["2030-01-01"], db_path=db)[0]
    assert r["line"] == 20.5 and r["use_tag"] == PE.USE_PASS                       # the latest view
    assert r["first_ts"] == "2030-01-01T14:00" and r["first_use_tag"] == PE.USE_PASS
    assert r["bet_ts"] == "2030-01-01T15:00" and r["bet_use_tag"] == PE.USE_SINGLE and r["bet_line"] == 19.5
    c = CLV.of(r)
    assert c["result"] == "beat" and c["line_move"] == 1.0                         # Over 19.5 -> line closed 20.5


def test_same_line_uses_the_no_vig_price():
    r = _rec(19.5, -130, +110, PE.USE_PASS, "2030-01-01T23:00", side="Under")
    r.update(bet_ts="2030-01-01T15:00", bet_line=19.5, bet_side="Under", bet_use_tag=PE.USE_SINGLE,
             bet_over_price=-110, bet_under_price=-110)
    c = CLV.of(r)
    assert c["result"] == "lost" and c["prob_move"] < -0.01                       # Under got cheaper: market went Over
    rec = CLV.record([r, dict(r, bet_ts=None)])
    assert rec[PE.USE_SINGLE]["lost"] == 1 and rec[PE.USE_SINGLE]["n"] == 1
    assert CLV.of(dict(r, bet_ts="2030-01-01T23:00")) is None                    # entry = close: nothing to measure


def test_snapshot_record_fills_entry_fields():
    row = {"player": "P", "projection": 25.0, "line": 20.5, "side": "Over", "p_final": 0.62, "over_price": -110,
           "under_price": -110, "p_market": 0.5}
    rec = MS.snapshot_record("NBA", "2030-01-01", "g", row, "Points", kickoff="2030-01-02T00:00Z")
    assert rec["first_line"] == 20.5 and rec["first_side"] == "Over" and rec["first_ts"] == rec["ts"]
    assert (rec["bet_ts"] is None) == (not rec["use_tag"] or PE.is_pass(rec["use_tag"]) or rec["use_tag"] == PE.USE_NO_LINE)


def test_a_bet_tag_that_drifted_is_graded_as_the_bet():
    import postgame as PG
    r = {"use_tag": PE.USE_PASS, "side": "Under", "result": "miss", "chance": 0.51,
         "bet_use_tag": PE.USE_SINGLE, "bet_side": "Over", "bet_result": "hit", "bet_chance": 0.58}
    rec = {x["Use"]: x for x in PG.use_record([r])}
    assert PE.USE_SINGLE in rec and PE.USE_PASS not in rec and rec[PE.USE_SINGLE]["Hits"] == 1
    old = {"use_tag": PE.USE_PASS, "side": "Under", "result": "miss"}               # saved before Nov 18
    assert PG.use_record([old])[0]["Use"] == PE.USE_PASS


def test_first_name_spellings_match_one_player_only():
    import postgame as PG
    roster = {"joshua metellus": {}, "dru phillips": {}, "bijan robinson": {}, "jordan mason": {}}
    assert PG._alias_name("josh metellus", roster) == "joshua metellus"
    assert PG._alias_name("andru phillips", roster) == "dru phillips"
    assert PG._alias_name("brian robinson", roster) is None                 # a different Robinson
    assert PG._alias_name("jordan addison", roster) is None
    assert PG._alias_name("josh metellus", dict(roster, **{"jose metellus": {}})) is None   # two candidates: no guess
