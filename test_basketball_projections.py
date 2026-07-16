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


# ----------------------------------------------------------------- shrink_prob
def test_shrink_prob_pulls_small_samples_hard_toward_reference():
    # A "perfect" 4/4 streak (raw prob 1.0) should get pulled well below 1.0, since only 4 real
    # games back it — the whole point of this function.
    shrunk = BB_P.shrink_prob(1.0, n_games=4, prior_strength=4.0, reference=0.5)
    assert shrunk == (1.0 * 4 + 4.0 * 0.5) / (4 + 4.0) == 0.75
    print("✓ shrink_prob pulls a small-sample 'perfect' streak meaningfully below 1.0")


def test_shrink_prob_barely_touches_large_samples():
    # A 40-game "perfect" streak should stay close to 1.0 — plenty of real evidence backs it,
    # so the fixed prior_strength=4.0 barely moves it.
    shrunk = BB_P.shrink_prob(1.0, n_games=40, prior_strength=4.0, reference=0.5)
    assert shrunk > 0.95
    print("✓ shrink_prob leaves a large-sample streak close to its raw value")


def test_shrink_prob_different_sample_sizes_no_longer_produce_identical_output():
    # THE actual bug this fixes: before shrinkage, a 4/4 streak and a 10/10 streak both fed
    # _clip_prob a raw 1.0 and came out identically at 0.98. After shrinkage, they're different —
    # the 10-game streak (more real evidence) shrinks less than the 4-game one.
    shrunk_4 = BB_P.shrink_prob(1.0, n_games=4)
    shrunk_10 = BB_P.shrink_prob(1.0, n_games=10)
    assert shrunk_4 != shrunk_10
    assert shrunk_10 > shrunk_4   # more real games backing the streak -> less shrinkage
    print("✓ shrink_prob makes a 4-game and a 10-game 'perfect' streak produce genuinely different numbers")


def test_shrink_prob_matches_reference_at_zero_games():
    assert BB_P.shrink_prob(0.9, n_games=0) == 0.5   # no data at all -> the neutral baseline, not a guess


def test_shrink_prob_leaves_reference_itself_unchanged():
    # If the raw prob already equals the reference (50/50), shrinkage is a no-op regardless of n.
    assert BB_P.shrink_prob(0.5, n_games=4) == 0.5
    assert BB_P.shrink_prob(0.5, n_games=40) == 0.5


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
