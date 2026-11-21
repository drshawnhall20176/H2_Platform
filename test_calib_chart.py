import calib_chart as CC


def _b(d, p, r):
    return {"slate_date": d, "model_prob": p, "result": r, "kind": "single", "market": "Points", "player": "A"}


def test_two_eras():
    bets = [_b("2026-11-20", 0.7, "win"), _b("2026-11-20", 0.7, "loss"), _b("2026-11-21", 0.55, "win")]
    parts = CC.split(bets)
    assert len(parts["before"]) == 2 and len(parts["since"]) == 1
    fig = CC.figure(bets, "t")
    assert fig is not None and len(fig.data) >= 2
