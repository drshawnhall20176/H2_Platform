"""
test_basketball_projections.py — offline unit tests for basketball_projections.py, the shared
league-agnostic projections layer (WNBA today, NBA whenever that build starts).

    python test_basketball_projections.py     # or: pytest test_basketball_projections.py
"""

import basketball_projections as BB_P


def test_blowout_risk_tag_flags_large_spreads_either_direction():
    assert BB_P.blowout_risk_tag(-14.5) == "⚠️ Blowout risk"   # heavy favorite
    assert BB_P.blowout_risk_tag(14.5) == "⚠️ Blowout risk"    # heavy underdog
    assert BB_P.blowout_risk_tag(-10.0) == "⚠️ Blowout risk"   # exactly at threshold


def test_blowout_risk_tag_competitive_below_threshold():
    assert BB_P.blowout_risk_tag(-6.5) == "Competitive"
    assert BB_P.blowout_risk_tag(0.0) == "Competitive"


def test_blowout_risk_tag_respects_custom_threshold():
    assert BB_P.blowout_risk_tag(-7.0, threshold=6.0) == "⚠️ Blowout risk"
    assert BB_P.blowout_risk_tag(-7.0, threshold=8.0) == "Competitive"


def test_blowout_risk_tag_unknown_when_no_spread():
    assert BB_P.blowout_risk_tag(None) == "—"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
