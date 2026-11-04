import betlog as B
import model_store as MS
import reconcile_bets as R


def test_settles_slip_game_lines_from_finals(tmp_path, monkeypatch, capsys):
    bdb, mdb = str(tmp_path / "b.db"), str(tmp_path / "m.db")
    monkeypatch.setattr(B, "list_bets", lambda *a, _l=B.list_bets, **k: _l(db_path=bdb, **{x: y for x, y in k.items() if x != "db_path"}))
    monkeypatch.setattr(B, "update_bet", lambda bid, _u=B.update_bet, **k: _u(bid, bdb, **k))
    MS.save_results("NCAAMB", [{"id": "n1", "date": "2026-11-04", "home_team": "Kentucky Wildcats", "away_team": "Manhattan Jaspers",
                                "home_points": 95, "away_points": 60}], db_path=mdb)
    MS.save_results("NHL", [{"id": "h1", "date": "2026-11-04", "home_team": "Columbus Blue Jackets",
                             "away_team": "Colorado Avalanche", "home_points": 3, "away_points": 2}], db_path=mdb)
    monkeypatch.setattr(MS, "load_results", lambda sport, since=None, db_path=None, _l=MS.load_results: _l(sport, since, db_path=mdb))
    for f in ({"sport": "NCAAMB", "player": "Manhattan", "market": "Spread", "side": "Manhattan", "line": 33.5,
               "game": "Manhattan @ Kentucky"},
              {"sport": "NCAAMB", "player": "Game total", "market": "Total", "side": "Under", "line": 158.5,
               "game": "Manhattan @ Kentucky"},
              {"sport": "NHL", "player": "Colorado Avalanche", "market": "Puck Line", "side": "Colorado Avalanche",
               "line": 1.5, "game": "Colorado Avalanche @ Columbus Blue Jackets"},
              {"sport": "NHL", "player": "Colorado Avalanche", "market": "Moneyline", "side": "Colorado Avalanche",
               "line": None, "game": "Colorado Avalanche @ Columbus Blue Jackets"}):
        B.add_bet(bdb, slate_date="2026-11-03", entry_odds=-110, stake=4, **f)
    assert R.main(["--dates", "2026-11-03", "--apply"]) == 0
    got = {(b["market"], b["side"]): b["result"] for b in B.list_bets()}
    assert got == {("Spread", "Manhattan"): "loss", ("Total", "Under"): "win", ("Puck Line", "Colorado Avalanche"): "win",
                   ("Moneyline", "Colorado Avalanche"): "loss"}
    out = capsys.readouterr().out
    assert "Settled now from final scores: 4" in out and "Real · 2026-11-03 · NCAAMB" in out
