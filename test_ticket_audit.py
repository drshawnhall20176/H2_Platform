"""Nov 7: the full pre-bet check as one tool."""
import props_engine as PE
import ticket_audit as T


def test_live_price_reads_the_odds_feed_layout():
    import analyst as A
    offers = [{"market": "player_rebounds", "player": "Draymond Green", "point": 5.5,
               "over": {"draftkings": 105, "fanduel": 110}, "under": {"draftkings": -139, "fanduel": -141, "betmgm": -132}},
              {"market": "player_rebounds", "player": "Draymond Green", "point": 6.5,
               "over": {"draftkings": 160}, "under": {"draftkings": -210}}]
    idx = A.index_offers(offers)
    lp = T.live_price(idx, "Draymond Green", "player_rebounds", "Under", 5.5)
    assert lp["price"] == -139 and lp["others"] == [-141, -132] and lp["line_now"] is None
    moved = T.live_price(idx, "Draymond Green", "player_rebounds", "Under", 4.5)
    assert moved["price"] is None and moved["line_now"] == 5.5


def test_team_and_status_helpers():
    assert T.is_out("Out") and T.is_out("Doubtful") and not T.is_out("Day-To-Day")
    assert T.same_team("Houston Rockets", "Rockets") and not T.same_team("Houston Rockets", "Phoenix Suns")


def _leg(player, game, use, chance=0.6, price=-130, flags=(), ev=None):
    dec = PE.decimal(price)
    return {"player": player, "game": game, "use": use, "chance": chance, "price": price, "by_script": None,
            "scripts": None, "flags": list(flags), "ev": chance * dec - 1 if ev is None else ev, "market": "Rebounds",
            "side": "Under", "line": 5.5}


def test_best_tickets_respects_the_platform_rules():
    legs = [_leg("A", "G1", PE.USE_PARLAY), _leg("B", "G1", PE.USE_PARLAY), _leg("C", "G1", PE.USE_PARLAY),
            _leg("D", "G2", PE.USE_PARLAY), _leg("E", "G3", PE.USE_SINGLE, 0.58, -116),
            _leg("F", "G4", PE.USE_SINGLE, 0.59, -115), _leg("G", "G5", PE.USE_PARLAY, flags=["rotation teammate out"]),
            _leg("H", "G6", PE.USE_PASS, 0.7, 120)]
    tix = T.best_tickets(legs, sizes=(4,), max_single_only=1)
    assert tix
    for t in tix:
        names = [c["player"] for c in t["legs"]]
        assert sum(1 for c in t["legs"] if c["game"] == "G1") <= 2          # at most two per game
        assert "G" not in names and "H" not in names                       # flagged / Pass legs never
        assert t["single_only"] <= 1
    assert T.best_tickets(legs, sizes=(4,), max_single_only=0) == []        # only A-D tagged, 3 of them in one game


def test_only_absences_the_model_has_not_seen_are_flagged(monkeypatch):
    """A teammate out that the model already bumped for is priced (Unders 55.7% vs 55.0%); one ruled out after the
    board was built is flagged on an Under."""
    import analyst as A
    import script_effects as SE
    plays = [
        {"Model": "player-props", "Player": "Amen Thompson", "Team": "Houston Rockets", "Game": "HOU @ PHX", "Market": "Rebounds",
         "Side": "Under", "Line": 6.5, "ModelProb": 0.57, "RealPrice": 112, "Use": PE.USE_SINGLE, "GameDate": "2099-01-01T02:00:00Z",
         "Flags": ["↑ usage bump (Steven Adams out)"], "_game_log": [{"min": 34.0}] * 5},
        {"Model": "player-props", "Player": "Clint Capela", "Team": "Houston Rockets", "Game": "HOU @ PHX", "Market": "Rebounds",
         "Side": "Over", "Line": 6.5, "ModelProb": 0.5, "RealPrice": -110, "Use": PE.USE_PASS, "GameDate": "2099-01-01T02:00:00Z",
         "_game_log": [{"min": 20.0}] * 5},
        {"Model": "player-props", "Player": "Steven Adams", "Team": "Houston Rockets", "Game": "HOU @ PHX", "Market": "Rebounds",
         "Side": "Over", "Line": 5.5, "ModelProb": 0.5, "RealPrice": -110, "Use": PE.USE_PASS, "GameDate": "2099-01-01T02:00:00Z",
         "_game_log": [{"min": 18.0}] * 5}]
    inj = {PE.norm_name("Clint Capela"): {"status": "Out", "team": "Houston Rockets", "note": ""},
           PE.norm_name("Steven Adams"): {"status": "Out", "team": "Houston Rockets", "note": ""}}
    deps = {"api_key": lambda: None, "fetch_offers": lambda *a: [], "game_env": lambda *a: ({}, ""),
            "matchups": lambda *a: ({}, "")}
    monkeypatch.setattr(A, "scan", lambda *a, **k: [])
    monkeypatch.setattr(SE, "fetch_lines", lambda *a, **k: [])
    monkeypatch.setattr(SE, "calls", lambda *a, **k: {})
    import line_history as LH
    monkeypatch.setattr(LH, "sport_index", lambda *a, **k: {})
    legs = T.audit("NBA", "2099-01-01", deps=deps, plays=plays, injuries=inj)
    amen = next(x for x in legs if x["player"] == "Amen Thompson")
    late = [f for f in amen["flags"] if f.startswith("teammate ruled out after")]
    assert late and "capela" in late[0].lower() and "adams" not in late[0].lower()
