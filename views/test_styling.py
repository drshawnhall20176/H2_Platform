"""Tests for styling.gradient — the theme-proof heatmap coloring. Verifies per-cell contrast
(dark text on pale cells, light text on deep cells) and graceful handling of NaN/empty."""

import numpy as np
import pandas as pd

import styling as ST


def test_luminance_picks_readable_text():
    # Pale mint background -> should get DARK text; deep forest -> LIGHT text.
    pale = ST._RAMPS["Greens"][0]
    deep = ST._RAMPS["Greens"][1]
    assert ST._text_for(pale) == "#111111"     # dark text on light cell
    assert ST._text_for(deep) == "#ffffff"     # light text on dark cell
    print("✓ per-cell text: dark on pale, white on deep (readable both ways)")


def test_col_styles_span_low_to_high():
    s = pd.Series([0.0, 0.5, 1.0])
    styles = ST._col_styles(s, "Greens")
    assert len(styles) == 3
    # lowest value -> pale bg -> dark text; highest -> deep bg -> white text
    assert "color: #111111" in styles[0]
    assert "color: #ffffff" in styles[2]
    assert all("background-color: rgb(" in st for st in styles)
    print("✓ column scales low->high with correct contrast at each end")


def test_nan_gets_neutral_readable_text():
    s = pd.Series([0.2, np.nan, 0.9])
    styles = ST._col_styles(s, "Reds")
    assert f"color: {ST._NEUTRAL_TEXT}" in styles[1]      # NaN cell -> neutral, still readable
    assert "background-color" not in styles[1]            # no fill on the blank cell
    print("✓ NaN cells get neutral readable text, no fill")


def test_all_nan_column_does_not_crash():
    s = pd.Series([np.nan, np.nan])
    styles = ST._col_styles(s, "Greens")
    assert all(f"color: {ST._NEUTRAL_TEXT}" in st for st in styles)
    print("✓ all-NaN column returns neutral text, no crash")


def test_gradient_skips_missing_columns_and_chains():
    df = pd.DataFrame({"A": [1, 2, 3], "B": [0.1, 0.5, 0.9]})
    styler = df.style
    # 'Missing' isn't a column -> skipped silently; 'B' styled; returns a styler (chainable)
    out = ST.gradient(styler, "Greens", ["B", "Missing"])
    assert out is not None
    rendered = out.to_html()
    assert "background-color" in rendered
    print("✓ gradient skips missing columns, styles present ones, chains")


def test_empty_frame_safe():
    df = pd.DataFrame({"A": []})
    out = ST.gradient(df.style, "Reds", ["A"])
    assert out is not None
    print("✓ empty frame is safe")


def test_absolute_threshold_same_value_same_color():
    # THE KEY GUARANTEE: the same SLG value colors identically regardless of the OTHER values in
    # the table. In relative mode these would differ; with benchmarks they must match.
    t1 = ST._col_styles(pd.Series([0.410, 0.300, 0.320]), "RdYlGn_r", "SLG")   # .410 sits with low vals
    t2 = ST._col_styles(pd.Series([0.410, 0.550, 0.600]), "RdYlGn_r", "H SLG (fam)")  # .410 with high vals
    # first cell of each is SLG .410 -> must be the SAME rgb (both anchor to the SLG benchmark)
    import re
    c1 = re.search(r"rgb\([^)]+\)", t1[0]).group(0)
    c2 = re.search(r"rgb\([^)]+\)", t2[0]).group(0)
    assert c1 == c2, f"same SLG .410 got different colors: {c1} vs {c2}"
    print("✓ absolute: SLG .410 is the SAME color across tables (consistent meaning)")


def test_anchor_endpoints_map_to_ramp_ends():
    lo, mid, hi = ST.THRESHOLDS["SLG"]
    assert ST._norm_position(lo - 0.1, ST.THRESHOLDS["SLG"]) == 0.0   # below low -> red end
    assert ST._norm_position(mid, ST.THRESHOLDS["SLG"]) == 0.5        # mid -> yellow
    assert ST._norm_position(hi + 0.1, ST.THRESHOLDS["SLG"]) == 1.0   # above high -> green end
    print("✓ anchors: low->0.0, mid->0.5, high->1.0 (clamped)")


def test_direction_is_per_ramp_anchors_shared():
    # Same stat, same anchors, but OPPOSITE direction via the ramp: a hitter Whiff% of .33 should
    # be GREEN for the pitcher (RdYlGn) and RED for the bettor (RdYlGn_r) — anchors identical.
    good_for_pitcher = ST._col_styles(pd.Series([0.33]), "RdYlGn", "H Whiff% (fam)")[0]
    bad_for_bettor = ST._col_styles(pd.Series([0.33]), "RdYlGn_r", "H Whiff% (fam)")[0]
    assert "background-color" in good_for_pitcher and "background-color" in bad_for_bettor
    assert good_for_pitcher != bad_for_bettor      # opposite ends of the same scale
    print("✓ direction is per-ramp while thresholds stay shared (context-appropriate)")


def test_unmapped_column_falls_back_to_relative():
    # A column with no benchmark still colors (relative), never crashes.
    styles = ST._col_styles(pd.Series([1.0, 5.0, 9.0]), "Greens", "SomeUnknownColumn")
    assert all("background-color" in s for s in styles)
    print("✓ unmapped columns fall back to relative scaling, no crash")


def test_slg_xwoba_same_direction_on_every_page():
    # Regression guard for the Matchup Lab / Dinger Engine color-consistency fix: SLG and xwOBA
    # must be green-when-high (RdYlGn) on every page that colors them, platform-wide, never
    # RdYlGn_r. Scans the actual view source rather than re-deriving colors, since the bug this
    # guards against is a page choosing the wrong ramp name, not a math error in _col_styles.
    import re
    from pathlib import Path
    views = Path(__file__).parent / "views"
    offenders = []
    for f in views.glob("*.py"):
        src = f.read_text()
        for call in re.findall(r'theme_gradient\(cmap="RdYlGn_r",\s*subset=\[([^\]]*)\]', src):
            if "SLG" in call or "xwOBA" in call:
                offenders.append(f.name)
    assert not offenders, f"SLG/xwOBA colored RdYlGn_r (reversed) in: {offenders}"
    print("✓ SLG/xwOBA are green-when-high on every page (no reversed direction anywhere)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
