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


# --------------------------------------------------------------------------- one table convention (Nov 24)
# Owner, Nov 24: "all data tables should include the ... column heading alignments, arrangements etc we discussed with
# the game labs ... all important data should be to the left and all tables should be game time ascending and each
# consistent with each other." Every st.dataframe passes through here, so the convention holds on every page:
#   * a slate table (a start-time column plus a game / player / pick column) is sorted by start time, earliest first
#     (times before 6 AM are after-midnight starts and sort last);
#   * the start time and the game lead, in that order;
#   * the comparison headers say Model / Market, never "Book" (the sportsbook's NAME column keeps "Book").
# Row-selection tables and data editors are left in their own order (their callers map rows by position).
import re as _re

TIME_COLS = ("Time", "Tip (ET)", "Kickoff (ET)", "Time (ET)", "Start (ET)", "Start", "Kickoff", "When", "Tip")
GAME_COLS = ("Game", "Matchup", "Fight")
ROW_COLS = ("Game", "Matchup", "Fight", "Player", "Pick", "Bet")
RENAME = {"Book says": "Market says", "Book price": "Market price", "Book no-vig": "Market no-vig",
          "Book line": "Market line", "Book implied*": "Market implied*", "Book has": "Market has",
          "Book spread": "Market spread", "Book total": "Market total", "Book ML": "Market moneyline"}
_T = _re.compile(r"(?:(\d{1,2})/(\d{1,2})\s+)?(\d{1,2}):(\d{2})\s*([AaPp][Mm])")
_WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def time_key(v):
    """Sort key for a start time as the site writes it ('7:00 PM', 'Sat 12:00 PM', '11/23 7:00 PM'); None if not a
    time (TBD, Final, blank)."""
    s = str(v or "").strip()
    m = _T.search(s)
    if not m:
        return None
    mo, dy, h, mi, ap = m.groups()
    h = int(h) % 12 + (12 if ap.upper() == "PM" else 0)
    mins = h * 60 + int(mi)
    day = 0
    if mo and dy:
        day = int(mo) * 40 + int(dy)
    else:
        wd = next((i for i, w in enumerate(_WD) if s.startswith(w)), None)
        if wd is not None:
            day = 1000 + wd
    if mins < 6 * 60 and not (mo or day >= 1000):
        mins += 24 * 60                                         # 12:30 AM tonight comes after 11:59 PM
    return (day, mins)


def conform(frame, column_config=None):
    """(frame, column_config) in the site's convention: Model/Market headers, time then game first, earliest start
    first. Anything unexpected returns the inputs untouched."""
    import pandas as pd
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame, column_config
    cfg = dict(column_config or {})
    ren = {c: RENAME[c] for c in frame.columns if isinstance(c, str) and c in RENAME and RENAME[c] not in frame.columns}
    if ren:
        frame = frame.rename(columns=ren)
        cfg = {ren.get(k, k): v for k, v in cfg.items()}
    t = next((c for c in TIME_COLS if c in frame.columns), None)
    g = next((c for c in GAME_COLS if c in frame.columns), None)
    rowc = next((c for c in ROW_COLS if c in frame.columns), None)
    if t and rowc:
        keys = [time_key(v) for v in frame[t]]
        if sum(k is not None for k in keys) >= max(2, 0.8 * len(keys)):
            order = sorted(range(len(keys)), key=lambda i: (keys[i] is None, keys[i] or (0, 0), i))
            if order != list(range(len(keys))):
                frame = frame.iloc[order]
                if isinstance(frame.index, pd.RangeIndex) or list(frame.index) == sorted(frame.index):
                    frame = frame.reset_index(drop=True)
        lead = [t] + ([g] if g and g != t else [])
        cols = list(frame.columns)
        if cols[:len(lead)] != lead:
            frame = frame[lead + [c for c in cols if c not in lead]]
    return frame, cfg


def install() -> None:
    import streamlit as st
    from streamlit.delta_generator import DeltaGenerator as DG
    if getattr(DG.dataframe, "_h2_centered", False):
        return
    for name in ("dataframe", "data_editor"):
        orig = getattr(DG, name)

        def wrap(self, data=None, *args, _orig=orig, _name=name, **kw):
            try:
                if _name == "dataframe" and not kw.get("on_select") and kw.get("selection_mode") is None:
                    data, cc = conform(data, kw.get("column_config"))
                    if cc is not None:
                        kw["column_config"] = cc
                kw["column_config"] = centered(data, kw.get("column_config"))
            except Exception:                                   # noqa: BLE001 -- styling never breaks a table
                pass
            return _orig(self, data, *args, **kw)
        wrap._h2_centered = True
        wrap.__doc__ = orig.__doc__
        setattr(DG, name, wrap)
    st.dataframe = st._main.dataframe                           # the module-level calls were bound before the patch
    st.data_editor = st._main.data_editor


# --------------------------------------------------------------------------- phones (Nov 23)
# Owner, Nov 23: "The site is not scalable for a device other than a laptop ... especially on a phone." On a phone
# a 15-20 column table shows two columns and the rest scrolls sideways inside the grid. On a phone, every wide table
# (PHONE_MIN_COLS+ columns, not a row-selection table) is drawn as stacked cards -- one per row, the left-most
# (most important) columns first -- with the full table one tap away. Desktop is untouched; anything unexpected falls
# back to the normal table.
import html as _html
import math as _math

