"""Oct 29: Pass Attempts / Pass Completions on NFL Position Matchups (Player props) and the shared slate model."""
import football_props as FP
import slate_props as SP


def qb_games():
    out = []
    for w in range(1, 7):
        for t in range(10):
            out.append(dict(game=f"{t}-{w}", order=w, team=f"O{t}", opp=f"D{t}", pid=f"q{t}", name=f"QB{t}", pos="QB",
                            stats=dict(pass_att=34 + (6 if t == 0 else 0), pass_cmp=22, pass_yds=230, pass_td=1)))
    return out


def test_menus():
    assert "Pass Attempts" in FP.markets_for("NFL") and "Pass Completions" in FP.markets_for("NFL")
    assert "Pass Attempts" in FP.markets_for("NCAAF") and "Pass Completions" not in FP.markets_for("NCAAF")
    assert FP.MARKETS["Pass Attempts"]["odds"] == "player_pass_attempts"


def test_projection_reads_volume_against_the_defense():
    import position_matchups as PM
    pg = qb_games()
    allowed = PM.allowed_by_slot(pg, "NFL")
    roster = [{"pid": "q5", "name": "QB5", "slot": "QB"}]
    soft = FP.player_rows(roster, "O5", "D0", "Pass Attempts", pg, allowed)[0]       # D0 faces 40 attempts a game
    even = FP.player_rows(roster, "O5", "D3", "Pass Attempts", pg, allowed)[0]
    assert 30 < even["projection"] < 38 and soft["projection"] > even["projection"]
    assert soft["sd_floor"] == (0.18, 5.0)
    cmp_ = FP.player_rows(roster, "O5", "D3", "Pass Completions", pg, allowed, lines={"q5": 21.5})[0]
    assert 18 < cmp_["projection"] < 26 and cmp_["line"] == 21.5 and cmp_["p_model"] is not None
