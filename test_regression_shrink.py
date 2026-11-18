"""Nov 14: regression to the mean in the props models (research/stability_audit.py, regression_test.py,
regression_validate.py)."""
import football_props as FP
import hockey_props as HP
import player_props as PPR
import props_engine as PE


def test_shrink_toward_weights_by_sample():
    assert PE.shrink_toward(0.5, [30, 30], 0.3, 0) == 0.5
    small = PE.shrink_toward(0.5, [10], 0.3, 45)
    big = PE.shrink_toward(0.5, [36] * 10, 0.3, 45)
    assert 0.3 < small < big < 0.5
    assert PE.shrink_toward(None, [30], 0.3, 45) is None
    assert PE.shrink_toward(0.5, [0, 0], 0.3, 45) == 0.3


def test_nba_settings_points_keep_their_own_rate():
    assert PPR.shrink_minutes("Points") == 0 and PPR.shrink_minutes("PRA") == 0
    assert PPR.shrink_minutes("Steals") > PPR.shrink_minutes("Rebounds") > 0
    pg = [{"stats": {"min": 30, "reb": 6, "pts": 15}}, {"stats": {"min": 5, "reb": 9}}]
    assert abs(PPR.league_rate(pg, "Rebounds") - 0.2) < 1e-9          # bench cameos left out


def test_football_and_hockey_settings():
    assert FP.shrink_k("Interceptions", "QB", "pass_att") == 1200.0
    assert FP.shrink_k("Pass Yards", "QB", "pass_att") == FP.EFF_SHRINK["pass_att"]
    assert FP.shrink_k("Rush Yards", "QB", "rush_att") == FP.QB_RUSH_SHRINK
    assert FP.shrink_k("Receptions", "WR", "tgt", promoted=True) == FP.EFF_SHRINK["tgt"] * FP.PROMOTED_SHRINK_MULT
    assert HP.SHRINK_MIN["sog"] == 90.0


def test_group_prior_and_measured_correlation():
    import slip_sim as SIM
    pg = [{"pos": "C", "stats": {"min": 30, "reb": 12}}, {"pos": "G", "stats": {"min": 30, "reb": 3}}]
    assert abs(PPR.league_rate(pg, "Rebounds", group="C") - 0.4) < 1e-9
    assert abs(PPR.league_rate(pg, "Rebounds") - 0.25) < 1e-9
    a = {"sport": "NHL", "game": "g", "player": "A", "team": "X", "side": "Over"}
    b = {"sport": "NHL", "game": "g", "player": "B", "team": "X", "side": "Over"}
    c = {"sport": "NHL", "game": "g", "player": "C", "team": "Y", "side": "Over"}
    R = SIM.correlation_matrix([a, b, c])
    assert abs(R[0, 1] - 0.19) < 0.02 and abs(R[0, 2] - 0.15) < 0.02
    assert abs(SIM.correlation_matrix([a, b], rho_game=0.08)[0, 1] - 0.08) < 1e-6      # a slider still wins
    assert SIM.measured_rho("NBA") == (0.27, -0.01) and SIM.measured_rho("MLB") == (0.30, 0.08)


def test_record_label_shows_its_range():
    import pick_records as PR
    assert "±" in PR.label(24, 41)
    assert PR.margin(24, 41) > PR.margin(240, 410)
