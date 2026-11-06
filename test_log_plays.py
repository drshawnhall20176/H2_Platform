import json

import pytest

import betlog as B
import log_plays as L


@pytest.fixture(autouse=True)
def _no_reads(monkeypatch):
    import best_bets_data as BBD
    monkeypatch.setattr(BBD, "load_slate_reads", lambda *a, **k: {})


def test_model_prob_matches_the_picks_own_line(monkeypatch):
    bp = {"ModelProb": 0.58, "Line": 3.5}
    assert L._model_prob({"player": "K", "market": "Receptions", "side": "Over", "line": 3.5}, bp, {}, "NFL") == 0.58
    assert L._model_prob({"player": "K", "market": "Receptions", "side": "Over", "line": 1.5}, bp, {}, "NFL") is None
    import parlay_check as PC
    monkeypatch.setattr(PC, "read_leg", lambda leg, reads, sport: {"source": "model (alt line)", "p_raw": 0.84})
    assert L._model_prob({"player": "K", "market": "Receptions", "side": "Over", "line": 1.5}, bp, {"x": 1}, "NFL") == 0.84


def test_picks_get_board_ids_and_rerunning_skips_duplicates(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    monkeypatch.setattr(B, "DB_PATH", db)
    monkeypatch.setattr(B, "USING_POSTGRES", False, raising=False)
    import export_board as X
    monkeypatch.setattr(X, "board", lambda *a, **k: [{"Player": "Justin Jefferson", "Market": "Receptions", "Side": "Under",
                                                      "PlayerId": "123", "ModelProb": 0.64, "Game": "MIN @ DET",
                                                      "Notes": "use:both"}])
    picks = [{"player": "Justin Jefferson", "market": "Receptions", "side": "Under", "line": 6.5, "odds": -138},
             {"player": "Nobody", "market": "Receptions", "side": "Over", "line": 1.5, "odds": -110, "game": "A @ B"}]
    f = tmp_path / "p.json"
    f.write_text(json.dumps(picks))
    import inspect
    if "db_path" in inspect.signature(B.list_bets).parameters:
        monkeypatch.setattr(B, "list_bets", lambda *a, _l=B.list_bets, **k: _l(db_path=db, **{x: y for x, y in k.items() if x != "db_path"}))
        monkeypatch.setattr(B, "add_bet", lambda _a=B.add_bet, **k: _a(db_path=db, **k))
    assert L.main(["--picks", f"@{f}", "--date", "2026-11-01", "--tag", "discord-unders"]) == 0
    bets = B.list_bets()
    assert len(bets) == 2
    j = next(b for b in bets if b["player"] == "Justin Jefferson")
    assert j["player_id"] == 123 and j["game"] == "MIN @ DET" and not j["is_real_bet"] and j["category"] == "H2"
    assert "discord-unders" in j["notes"]
    L.main(["--picks", f"@{f}", "--date", "2026-11-01"])
    assert len(B.list_bets()) == 2


def test_ticket_mode_logs_one_parlay(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    import export_board as X
    monkeypatch.setattr(X, "board", lambda *a, **k: [])
    monkeypatch.setattr(B, "list_bets", lambda *a, _l=B.list_bets, **k: _l(db_path=db, **{x: y for x, y in k.items() if x != "db_path"}))
    monkeypatch.setattr(B, "add_bet", lambda *a, _a=B.add_bet, **k: _a(db, **k))
    picks = [{"player": "Jahmyr Gibbs", "market": "Anytime TD", "side": "Over", "line": 0.5, "odds": -240, "game": "MIN @ DET"},
             {"player": "CeeDee Lamb", "market": "Anytime TD", "side": "Over", "line": 0.5, "odds": -145, "game": "ARI @ DAL"}]
    f = tmp_path / "p.json"
    f.write_text(json.dumps(picks))
    L.main(["--picks", f"@{f}", "--date", "2026-11-01", "--ticket", "ATD test", "--ticket-odds", "881", "--real", "true"])
    bets = B.list_bets()
    assert len(bets) == 3 and sum(1 for b in bets if b["ticket"] == "ATD test") == 3
    hdr = next(b for b in bets if b["player"] is None)
    assert hdr["entry_odds"] == 881 and hdr["stake"] == 1.0
    L.main(["--picks", f"@{f}", "--date", "2026-11-01", "--ticket", "ATD test", "--ticket-odds", "881"])
    assert len(B.list_bets()) == 3


def test_tracking_ticket_is_not_money(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    import export_board as X
    monkeypatch.setattr(X, "board", lambda *a, **k: [])
    monkeypatch.setattr(B, "list_bets", lambda *a, _l=B.list_bets, **k: _l(db_path=db, **{x: y for x, y in k.items() if x != "db_path"}))
    monkeypatch.setattr(B, "add_bet", lambda *a, _a=B.add_bet, **k: _a(db, **k))
    monkeypatch.setattr(B, "update_bet", lambda bid, _u=B.update_bet, **k: _u(bid, db, **k))
    f = tmp_path / "p.json"
    f.write_text(json.dumps([{"player": "A", "market": "Receptions", "side": "Over", "line": 1.5, "odds": -300, "game": "X @ Y"}]))
    L.main(["--picks", f"@{f}", "--date", "2026-11-02", "--ticket", "T", "--ticket-odds", "260"])
    assert all(not b["is_real_bet"] for b in B.list_bets())


def test_parlay_leg_does_not_block_the_same_single(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    import export_board as X
    monkeypatch.setattr(X, "board", lambda *a, **k: [])
    monkeypatch.setattr(B, "list_bets", lambda *a, _l=B.list_bets, **k: _l(db_path=db, **{x: y for x, y in k.items() if x != "db_path"}))
    monkeypatch.setattr(B, "add_bet", lambda *a, _a=B.add_bet, **k: _a(db, **k))
    monkeypatch.setattr(B, "update_bet", lambda bid, _u=B.update_bet, **k: _u(bid, db, **k))
    f = tmp_path / "p.json"
    f.write_text(json.dumps([{"player": "Cooper Kupp", "market": "Receptions", "side": "Over", "line": 1.5, "odds": -466,
                              "game": "CHI @ SEA"}]))
    L.main(["--picks", f"@{f}", "--date", "2026-11-02", "--ticket", "MNF", "--ticket-odds", "260"])
    L.main(["--picks", f"@{f}", "--date", "2026-11-02", "--real", "true", "--stake", "5"])
    singles = [b for b in B.list_bets() if not b.get("ticket")]
    assert len(singles) == 1 and singles[0]["stake"] == 5


def test_fix_model_refreshes_singles_and_legs(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    import export_board as X
    monkeypatch.setattr(X, "board", lambda *a, **k: [])
    monkeypatch.setattr(B, "list_bets", lambda *a, _l=B.list_bets, **k: _l(db_path=db, **{x: y for x, y in k.items() if x != "db_path"}))
    monkeypatch.setattr(B, "add_bet", lambda *a, _a=B.add_bet, **k: _a(db, **k))
    monkeypatch.setattr(B, "update_bet", lambda bid, _u=B.update_bet, **k: _u(bid, db, **k))
    f = tmp_path / "p.json"
    f.write_text(json.dumps([{"player": "Cooper Kupp", "market": "Receptions", "side": "Over", "line": 1.5, "odds": -466,
                              "game": "CHI @ SEA"}]))
    L.main(["--picks", f"@{f}", "--date", "2026-11-02", "--ticket", "MNF", "--ticket-odds", "260"])
    L.main(["--picks", f"@{f}", "--date", "2026-11-02", "--real", "true", "--stake", "5"])
    monkeypatch.setattr(L, "_model_prob", lambda *a, **k: 0.84)
    L.main(["--picks", f"@{f}", "--date", "2026-11-02", "--fix-model", "true"])
    kupp = [b for b in B.list_bets() if b["player"] == "Cooper Kupp"]
    assert len(kupp) == 2 and all(abs(b["model_prob"] - 0.84) < 1e-9 for b in kupp)


def test_known_result_is_recorded_on_a_won_parlay(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    import export_board as X
    monkeypatch.setattr(X, "board", lambda *a, **k: [])
    monkeypatch.setattr(B, "list_bets", lambda *a, _l=B.list_bets, **k: _l(db_path=db, **{x: y for x, y in k.items() if x != "db_path"}))
    monkeypatch.setattr(B, "add_bet", lambda *a, _a=B.add_bet, **k: _a(db, **k))
    monkeypatch.setattr(B, "update_bet", lambda bid, _u=B.update_bet, **k: _u(bid, db, **k))
    f = tmp_path / "p.json"
    f.write_text(json.dumps([{"player": "Otef Darom", "market": "Spread", "side": "Otef Darom", "line": -26.5, "odds": -140,
                              "game": "Hapoel Migdal Haemek @ Otef Darom"},
                             {"player": "Game total", "market": "Total", "side": "Over", "line": 175.5, "odds": -124,
                              "game": "Vytis @ Perlas"}]))
    L.main(["--picks", f"@{f}", "--date", "2026-11-03", "--sport", "INTL", "--ticket", "Live 5", "--ticket-odds", "1740",
            "--stake", "9", "--real", "true", "--result", "win"])
    bets = B.list_bets()
    hdr = next(b for b in bets if B.is_parlay_header(b))
    assert hdr["result"] == "win" and abs(B.bet_pnl(hdr) - 156.6) < 0.01
    assert all(b["result"] == "win" for b in bets)


def test_moneyline_parlay_without_lines(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    import export_board as X
    monkeypatch.setattr(X, "board", lambda *a, **k: [])
    monkeypatch.setattr(B, "list_bets", lambda *a, _l=B.list_bets, **k: _l(db_path=db, **{x: y for x, y in k.items() if x != "db_path"}))
    monkeypatch.setattr(B, "add_bet", lambda *a, _a=B.add_bet, **k: _a(db, **k))
    monkeypatch.setattr(B, "update_bet", lambda bid, _u=B.update_bet, **k: _u(bid, db, **k))
    f = tmp_path / "p.json"
    f.write_text(json.dumps([{"player": "Maxence Rivet", "market": "Moneyline", "side": "Maxence Rivet", "line": None,
                              "odds": -600, "game": "Rivet vs Barsukov"}]))
    L.main(["--picks", f"@{f}", "--date", "2026-11-04", "--sport", "TENNIS", "--ticket", "T", "--ticket-odds", "751",
            "--stake", "11", "--real", "true", "--result", "win"])
    L.main(["--picks", f"@{f}", "--date", "2026-11-04", "--sport", "TENNIS", "--real", "true", "--stake", "2"])
    bets = B.list_bets()
    hdr = next(b for b in bets if B.is_parlay_header(b))
    assert hdr["result"] == "win" and abs(B.bet_pnl(hdr) - 82.61) < 0.01
    assert sum(1 for b in bets if not b.get("ticket")) == 1                 # the single logs too (no line is fine)


def test_player_id_falls_back_to_model_reads(monkeypatch):
    """Nov 5: a defender's tackle prop isn't on the exported board, but the model read has his ID."""
    import log_plays as LP
    import parlay_check as PC
    monkeypatch.setattr(PC, "_find", lambda reads, player, market: {"pid": 3124890} if player == "Roquan Smith" else None)
    pk = {"player": "Roquan Smith", "market": "Tackles + Assists", "side": "Under", "line": 9.5, "odds": -121,
          "game": "Jacksonville Jaguars @ Baltimore Ravens", "model_prob": 0.62}
    rows = LP.build([pk], [], "NFL", "2026-11-05", reads={"x": 1})
    assert rows[0]["player_id"] == 3124890
    rows = LP.build([dict(pk, player_id=77)], [], "NFL", "2026-11-05", reads={"x": 1})
    assert rows[0]["player_id"] == 77


def test_against_model_flags_low_chance_and_missing_reads():
    import log_plays as LP
    assert "32%" in LP.against_model({"model_prob": 0.3163})
    assert "no model read" in LP.against_model({"model_prob": None})
    assert LP.against_model({"model_prob": 0.62}) == ""