PHONE_MIN_COLS = 5
CARD_FIELDS = 10
CARD_ROWS = 40
LAYOUT_KEY = "h2_layout"                 # "Auto" / "Phone" / "Full"
_TIME = ("Time", "Tip (ET)", "Kickoff (ET)", "Kickoff", "Start", "When")
_TITLE = ("Game", "Pick", "Player", "Matchup", "Bet", "Team", "Market", "Name")
CARD_CSS = """<style>
.h2c{background:#1a1f2b;border:1px solid #2d3344;border-radius:10px;padding:8px 11px;margin:0 0 7px}
.h2c-t{font-weight:600;font-size:.92rem;line-height:1.25;margin-bottom:5px;color:#e6e6e6}
.h2c-t span{color:#9aa4b2;font-weight:500;margin-right:6px}
.h2c-g{display:grid;grid-template-columns:minmax(84px,40%) 1fr;gap:2px 10px;font-size:.82rem;line-height:1.3}
.h2c-k{color:#9aa4b2}.h2c-v{color:#e6e6e6;overflow-wrap:anywhere}
</style>"""


def is_phone(ua: str) -> bool:
    ua = ua or ""
    return "iPhone" in ua or "iPod" in ua or ("Android" in ua and "Mobile" in ua) or "Windows Phone" in ua


def phone_mode() -> bool:
    """The layout choice ('Phone' / 'Full'), else the device: a phone's browser says so in its user agent."""
    import streamlit as st
    try:
        choice = st.session_state.get(LAYOUT_KEY, "Auto")
        if choice == "Phone":
            return True
        if choice == "Full":
            return False
        return is_phone(st.context.headers.get("User-Agent", ""))
    except Exception:                                           # noqa: BLE001
        return False


def _fmt(v, cfg) -> str:
    if v is None or (isinstance(v, float) and _math.isnan(v)):
        return ""
    if isinstance(v, bool):
        return ""
    fmt = ((cfg or {}).get("type_config") or {}).get("format") if isinstance(cfg, dict) else None
    if isinstance(v, (int, float)):
        if fmt == "percent":
            return f"{v:.0%}"
        if isinstance(v, float):
            return f"{v:.2f}".rstrip("0").rstrip(".")
    s = str(v).strip()
    return "" if s in ("—", "-", "nan", "None") else s


def cards_html(frame, column_config: Optional[Dict] = None, limit: int = CARD_ROWS) -> str:
    cfg = column_config or {}
    cols = [c for c in frame.columns if isinstance(c, str) and cfg.get(c, ...) is not None]
    t_col = next((c for c in _TIME if c in cols), None)
    m_col = next((c for c in _TITLE if c in cols), None) or next((c for c in cols if c != t_col), None)
    rest = [c for c in cols if c not in (t_col, m_col)]
    out = []
    for _, row in frame.head(limit).iterrows():
        title = _html.escape(_fmt(row.get(m_col), cfg.get(m_col)) if m_col else "")
        when = _html.escape(_fmt(row.get(t_col), cfg.get(t_col))) if t_col else ""
        fields = []
        for c in rest:
            v = _fmt(row.get(c), cfg.get(c))
            if v:
                label = cfg.get(c, {}).get("label") if isinstance(cfg.get(c), dict) else None
                fields.append(f'<div class="h2c-k">{_html.escape(str(label or c))}</div>'
                              f'<div class="h2c-v">{_html.escape(v)}</div>')
            if len(fields) >= CARD_FIELDS:
                break
        out.append(f'<div class="h2c"><div class="h2c-t">{f"<span>{when}</span>" if when else ""}{title}</div>'
                   f'<div class="h2c-g">{"".join(fields)}</div></div>')
    return CARD_CSS + "".join(out)


def _as_frame(data):
    import pandas as pd
    if type(data).__name__ == "Styler":
        return data.data
    if isinstance(data, pd.DataFrame):
        return data
    return None


def install_phone() -> None:
    """On a phone, wide st.dataframe tables become cards (the data editors keep their table: they're for ticking)."""
    from streamlit.delta_generator import DeltaGenerator as DG
    import streamlit as st
    if getattr(DG.dataframe, "_h2_phone", False):
        return
    orig = DG.dataframe

    def wrap(self, data=None, *args, **kw):
        try:
            frame = _as_frame(data)
            if (frame is not None and len(frame.columns) >= PHONE_MIN_COLS and not kw.get("on_select")
                    and kw.get("selection_mode") is None and len(frame) and phone_mode()):
                frame, cc = conform(frame, kw.get("column_config"))       # Nov 24: same order as the table
                cfg = centered(frame, cc) or {}
                self.markdown(cards_html(frame, cfg), unsafe_allow_html=True)
                more = len(frame) - CARD_ROWS
                exp = self.expander(f"Full table ({len(frame)} rows, scroll sideways)" if more <= 0 else
                                    f"+{more} more — open the full table ({len(frame)} rows)")
                orig(exp, data, *args, **kw)
                return None
        except Exception:                                       # noqa: BLE001 -- a phone never gets a broken page
            pass
        return orig(self, data, *args, **kw)
    wrap._h2_phone = True
    wrap._h2_centered = getattr(orig, "_h2_centered", False)
    setattr(DG, "dataframe", wrap)
    st.dataframe = st._main.dataframe
