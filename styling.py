"""
styling.py — theme-proof heatmap coloring shared by every page and every sport.

THE PROBLEM this solves: pandas Styler.background_gradient colors the CELL from pale to deep, but
leaves the TEXT the theme's default. In dark mode Streamlit flips text to near-white, so a pale
cell becomes white-on-near-white — invisible. The gradient was implicitly designed for a light
background and breaks when the theme flips.

THE FIX (per-cell contrast): for every colored cell we compute the background's luminance and set
the text black or white accordingly. That makes the numbers readable on ANY background, in light
OR dark mode, regardless of the user's device theme. We also force an explicit text color even on
the un-colored (NaN) cells so nothing ever inherits an unreadable default.

USE (drop-in replacement for `.background_gradient(cmap=..., subset=...)`):

    from styling import gradient
    styler = df.style.format({...}, na_rep="—")
    styler = gradient(styler, "Greens", ["Whiff%", "Score"])   # good = green
    styler = gradient(styler, "Reds",   ["SLG", "xwOBA"])      # damage = red
    st.dataframe(styler, use_container_width=True, hide_index=True)

`gradient()` returns the styler so calls chain. It never raises on empty frames or all-NaN
columns; it simply leaves those cells with readable neutral text.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np
import pandas as pd

# Color ramps as ordered RGB stops (2 stops = sequential, 3 = diverging). Kept in a MID-TONE band
# on purpose: never so pale a cell vanishes on white, never so deep it swallows text before the
# per-cell contrast even helps. Matplotlib is intentionally NOT required (it was a segfault source
# once); we interpolate RGB here.
_RAMPS = {
    "Greens":  [(235, 246, 238), (22, 120, 60)],     # soft mint  -> forest
    "Reds":    [(250, 236, 236), (168, 36, 36)],      # soft blush -> deep red
    "Blues":   [(233, 241, 250), (30, 96, 168)],      # soft sky   -> deep blue
    "Oranges": [(252, 240, 228), (188, 96, 20)],      # soft peach -> burnt orange
    "Purples": [(242, 236, 250), (104, 52, 160)],     # soft lilac -> deep purple
    # diverging red -> yellow -> green (low is bad, high is good)
    "RdYlGn":   [(200, 66, 66), (240, 214, 96), (46, 150, 78)],
    # reversed: green -> yellow -> red (low is good, high is bad)
    "RdYlGn_r": [(46, 150, 78), (240, 214, 96), (200, 66, 66)],
}
# Neutral text for cells that get no gradient (NaN / out of range). Mid-grey reads on light AND
# dark backgrounds (both themes keep table backgrounds close enough to mid that this is safe).
_NEUTRAL_TEXT = "#6b7280"


# ============================================================================================
# BENCHMARK-ANCHORED COLORING — consistent color MEANING across every page and every sport.
#
# Each stat has fixed (low, mid, high) anchors grounded in the league's real distribution:
# low ~ poor (red end), mid ~ league-average (yellow), high ~ elite (green end). Every table
# everywhere colors a stat against ITS anchors, so a given value is the SAME color no matter
# which page it's on — that's the professional, trustworthy behavior.
#
# DIRECTION is per-column, not per-stat: some pages want "high = green" (RdYlGn) and others want
# "high = red" (RdYlGn_r) for the SAME stat (a hitter's whiff% is good for the pitcher but bad for
# the bettor). Callers pick the ramp; the ANCHORS stay identical either way.
#
# Adding a sport = add its stats here. One source of truth for the whole platform.
#
# Thresholds are the starting calibration (MLB distributions). Tune any anchor here and it
# propagates to every table automatically.
# ============================================================================================
THRESHOLDS: Dict[str, tuple] = {
    # ---- MLB hitter quality (green = good for the hitter) ----
    "SLG":      (0.350, 0.410, 0.500),
    "xwOBA":    (0.290, 0.320, 0.370),
    "Barrel%":  (0.04,  0.08,  0.14),
    "HR%":      (0.02,  0.035, 0.06),
    "Hard-hit%":(0.30,  0.38,  0.48),
    "xHR/PA":   (0.02,  0.035, 0.06),
    # ---- whiff / strikeout (same anchors; DIRECTION set per page via the ramp) ----
    "Whiff%":   (0.18,  0.25,  0.33),
    "K%":       (0.15,  0.22,  0.30),
    # ---- MLB pitcher arsenal (green = good for the pitcher) ----
    "Pitch Whiff%": (0.08, 0.15, 0.28),
    "PutAway%":     (0.12, 0.18, 0.26),
}

# Map a table's column label -> the THRESHOLDS stat it should use. Different pages label the same
# underlying stat differently (e.g. "H SLG (fam)" and "SLG" are both SLG); this keeps them anchored
# to ONE benchmark. Unmapped columns fall back to relative (per-table) scaling.
COLUMN_TO_STAT: Dict[str, str] = {
    # slugging / xwOBA variants
    "SLG": "SLG", "H SLG (fam)": "SLG",
    "xwOBA": "xwOBA", "H xwOBA (fam)": "xwOBA",
    # whiff variants (pitch-level whiff shares the Pitch Whiff% benchmark)
    "Whiff%": "Pitch Whiff%", "P Whiff%": "Pitch Whiff%",
    "H Whiff% (fam)": "Whiff%",
    "PutAway%": "PutAway%", "P PutAway%": "PutAway%",
    # hitter power
    "HR%": "HR%", "Barrel%": "Barrel%", "xHR/PA": "xHR/PA", "Hard-hit%": "Hard-hit%",
    "K%": "K%", "SO Prob": "K%",
}


def register_thresholds(new: Dict[str, tuple], column_map: Optional[Dict[str, str]] = None):
    """Let a sport add its own stat anchors (and column aliases) to the shared system."""
    THRESHOLDS.update(new)
    if column_map:
        COLUMN_TO_STAT.update(column_map)


def _lerp(a: Sequence[float], b: Sequence[float], t: float):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _ramp_color(stops: Sequence[Sequence[float]], t: float):
    """Interpolate an N-stop ramp at position t in [0,1] (handles 2-stop and 3-stop diverging)."""
    t = max(0.0, min(1.0, t))
    if len(stops) == 1:
        return stops[0]
    seg = t * (len(stops) - 1)
    i = min(int(seg), len(stops) - 2)
    return _lerp(stops[i], stops[i + 1], seg - i)


def _luminance(rgb: Sequence[float]) -> float:
    """Perceived luminance (0-255 scale) via the standard Rec. 601 weights."""
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def _text_for(rgb: Sequence[float]) -> str:
    """Black on light backgrounds, white on dark ones — the per-cell contrast that makes the
    number readable no matter the app theme."""
    return "#111111" if _luminance(rgb) > 150 else "#ffffff"


def _norm_position(v: float, anchors: tuple) -> float:
    """Map a value to 0..1 against fixed (low, mid, high) anchors, so the SAME value is the SAME
    color everywhere. Piecewise: low->0.0, mid->0.5, high->1.0, clamped outside the range."""
    lo, mid, hi = anchors
    if v <= lo:
        return 0.0
    if v >= hi:
        return 1.0
    if v <= mid:
        return 0.5 * (v - lo) / ((mid - lo) or 1.0)
    return 0.5 + 0.5 * (v - mid) / ((hi - mid) or 1.0)


def _col_styles(series: pd.Series, ramp_name: str, col_name: Optional[str] = None) -> List[str]:
    """Per-cell 'background-color + color' for one column.

    If `col_name` maps to a benchmark in THRESHOLDS, the color position is computed against those
    FIXED anchors (consistent meaning across pages). Otherwise it falls back to relative min/max
    scaling within the column. Text color is always chosen per cell for light/dark readability."""
    stops = _RAMPS.get(ramp_name, _RAMPS["Greens"])
    vals = pd.to_numeric(series, errors="coerce")
    finite = vals[np.isfinite(vals)]
    out: List[str] = []
    if len(finite) == 0:
        return [f"color: {_NEUTRAL_TEXT}"] * len(series)

    stat = COLUMN_TO_STAT.get(col_name or "")
    anchors = THRESHOLDS.get(stat) if stat else None
    if anchors is None:                       # relative fallback (no benchmark for this column)
        vmin, vmax = float(finite.min()), float(finite.max())
        span = (vmax - vmin) or 1.0

    for v in vals:
        if not np.isfinite(v):
            out.append(f"color: {_NEUTRAL_TEXT}")
            continue
        if anchors is not None:               # absolute: same value -> same color everywhere
            t = _norm_position(float(v), anchors)
        else:                                 # relative: scaled within this table
            t = (float(v) - vmin) / span
        rgb = _ramp_color(stops, t)
        bg = f"rgb({int(rgb[0])},{int(rgb[1])},{int(rgb[2])})"
        out.append(f"background-color: {bg}; color: {_text_for(rgb)}")
    return out


def gradient(styler: "pd.io.formats.style.Styler", ramp: str,
             subset: Optional[List[str]]) -> "pd.io.formats.style.Styler":
    """Theme-proof replacement for Styler.background_gradient.

    Colors each column in `subset` low->high using the named `ramp`, and sets the text color per
    cell from the background luminance so it's readable in light OR dark mode. Returns the styler
    so calls chain. Missing columns are skipped silently; empty/all-NaN columns get neutral text."""
    if subset is None:
        return styler
    cols = [c for c in subset if c in styler.data.columns]
    for c in cols:
        styler = styler.apply(lambda s, _c=c: _col_styles(s, ramp, _c), subset=[c])
    return styler


# ---- drop-in Styler method -------------------------------------------------------------------
# So existing pages convert with a one-token rename (`.background_gradient(` -> `.theme_gradient(`)
# instead of restructuring every chained call. Same keyword signature as background_gradient; extra
# kwargs (vmin/vmax/etc.) are accepted and ignored. Importing this module installs the method.
def _theme_gradient(self, cmap: str = "Greens", subset: Optional[List[str]] = None, **_kwargs):
    return gradient(self, cmap, subset)


def _install():
    try:
        from pandas.io.formats.style import Styler
        Styler.theme_gradient = _theme_gradient
    except Exception:  # noqa: BLE001 — if pandas internals move, pages can still import gradient()
        pass


_install()
