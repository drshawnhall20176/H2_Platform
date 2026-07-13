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
