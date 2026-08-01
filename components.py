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

import base64
from pathlib import Path
from typing import List, Optional, Sequence

import streamlit as st

_ASSETS_DIR = Path(__file__).parent / "assets"


@st.cache_resource(show_spinner=False)
def _b64_asset(filename: str) -> Optional[str]:
    """Base64-encoded bytes of a static file under assets/, cached for the life of the process
    (a real logo file never changes mid-session, so re-reading/re-encoding it on every hero_
    banner call across every rerun would be pure waste). Returns None if the file isn't there --
    hero_banner below must degrade to its original icon+title+subtitle look, not crash, if an
    asset is ever missing (e.g. a stripped-down deploy, or the file simply not committed)."""
    path = _ASSETS_DIR / filename
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


def hero_banner(icon: str, title: str, subtitle: str) -> None:
    """Dark gradient hero banner -- extracted from Command Center's own original inline CSS
    (already proven working there) into this shared module, so every page that wants this same
    "front door" treatment reuses the exact same visual language instead of each page
    duplicating and potentially drifting from its own copy of the CSS.

    Real H2 Sports logo (assets/h2_logo.png) rendered to the left of the title/subtitle stack --
    added directly on request. FAILS SAFE: if the asset is ever missing, this silently falls back
    to the original icon+title+subtitle layout with no logo slot at all, never a broken-image
    icon or a crash -- same fail-soft posture this module already uses everywhere else (base_css's
    own CSS-hook risk, the sidebar CSS removed after it was confirmed inert, etc.)."""
    logo_b64 = _b64_asset("h2_logo.png")
    logo_html = (f'<img src="data:image/png;base64,{logo_b64}" '
                f'style="height:56px;width:auto;flex-shrink:0;">' if logo_b64 else "")
    st.markdown(f"""
    <style>
    .h2-hero {{background:linear-gradient(110deg,#0f172a,#1e293b);padding:22px 26px;
              border-radius:14px;color:#f8fafc;margin-bottom:6px;display:flex;
              align-items:center;gap:18px;}}
    .h2-hero h1 {{margin:0;font-size:30px;letter-spacing:-0.5px;}}
    .h2-hero p {{margin:4px 0 0;color:#94a3b8;font-size:15px;}}
    </style>
    <div class="h2-hero">
      {logo_html}
      <div>
        <h1>{icon} {title}</h1>
        <p>{subtitle}</p>
      </div>
    </div>
    """, unsafe_allow_html=True)


def pipeline_chips(steps: List[str]) -> None:
    """Horizontal chain of pill-shaped step chips connected by arrows -- extracted from Command
    Center's own original "How every play is built" pipeline visualization into this shared
    module, same reasoning as hero_banner above. steps is rendered in order, left to right."""
    st.markdown("""
    <style>
    .pipe {display:inline-block;background:#1e293b;color:#e2e8f0;border:1px solid #334155;
           padding:6px 12px;border-radius:999px;margin:3px 4px;font-size:13px;}
    .pipe-arrow {color:#64748b;margin:0 2px;}
    </style>
    """, unsafe_allow_html=True)
    chips = f'<span class="pipe-arrow">→</span>'.join(f'<span class="pipe">{s}</span>' for s in steps)
    st.markdown(chips, unsafe_allow_html=True)


def wrapped_tab_picker(items: List[tuple], key: str, default_index: int = 0):
    """A tab-like selector that WRAPS to multiple rows instead of overflowing off-screen with a
    truncating ">" arrow, the way native st.tabs() does with many options. Built on st.pills
    (confirmed directly against Streamlit's own docs before using it: pills wrap to the next
    line by default when they overflow, the same real behavior st.container(horizontal=True)
    has, unlike st.tabs or st.columns which don't wrap at all).

    items: [(display_label, value), ...] -- same shape as the existing _TOP_TABS-style pattern
    already used for market tabs, so converting a call site is a straightforward swap, not a
    rewrite of the surrounding logic.

    required=True (fixed, not exposed as a parameter) matches real st.tabs() behavior: there's
    always exactly one selection, never a "nothing selected" state a caller would have to
    handle as a special case.

    Returns the VALUE (not the label) of the selected item -- caller checks this directly and
    renders only that one branch's content (see this function's own module docstring on why
    that's also more efficient than st.tabs, which computes every tab's content on every rerun
    whether it's visible or not)."""
    labels = [i[0] for i in items]
    values = {i[0]: i[1] for i in items}
    selected_label = st.pills(f"tab_picker_{key}", labels, default=labels[default_index],
                              required=True, key=key, label_visibility="collapsed")
    return values[selected_label]


