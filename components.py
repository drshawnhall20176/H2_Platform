"""
components.py — shared, reusable "commercial feel" layout components.

WHY THIS EXISTS: the platform's actual functionality has been real and deep for a long time, but
the visual presentation was running on default Streamlit widgets (st.metric, st.subheader) that
look like an internal tool, not a product. Added directly on request, using Command Center as the
first real proof of concept -- built as a SHARED module from the start, not page-specific inline
CSS, so the same visual language can extend to other pages later without rebuilding it each time.

A REAL, DELIBERATE CONSTRAINT worth stating plainly: raw HTML rendered via st.markdown cannot
wrap around other Streamlit widgets (st.dataframe, st.tabs, etc.) -- each call renders as its own
separate DOM node, not nested inside the previous one. That shapes everything here:
  - Fully self-contained elements (KPI tiles, section headers) ARE built as custom HTML, since
    they don't need to contain other Streamlit widgets.
  - Anything that needs to hold a table, tabs, or other widgets uses st.container(border=True) --
    Streamlit's own native mechanism, already stable, already gets rounded corners from this
    platform's own config.toml (baseRadius="medium") -- not a hand-rolled HTML wrapper that
    can't actually contain those widgets.

CSS RISK, STATED HONESTLY: base_css() below styles a couple of Streamlit's own internal
data-testid hooks (e.g. dataframe corners) for extra polish. These are reasonably stable,
well-known hooks, but they are still Streamlit internals, not a documented public API -- a future
Streamlit version could change them. If that happens, the CSS rule simply stops matching anything
(inert, not broken) -- the page keeps working, it just loses that specific polish until updated.
Nothing here targets fragile internals like the sidebar nav DOM.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import streamlit as st


def base_css() -> None:
    """One-time, page-level CSS polish. Call once near the top of a page, after st.title/caption.
    Safe, self-contained rules only -- see this module's own docstring for the honest risk
    accounting on the couple of internal hooks used here."""
    st.markdown("""
    <style>
    /* Rounded, subtly-elevated dataframes -- a small but real step away from the flat default
       table look. Falls through harmlessly if this hook ever changes in a future Streamlit
       version; nothing else on the page depends on it. */
    [data-testid="stDataFrame"] {
        border-radius: 10px;
        overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    }
    /* Tab strip: a bit more breathing room and a clearer active-tab indicator than the stock
       thin underline, closer to the denser, more deliberate tab styling both reference products
       use. */
    [data-testid="stTabs"] button[role="tab"] {
        padding: 8px 16px;
        font-weight: 600;
    }
    </style>
    """, unsafe_allow_html=True)


# Doink-style vibrant, distinct accent colors for KPI tiles -- deliberately NOT red/green for the
# neutral count-style tiles (games, plays, top lean), since red/green are reserved platform-wide
# for real data meaning (grades, RdYlGn gradients). Performance tiles (beat-close rate, CLV) use
# a SEPARATE, dynamic good/bad/neutral scheme instead -- see kpi_row's own "trend" parameter.
_KPI_PALETTE = ["#3b82f6", "#8b5cf6", "#f59e0b", "#06b6d4", "#ec4899"]
_TREND_COLOR = {"good": "#16a34a", "bad": "#dc2626", "neutral": "#6b7280"}


def kpi_row(items: List[dict]) -> None:
    """Doink-style row of vibrant, icon-led stat tiles -- replaces a plain st.columns()+st.metric()
    row. Each item: {"icon": str, "value": str, "label": str, "help": Optional[str],
    "trend": Optional["good"|"bad"|"neutral"]}.

    trend, when given, OVERRIDES the tile's accent color with a real good/bad/neutral color
    instead of the decorative palette -- for metrics where the color itself is real information
    (a positive CLV should look different from a negative one), not just visual variety. Omit
    trend for neutral counts (games, plays) where any color is purely decorative.

    Self-contained HTML by design (see this module's own docstring) -- no nested Streamlit
    widgets inside a tile, so this is safe to render as one block via st.markdown."""
    if not items:
        return
    cols_html = []
    for i, item in enumerate(items):
        color = _TREND_COLOR.get(item.get("trend"), _KPI_PALETTE[i % len(_KPI_PALETTE)])
        help_attr = f' title="{item["help"]}"' if item.get("help") else ""
        cols_html.append(f"""
        <div style="flex:1;min-width:140px;background:linear-gradient(135deg,{color}22,{color}0d);
                    border:1px solid {color}44;border-radius:12px;padding:14px 16px;"{help_attr}>
          <div style="font-size:22px;line-height:1;">{item.get('icon', '')}</div>
          <div style="font-size:26px;font-weight:800;margin-top:6px;color:{color};">
            {item.get('value', '—')}
          </div>
          <div style="font-size:12.5px;color:#9aa4b2;margin-top:2px;">{item.get('label', '')}</div>
        </div>""")
    st.markdown(
        f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:4px;">'
        f'{"".join(cols_html)}</div>',
        unsafe_allow_html=True)


def section_header(icon: str, title: str, subtitle: Optional[str] = None,
                   color: str = "#1f6feb") -> None:
    """PropFinder-style dense section header: icon in a colored circular badge + bold title,
    replacing a plain st.subheader(). Purely decorative HTML, self-contained -- call this, then
    use normal st.* calls (st.dataframe, st.tabs, etc.) immediately after; this does NOT open a
    container those calls render inside (see this module's own docstring for why)."""
    sub_html = (f'<div style="font-size:13px;color:#9aa4b2;margin-top:2px;">{subtitle}</div>'
               if subtitle else "")
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin:6px 0 10px 0;">
      <div style="background:{color};color:white;width:38px;height:38px;border-radius:10px;
                  display:flex;align-items:center;justify-content:center;font-size:19px;
                  flex-shrink:0;">{icon}</div>
      <div>
        <div style="font-size:19px;font-weight:750;line-height:1.15;">{title}</div>
        {sub_html}
      </div>
    </div>
    """, unsafe_allow_html=True)
