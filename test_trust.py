"""Nov 17: trust in the model vs the books -- forced toward the market, earned back on held-out days."""
import calibration as CAL
import props_engine as PE


def test_apply_trust_moves_toward_market():
    assert CAL.apply_trust(0.70, 0.50, 0.5) == 0.60
    assert CAL.apply_trust(0.70, 0.50, 1.0) == 0.70
    assert CAL.apply_trust(0.70, None, 0.5) == 0.70


def test_read_line_uses_trust():
    vals = [10, 12, 14, 9, 11, 13, 15, 10]
    a = PE.read_line(14.0, vals, 11.5, "normal", -110, -110, 0.5)
    b = PE.read_line(14.0, vals, 11.5, "normal", -110, -110, 0.5, trust=0.5)
    assert abs((b["p_final"] - 0.5) - 0.5 * (a["p_final"] - 0.5)) < 1e-9


def _graded(n_days, per_day, model_p, mkt, hit_rate, market="Points"):
    out = {}
    for d in range(n_days):
        rows = []
        for i in range(per_day):
            y = (i / per_day) < hit_rate
            rows.append({"result": "hit" if y else "miss", "chance": model_p, "p_market": mkt, "side": "Over",
                         "market": market, "game": f"g{i % 7}", "ts": f"2026-11-{d + 1:02d}T12:00"})
        out[f"2026-11-{d + 1:02d}"] = rows
    return out


def test_auto_trust_pulls_toward_market_when_the_books_were_right(monkeypatch):
    monkeypatch.setattr(CAL, "trust", lambda s, m=None: 1.0)
    monkeypatch.setattr(CAL, "factor_history", lambda k: [])
    g = _graded(5, 80, 0.62, 0.50, 0.50)             # model said 62%, books 50%, it hit 50%
    dec = CAL.auto_trust("NBA", g, "2026-11-17", write=False)[0]
    assert dec["new"] == 0.1 and "books were closer" in dec["why"]


def test_auto_trust_needs_proof_to_move_back(monkeypatch):
    monkeypatch.setattr(CAL, "trust", lambda s, m=None: 0.5)
    monkeypatch.setattr(CAL, "factor_history", lambda k: [])
    g = _graded(5, 80, 0.56, 0.50, 0.62)             # shown 56% (after trust 0.5), hit 62% -> more trust fits
    dec = CAL.auto_trust("NBA", g, "2026-11-17", write=False)[0]
    assert dec["new"] > 0.5 and ("earned" in dec["why"] or "didn't hold up" in dec["why"])


def test_td_rows_fit_separately(monkeypatch):
    monkeypatch.setattr(CAL, "trust", lambda s, m=None: 1.0)
    monkeypatch.setattr(CAL, "factor_history", lambda k: [])
    g = _graded(4, 70, 0.32, 0.22, 0.18, market="Anytime TD")
    out = CAL.auto_trust("NFL", g, "2026-11-17", write=False)
    td = [d for d in out if d["kind"] == "td"][0]
    assert td["new"] == 0.1 and CAL._trust_key("NFL", "Anytime TD") == "NFL:trust:TD"


def test_auto_trust_wont_cut_on_noise(monkeypatch):
    """Nov 18: NBA went 0.54 -> 0.46 with log loss flat and 1 of 13 held-out splits -- a cut needs evidence too."""
    monkeypatch.setattr(CAL, "trust", lambda s, m=None: 0.5)
    monkeypatch.setattr(CAL, "factor_history", lambda k: [])
    g = {f"2026-11-{d + 1:02d}": _graded(1, 100, 0.52, 0.50, hr)["2026-11-01"]
         for d, hr in enumerate([0.60, 0.40, 0.60, 0.40, 0.60, 0.40])}       # 50% overall, noisy days
    dec = CAL.auto_trust("NBA", g, "2026-11-18", write=False)[0]
    assert "not by enough" in dec["why"] and not dec["applied"]


def _graded_mk(days, per_day, specs):
    """specs: [(market, model chance, market chance, hit rate)]"""
    out = {}
    for d in range(days):
        rows = []
        for mk, p, m, hr in specs:
            for i in range(per_day):
                y = ((i * 7 + d * 3) % per_day) / per_day < hr
                rows.append({"result": "hit" if y else "miss", "chance": p, "p_market": m, "side": "Over",
                             "market": mk, "game": f"g{i % 7}", "ts": f"2026-11-{d + 1:02d}T12:00"})
        out[f"2026-11-{d + 1:02d}"] = rows
    return out


def test_a_market_earns_its_own_trust_and_the_sport_keeps_its(monkeypatch):
    """Nov 18 (research/widen_test.py): Assists earn more model weight than the sport's; Points don't."""
    store = {"NBA:trust": 0.5}
    monkeypatch.setattr(CAL, "factor", lambda s: 1.0)
    monkeypatch.setattr(CAL, "_cache", {"at": 1e18, "map": store})
    monkeypatch.setattr(CAL, "factor_history", lambda k: [("2026-10-01", store[k])] if k in store else [])
    # shown 54% (trust 0.5 around a 50% book) and they hit 58%: the model's own 58% was right -> more trust holds up
    g = _graded_mk(8, 90, [("Assists", 0.54, 0.50, 0.58), ("Points", 0.54, 0.50, 0.50)])
    out = {d["market"]: d for d in CAL.auto_trust_markets("NBA", g, "2026-11-18", write=False)}
    assert out["Assists"]["new"] > 0.5 and "held up" in out["Assists"]["why"]
    assert out["Points"]["new"] < 0.5
    assert CAL.trust("NBA", "Assists") == 0.5                      # nothing written in a dry run
    store["NBA:trust:m:Assists"] = 0.8
    assert CAL.trust("NBA", "Assists") == 0.8 and CAL.trust("NBA", "Points") == 0.5
    assert CAL.trust("NBA", "Anytime TD") == 1.0 and CAL.market_trusts("NBA") == {"Assists": 0.8}
    rows = CAL.trust_rows("NBA", g, "props", exclude=["Assists"])
    assert len(rows) == 8 * 90                                      # the sport fit leaves Assists out


def test_a_market_needs_held_out_proof_either_way(monkeypatch):
    store = {"NBA:trust": 0.5}
    monkeypatch.setattr(CAL, "factor", lambda s: 1.0)
    monkeypatch.setattr(CAL, "_cache", {"at": 1e18, "map": store})
    monkeypatch.setattr(CAL, "factor_history", lambda k: [("2026-10-01", store[k])] if k in store else [])
    g = _graded_mk(2, 300, [("Assists", 0.54, 0.50, 0.58)])         # plenty of reads but 2 days: no splits
    d = CAL.auto_trust_markets("NBA", g, "2026-11-18", write=False)[0]
    assert not d["applied"] and ("not enough" in d["why"] or "didn't hold up" in d["why"])