def page_header(icon: str, title: str, subtitle: str) -> None:
    """Lighter-weight page header for ordinary sub-pages -- replaces a plain st.title()+
    st.caption() pair with a consistent icon-badge treatment. Deliberately NOT the full
    gradient hero_banner() above -- that stays reserved for the two genuine "front door" pages
    (Home, Command Center) on purpose. A big gradient banner identically repeated at the top of
    20+ sub-pages would read as visual fatigue, not polish; this is the lighter, consistent
    alternative for everywhere else."""
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:2px;">
      <div style="font-size:32px;line-height:1;">{icon}</div>
      <div>
        <div style="font-size:27px;font-weight:800;letter-spacing:-0.5px;line-height:1.15;">{title}</div>
        <div style="font-size:14px;color:#9aa4b2;margin-top:2px;">{subtitle}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


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


def _team_logo_html(url: Optional[str]) -> str:
    """Small inline team logo, or nothing at all when no URL is available/known -- never a
    broken-image icon. onerror hides the element itself on a 404/bad URL, a completely standard,
    stable HTML behavior (not a fragile internal hook, see this module's own CSS-risk section) --
    the one real, honest safety net for NFL's constructed-guess logo URLs and any other source
    that might not resolve."""
    if not url:
        return ""
    return (f'<img src="{url}" style="width:20px;height:20px;object-fit:contain;'
           f'vertical-align:middle;margin-right:5px;" onerror="this.style.display=\'none\'">')


# Game-status badge colors -- a genuinely separate semantic dimension from the conference accent
# color or _TREND_COLOR's own good/bad/neutral judgment (a live game isn't "good", a final score
# isn't "bad") -- its own small, fixed map so it never accidentally collides with either.
_STATUS_STYLE = {
    "delayed": ("#f59e0b", "Delayed"),
    "canceled": ("#dc2626", "Canceled"),
    "in-progress": ("#16a34a", "Live"),
    "finished": ("#8b93a1", "Final"),
    # "scheduled" deliberately has no entry -- the time chip already communicates "upcoming",
    # a same-meaning "Scheduled" badge next to it would be pure redundancy, not new information.
}


def _status_badge_html(status: Optional[str]) -> str:
    """A small colored status badge for anything OTHER than 'scheduled' (see _STATUS_STYLE's own
    comment on why) -- empty string for scheduled/unknown, never a placeholder badge for the
    common case."""
    style = _STATUS_STYLE.get(status or "")
    if not style:
        return ""
    color, label = style
    return (f'<span style="font-size:11px;font-weight:700;white-space:nowrap;'
           f'background:{color}22;color:{color};padding:3px 8px;border-radius:6px;'
           f'border:1px solid {color}55;">{label}</span>')


def _lineup_bubble_html(g: dict) -> str:
    """H:/A: red-or-green dots showing whether each side's REAL starting lineup is officially
    posted yet (green) or still just this platform's own projection (red) -- MLB only right now,
    see schedule_board.py's own module notes on why other sports don't have a confirmed signal
    for this yet. Empty string entirely when both sides are None (not applicable for this sport),
    so nothing renders instead of a pair of misleading always-red dots."""
    home_c, away_c = g.get("home_lineup_confirmed"), g.get("away_lineup_confirmed")
    if home_c is None and away_c is None:
        return ""
    green, red = _TREND_COLOR["good"], _TREND_COLOR["bad"]

    def _dot(confirmed: Optional[bool]) -> str:
        color = green if confirmed else red
        return (f'<span style="width:8px;height:8px;border-radius:50%;background:{color};'
               f'display:inline-block;margin-left:3px;"></span>')

    return (f'<span style="display:inline-flex;align-items:center;gap:2px;font-size:10.5px;'
           f'color:#9aa4b2;font-weight:600;">H:{_dot(home_c)}'
           f'<span style="margin-left:6px;">A:</span>{_dot(away_c)}</span>')


