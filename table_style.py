"""
table_style.py -- one look for every table on the site (Nov 23).

Owner, Nov 23: "Can you center all column headers?" Streamlit's tables (st.dataframe / st.data_editor, and the same
calls on columns, tabs and expanders) align a header with its column's content, and there is no header-only setting,
so every column is centered -- header and cells -- unless a page sets its own alignment. Installed once from the
entry point (streamlit_app.py), like cache_guard, so no page has to remember it.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

CENTER = "center"


def centered(data: Any, column_config: Optional[Dict] = None) -> Optional[Dict]:
    """column_config with every column of `data` (a DataFrame or Styler) centered; a page's own settings are kept, its
    own alignment wins, and a hidden column (None) stays hidden."""
    frame = getattr(data, "data", data) if type(data).__name__ == "Styler" else data
    cols = list(getattr(frame, "columns", None) if getattr(frame, "columns", None) is not None else [])
    if not cols:
        return column_config
    cfg = dict(column_config or {})
    for c in cols:
        if not isinstance(c, str):
            continue
        cur = cfg.get(c, ...)
        if cur is ...:
            cfg[c] = {"alignment": CENTER}
        elif cur is None:
            continue
        elif isinstance(cur, str):
            cfg[c] = {"label": cur, "alignment": CENTER}
        elif isinstance(cur, dict) and not cur.get("alignment"):
            cfg[c] = dict(cur, alignment=CENTER)
    return cfg


def install() -> None:
    import streamlit as st
    from streamlit.delta_generator import DeltaGenerator as DG
    if getattr(DG.dataframe, "_h2_centered", False):
        return
    for name in ("dataframe", "data_editor"):
        orig = getattr(DG, name)

        def wrap(self, data=None, *args, _orig=orig, **kw):
            try:
                kw["column_config"] = centered(data, kw.get("column_config"))
            except Exception:                                   # noqa: BLE001 -- styling never breaks a table
                pass
            return _orig(self, data, *args, **kw)
        wrap._h2_centered = True
        wrap.__doc__ = orig.__doc__
        setattr(DG, name, wrap)
    st.dataframe = st._main.dataframe                           # the module-level calls were bound before the patch
    st.data_editor = st._main.data_editor
