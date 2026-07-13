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


def _col_styles(series: pd.Series, ramp_name: str) -> List[str]:
    """Per-cell 'background-color + color' for one column, normalized within that column."""
    stops = _RAMPS.get(ramp_name, _RAMPS["Greens"])
    vals = pd.to_numeric(series, errors="coerce")
    finite = vals[np.isfinite(vals)]
    out: List[str] = []
    if len(finite) == 0:
        # nothing to scale — just make text readable
        return [f"color: {_NEUTRAL_TEXT}"] * len(series)
    vmin, vmax = float(finite.min()), float(finite.max())
    span = (vmax - vmin) or 1.0
    for v in vals:
        if not np.isfinite(v):
            out.append(f"color: {_NEUTRAL_TEXT}")
            continue
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
        styler = styler.apply(lambda s, _c=c: _col_styles(s, ramp), subset=[c])
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
