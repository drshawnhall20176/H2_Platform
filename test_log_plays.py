import json

import betlog as B
import log_plays as L


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
    L.main(["--picks", f"@{f}", "--date", "2026-11-01", "--ticket", "ATD test", "--ticket-odds", "881"])
    bets = B.list_bets()
    assert len(bets) == 3 and sum(1 for b in bets if b["ticket"] == "ATD test") == 3
    hdr = next(b for b in bets if b["player"] is None)
    assert hdr["entry_odds"] == 881 and hdr["stake"] == 1.0
    L.main(["--picks", f"@{f}", "--date", "2026-11-01", "--ticket", "ATD test", "--ticket-odds", "881"])
    assert len(B.list_bets()) == 3