def _schedule_game_row(g: dict, color: str) -> str:
    """One game's self-contained HTML row -- team logo + away @ home pulled together on the
    left, a small colored time chip and venue immediately after (not stretched to the far edge
    of the row) so the row's real content stays compact instead of wasting horizontal space --
    directly reported feedback: the original space-between layout spread team names and time/
    venue across the FULL container width, which read as wasted real estate especially once
    conference boxes went side by side (see todays_schedule_board below) and got narrower. color
    is the SAME accent color assigned to this game's conference (see todays_schedule_board) --
    carries the conference's own color through to the row level via the same alpha-blended-
    background technique kpi_row already uses, rather than introduce an unrelated new color
    scheme.

    Also carries a real game-status badge (Live/Delayed/Canceled/Final -- see _STATUS_STYLE) and,
    for MLB specifically, H:/A: lineup-confirmation bubbles -- both added directly on request.

    BUILT AS A SINGLE-LINE STRING, DELIBERATELY -- a real, confirmed rendering bug, not a style
    choice: many of these rows get joined together (see todays_schedule_board's own rows =
    "".join(...)) into ONE st.markdown() call. A pretty-printed, multi-line/indented f-string
    (this function's own original version) gets misread by the markdown renderer once several
    are concatenated -- deeply-indented inner lines (the time chip and venue, in the confirmed
    live report) get treated as an indented Markdown code block and leak as literal escaped text
    instead of rendering as HTML, while shallow single-line content (team names) renders fine.
    Every other HTML-building helper in this module that gets joined this way (_team_logo_html,
    _status_badge_html, _lineup_bubble_html) was already single-line and unaffected -- this
    function was the one real gap."""
    if g.get("time_known") and g.get("dt") is not None:
        time_str = g["dt"].strftime("%-I:%M %p ET")
    else:
        time_str = "Time TBD"
    venue_html = (f'<span style="font-size:11.5px;color:#9aa4b2;">{g["venue"]}</span>'
                 if g.get("venue") else "")
    status_html = _status_badge_html(g.get("status"))
    lineup_html = _lineup_bubble_html(g)
    away_logo = _team_logo_html(g.get('away_logo'))
    home_logo = _team_logo_html(g.get('home_logo'))
    away_name = g.get('away', '?')
    home_name = g.get('home', '?')
    return (
        '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;'
        'padding:8px 10px;border-radius:8px;margin-bottom:3px;background:rgba(255,255,255,0.025);">'
        '<div style="font-size:14px;white-space:nowrap;">'
        f'{away_logo}<span style="font-weight:600;">{away_name}</span>'
        '<span style="color:#6b7280;margin:0 5px;">@</span>'
        f'{home_logo}<span style="font-weight:600;">{home_name}</span>'
        '</div>'
        '<div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">'
        f'{lineup_html}{status_html}'
        f'<span style="font-size:11.5px;font-weight:700;white-space:nowrap;background:{color}1e;'
        f'color:{color};padding:3px 9px;border-radius:6px;">{time_str}</span>'
        f'{venue_html}'
        '</div>'
        '</div>'
    )


