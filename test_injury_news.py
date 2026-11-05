"""Injury news on every row and the news + far-from-market rule (Nov 5)."""
import props_engine as PE
import slate_props as SP


def _rows():
    g = "JAX @ BAL"
    return {
        ("qb", "m"): {"player": "Lamar Jackson", "slot": "QB1", "out": True, "game": g, "team_id": "BAL", "opp_id": "JAX",
                      "team_name": "BAL", "opp_name": "JAX"},
        ("rb", "m"): {"player": "Derrick Henry", "slot": "RB1", "out": False, "game": g, "team_id": "BAL", "opp_id": "JAX",
                      "team_name": "BAL", "opp_name": "JAX", "flags": []},
        ("lb", "m"): {"player": "Foyesade Oluokun", "slot": "LB1", "out": False, "game": g, "team_id": "JAX",
                      "opp_id": "BAL", "team_name": "JAX", "opp_name": "BAL", "flags": []},
        ("bk", "m"): {"player": "Bench Guy", "slot": "G", "avg_min": 12.0, "out": True, "game": "A @ B", "team_id": "A",
                      "opp_id": "B"},
        ("st", "m"): {"player": "Star", "slot": "F", "avg_min": 34.0, "out": True, "game": "A @ B", "team_id": "A",
                      "opp_id": "B"},
        ("tm", "m"): {"player": "Teammate", "slot": "G", "avg_min": 30.0, "out": False, "game": "A @ B", "team_id": "A",
                      "opp_id": "B", "team_name": "A", "opp_name": "B", "flags": []},
    }


def test_rows_carry_own_and_opponent_key_absences():
    r = SP.attach_injury_news(_rows())
    assert r[("rb", "m")]["news_team"] == ["Lamar Jackson (QB1)"] and r[("rb", "m")]["flags"][0].startswith("🩹")
    assert r[("lb", "m")]["news_opp"] == ["Lamar Jackson (QB1)"] and r[("lb", "m")]["news_team"] == []
    assert r[("tm", "m")]["news_team"] == ["Star"]                  # a 12-minute bench player isn't key news


def test_news_plus_far_from_market_becomes_pass():
    row = {"news_team": ["Lamar Jackson (QB1)"], "news_opp": []}
    use, why = SP.news_guard(row, PE.USE_BOTH, "x", 1.55)
    assert use == PE.USE_PASS and "injury news" in why
    assert SP.news_guard(row, PE.USE_BOTH, "x", 1.44)[0] == PE.USE_BOTH          # under 1.50: kept (data: 59% hit)
    assert SP.news_guard({"news_team": [], "news_opp": []}, PE.USE_BOTH, "x", 2.0)[0] == PE.USE_BOTH
