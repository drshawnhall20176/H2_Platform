import random
import calibration as CAL
import postgame as PG


def test_auto_global_applies_when_overconfident_and_holds_out(monkeypatch):
    random.seed(1)
    by = {}
    for d in range(6):
        day = f"2026-11-0{d + 1}"
        rows = []
        for _ in range(120):
            p = 0.70
            rows.append({"result": "hit" if random.random() < 0.58 else "miss", "chance": p, "market": "Points"})
        by[day] = rows
    monkeypatch.setattr(CAL, "factor", lambda s: 1.0)
    import model_store as MS
    monkeypatch.setattr(MS, "list_calibration", lambda: [])
    applied = []
    monkeypatch.setattr(MS, "approve_calibration", lambda k, s, d: applied.append((k, s)) or True)
    dec = CAL.auto_global("NBA", by, "2026-11-10")
    assert dec["applied"] and applied[0][0] == "NBA" and applied[0][1] < 0.7


def _rows(n_slates, per, actual, proj=10.0, market="Anytime TD", start=1):
    return [{"sport": "NFL", "market": market, "slot": "", "slate_date": f"2026-11-{start + s:02d}", "result": "miss",
             "actual": actual, "projection": proj} for s in range(n_slates) for _ in range(per)]


def test_auto_tuning_uses_only_props_since_the_last_change():
    rows = _rows(4, 15, 7.0)                                     # results 30% under the projections, 4 slates
    got = []
    dec = PG.auto_tunings(rows, [], "2026-11-10", approve=lambda *a, **k: got.append((a, k)) or True)
    assert dec and dec[0]["applied"] and got[0][0][2] == 0.9      # one step, capped at -10%
    old = [{"sport": "NFL", "market": "Anytime TD", "slot": "", "factor": 0.9, "approved_ts": "2026-11-09T08:00"}]
    dec2 = PG.auto_tunings(rows, old, "2026-11-10", approve=lambda *a, **k: True)
    assert all(not d["applied"] for d in dec2)                   # those slates predate the change: not enough since