def todays_schedule_board(result: Optional[dict], icon: str, label: str) -> None:
    """Renders schedule_board.todays_schedule()'s own return shape -- conference (and division,
    where that data exists) sections, each game sorted chronologically within its group. result
    is None for a sport schedule_board.py doesn't cover (NCAAMB, UFC) or that had a live fetch
    error already absorbed upstream -- the caller should check for None and simply not call this
    at all rather than render an empty section, same "hidden, not shown broken" posture used
    elsewhere on this platform. Renders a plain, honest "no games today" message for a real empty
    schedule (a legitimate off-day), which IS worth showing, unlike a None result.

    CONFERENCE BOXES LAID OUT SIDE BY SIDE, not stacked full-width -- directly reported feedback:
    stacking wasted real estate on a wide screen, and would get genuinely painful for a many-
    conference sport (NCAAF: up to ~10 conferences full-width would mean 10 screens of scrolling
    just to see today's whole slate). Up to 3 conferences per row -- exactly fills one row for
    every 2-conference sport here (MLB/NBA/NFL/WNBA), and wraps into multiple rows for NCAAF
    without going so narrow that a game row's team names + time chip stop fitting comfortably.

    Each conference gets one color, cycled from _KPI_PALETTE -- the SAME palette kpi_row already
    uses for decorative-but-distinguishing variety (not the red/green/yellow reserved platform-
    wide for real win/loss data meaning). That color carries through to the division label and
    every game's time chip underneath it, so the section reads as one coherent design instead of
    plain, uncolored text rows -- matching the "commercial feel" component language established
    everywhere else on this platform, not a separately-styled, flatter-looking bolt-on."""
    if result is None:
        return
    section_header(icon, f"Today's {label} Schedule")

    grouped = result["grouped"]
    other = result["other"]
    has_divisions = result["has_divisions"]

    if not grouped and not other:
        st.caption("No games scheduled today.")
        return

    def _render_conference(conf: str, color: str) -> None:
        with st.container(border=True):
            st.markdown(
                f'<div style="display:inline-block;background:{color}22;border:1px solid '
                f'{color}55;color:{color};padding:4px 12px;border-radius:8px;font-weight:700;'
                f'font-size:13px;letter-spacing:0.3px;margin-bottom:8px;">{conf}</div>',
                unsafe_allow_html=True)
            divisions = grouped[conf]
            if has_divisions:
                for div in sorted(k for k in divisions.keys() if k is not None):
                    st.markdown(
                        f'<div style="font-size:11px;color:{color};opacity:0.9;font-weight:700;'
                        f'text-transform:uppercase;letter-spacing:0.6px;margin:10px 0 4px;">'
                        f'{div}</div>', unsafe_allow_html=True)
                    rows = "".join(_schedule_game_row(g, color) for g in divisions[div])
                    st.markdown(rows, unsafe_allow_html=True)
            else:
                # No division level for this sport (WNBA/NCAAF) -- every game for this
                # conference lives under the single None key group_games always uses.
                rows = "".join(_schedule_game_row(g, color) for g in divisions.get(None, []))
                st.markdown(rows, unsafe_allow_html=True)

    confs = sorted(grouped.keys())
    per_row = 3
    for row_start in range(0, len(confs), per_row):
        row_confs = confs[row_start:row_start + per_row]
        cols = st.columns(len(row_confs))
        for col, conf in zip(cols, row_confs):
            i = confs.index(conf)
            with col:
                _render_conference(conf, _KPI_PALETTE[i % len(_KPI_PALETTE)])

    if other:
        # Deliberately the neutral trend gray, not another palette color -- "Other" is a real
        # gap being surfaced honestly (see schedule_board.py), not a real grouped category that
        # deserves equal visual billing with AL/NL, Eastern/Western, etc.
        gray = _TREND_COLOR["neutral"]
        with st.container(border=True):
            st.markdown(
                f'<div style="display:inline-block;background:{gray}22;border:1px solid '
                f'{gray}55;color:{gray};padding:4px 12px;border-radius:8px;font-weight:700;'
                f'font-size:13px;letter-spacing:0.3px;margin-bottom:6px;">Other</div>',
                unsafe_allow_html=True)
            st.caption("Home team not in this platform's own conference/division reference "
                      "table yet (a real gap, not a hidden game) -- still shown below.")
            rows = "".join(_schedule_game_row(g, gray) for g in other)
            st.markdown(rows, unsafe_allow_html=True)
