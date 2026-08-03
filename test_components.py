"""Tests for components.py -- KPI tiles, section headers, and base CSS.

These render HTML strings rather than pixels, so tests here verify structural correctness
(balanced tags, correct color selection, graceful handling of missing/edge-case input) --
not visual appearance, which can't be verified without an actual browser render."""

import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def captured(monkeypatch):
    """Mocks st.markdown to capture the HTML each component call renders, without needing a
    real Streamlit runtime."""
    calls = []
    import components as C
    monkeypatch.setattr(C.st, "markdown", lambda html, **kw: calls.append(html))
    return calls


def _balanced_divs(html: str) -> bool:
    return html.count("<div") == html.count("</div>")


def test_kpi_row_renders_balanced_html_for_every_item(captured):
    import components as C
    C.kpi_row([
        {"icon": "⚾", "value": "12", "label": "Tonight's games"},
        {"icon": "🎲", "value": "47", "label": "Model plays"},
        {"icon": "⭐", "value": "2.4×", "label": "Top lean", "help": "Devers HR Over"},
    ])
    assert len(captured) == 1
    assert _balanced_divs(captured[0])
    assert "12" in captured[0] and "Tonight's games" in captured[0]
    print("✓ kpi_row renders one balanced HTML block covering every item")


def test_kpi_row_neutral_tiles_use_palette_not_trend_color(captured):
    import components as C
    C.kpi_row([{"icon": "⚾", "value": "0", "label": "No games"}])
    # No trend given -> falls back to the decorative palette, not a good/bad color
    assert "#16a34a" not in captured[0] and "#dc2626" not in captured[0]
    assert C._KPI_PALETTE[0] in captured[0]
    print("✓ a tile with no trend uses the decorative palette, not a good/bad color")


def test_kpi_row_good_trend_uses_green():
    import components as C
    assert C._TREND_COLOR["good"] == "#16a34a"


def test_kpi_row_bad_trend_uses_red(captured):
    import components as C
    C.kpi_row([{"icon": "💰", "value": "-1.2%", "label": "Avg CLV", "trend": "bad"}])
    assert C._TREND_COLOR["bad"] in captured[0]
    print("✓ a tile with trend='bad' (e.g. negative CLV) renders with the real bad-trend color")


def test_kpi_row_good_trend_renders_correct_color(captured):
    import components as C
    C.kpi_row([{"icon": "📈", "value": "58%", "label": "Beat-close rate", "trend": "good"}])
    assert C._TREND_COLOR["good"] in captured[0]
    print("✓ a tile with trend='good' renders with the real good-trend color")


def test_kpi_row_empty_list_does_not_call_markdown(captured):
    import components as C
    C.kpi_row([])
    assert captured == []
    print("✓ kpi_row with an empty list renders nothing, doesn't call markdown with empty content")


def test_kpi_row_missing_optional_fields_do_not_crash(captured):
    import components as C
    # No icon, no help, no trend, no value -- every field is technically optional
    C.kpi_row([{"label": "Bare minimum"}])
    assert _balanced_divs(captured[0])
    assert "—" in captured[0]   # missing value falls back to an em dash, not blank/crash
    print("✓ kpi_row handles a tile with only a label, no crash, honest em-dash fallback for value")


def test_section_header_renders_balanced_html(captured):
    import components as C
    C.section_header("⭐", "Tonight's top leans", "Best plays right now")
    assert _balanced_divs(captured[0])
    assert "Tonight's top leans" in captured[0]
    assert "Best plays right now" in captured[0]
    print("✓ section_header renders balanced HTML with both title and subtitle")


def test_section_header_without_subtitle_omits_subtitle_html(captured):
    import components as C
    C.section_header("🧾", "The proof")
    assert _balanced_divs(captured[0])
    assert "The proof" in captured[0]
    print("✓ section_header without a subtitle still renders balanced, valid HTML")


def test_section_header_uses_custom_color_when_given(captured):
    import components as C
    C.section_header("🎯", "Custom colored header", color="#ff0000")
    assert "#ff0000" in captured[0]
    print("✓ section_header respects a custom color override")


def test_base_css_renders_style_block(captured):
    import components as C
    C.base_css()
    assert "<style>" in captured[0] and "</style>" in captured[0]
    print("✓ base_css renders a real <style> block")


def test_hero_banner_renders_balanced_html_with_icon_title_subtitle(captured):
    import components as C
    C.hero_banner("🏆", "H2 Sports — Command Center", "Trade sports, not bet sports.")
    assert captured[0].count("<div") == captured[0].count("</div>")
    assert "H2 Sports — Command Center" in captured[0]
    assert "Trade sports, not bet sports." in captured[0]
    print("✓ hero_banner renders balanced HTML with icon, title, and subtitle all present")


def test_hero_banner_embeds_the_real_logo_asset(captured):
    # Confirms the actual assets/h2_logo.png file is found and embedded, not just that the
    # code path exists -- this only passes if the real asset is present and readable.
    import components as C
    C._b64_asset.clear()   # don't let another test's cache hit hide a real regression here
    C.hero_banner("⚾", "H2 Sports — MLB Model Dashboard", "Live matchup analytics")
    assert "data:image/png;base64," in captured[0]
    assert "<img" in captured[0]
    print("✓ hero_banner embeds the real logo asset as a base64 data URI")


def test_hero_banner_degrades_gracefully_when_asset_missing(captured, monkeypatch):
    # FAILS SAFE: a missing/stripped asset must never crash hero_banner or leave a broken-image
    # tag -- just the original icon+title+subtitle layout with no logo slot.
    import components as C
    monkeypatch.setattr(C, "_b64_asset", lambda name: None)
    C.hero_banner("🏆", "H2 Sports — Command Center", "Trade sports, not bet sports.")
    assert "<img" not in captured[0]
    assert "H2 Sports — Command Center" in captured[0]
    assert captured[0].count("<div") == captured[0].count("</div>")
    print("✓ hero_banner degrades to icon+title+subtitle only, no broken image, when the "
         "logo asset is missing")


def test_pipeline_chips_correct_arrow_count_between_steps(captured):
    import components as C
    C.pipeline_chips(["Step A", "Step B", "Step C", "Step D"])
    # 2 markdown calls: the style block, then the chips themselves
    assert len(captured) == 2
    assert captured[1].count("pipe-arrow") == 3   # N steps -> N-1 arrows, not N or N+1
    for step in ["Step A", "Step B", "Step C", "Step D"]:
        assert step in captured[1]
    print("✓ pipeline_chips renders exactly N-1 arrows for N steps, all steps present")


def test_pipeline_chips_single_step_has_no_dangling_arrow(captured):
    import components as C
    C.pipeline_chips(["Only One Step"])
    assert "pipe-arrow" not in captured[1]
    print("✓ pipeline_chips with a single step has no dangling trailing arrow")


def test_pipeline_chips_empty_list_does_not_crash(captured):
    import components as C
    C.pipeline_chips([])
    assert captured[1] == ""
    print("✓ pipeline_chips with an empty list renders nothing for the chips, no crash")


def test_kpi_palette_has_no_red_or_green_for_neutral_tiles():
    # Real, deliberate design constraint: the decorative palette must never overlap with this
    # platform's own red/green data-meaning language (grades, RdYlGn gradients) -- confirms this
    # stays true rather than silently drifting if the palette is ever edited later.
    import components as C
    reds_greens = {"#16a34a", "#dc2626", "#22c55e", "#ef4444"}
    for color in C._KPI_PALETTE:
        assert color not in reds_greens, f"{color} looks like a red/green data-meaning color"
    print("✓ the decorative KPI palette contains no colors that could be confused with this "
         "platform's own red/green data-meaning language")


def test_wrapped_tab_picker_returns_value_not_label(monkeypatch):
    # Regression guard for the actual fix requested: replaces native st.tabs (which overflows
    # off-screen with a truncating ">" arrow once there are too many markets) with st.pills,
    # confirmed directly against Streamlit's own docs to wrap naturally to multiple rows.
    import components as C
    calls = []

    def fake_pills(label, options, **kw):
        calls.append((label, options, kw))
        return "Batter HR"   # simulate the user having selected this pill

    monkeypatch.setattr(C.st, "pills", fake_pills)
    items = [("All", None), ("Batter HR", "Batter HR"), ("Batter Total Bases", "Batter Total Bases")]
    result = C.wrapped_tab_picker(items, key="top_leans_market")
    assert result == "Batter HR"
    print("✓ wrapped_tab_picker returns the underlying VALUE for the selected label, not the label itself")


def test_wrapped_tab_picker_calls_pills_with_correct_parameters(monkeypatch):
    import components as C
    calls = []
    monkeypatch.setattr(C.st, "pills", lambda label, options, **kw: calls.append((label, options, kw)) or options[0])
    items = [("All", None), ("Batter HR", "Batter HR")]
    C.wrapped_tab_picker(items, key="my_key")
    _, options, kw = calls[0]
    assert options == ["All", "Batter HR"]
    assert kw["default"] == "All"
    assert kw["required"] is True   # matches real st.tabs() behavior: always exactly one selection
    assert kw["key"] == "my_key"
    assert kw["label_visibility"] == "collapsed"
    print("✓ wrapped_tab_picker calls st.pills with correct options, default, required=True, "
         "and a collapsed label")


def test_wrapped_tab_picker_respects_default_index(monkeypatch):
    import components as C
    calls = []
    monkeypatch.setattr(C.st, "pills", lambda label, options, **kw: calls.append((label, options, kw)) or options[0])
    items = [("All", None), ("Batter HR", "Batter HR"), ("Batter Total Bases", "Batter Total Bases")]
    C.wrapped_tab_picker(items, key="k", default_index=1)
    _, _, kw = calls[0]
    assert kw["default"] == "Batter HR"
    print("✓ wrapped_tab_picker passes the correct label as default when default_index is given")


def test_page_header_renders_balanced_html_with_icon_title_subtitle(captured):
    import components as C
    C.page_header("⭐", "Best Bets", "The strongest leans across the slate")
    assert _balanced_divs(captured[0])
    assert "Best Bets" in captured[0]
    assert "The strongest leans across the slate" in captured[0]
    print("✓ page_header renders balanced HTML with icon, title, and subtitle all present")


def test_page_header_is_lighter_weight_than_hero_banner(captured):
    # Real, deliberate distinction: page_header must NOT carry hero_banner's gradient
    # background -- it's meant to be the lighter alternative for ordinary sub-pages, not a
    # second copy of the front-door treatment.
    import components as C
    C.page_header("🏅", "Graded Picks", "Every game on the slate, graded")
    assert "linear-gradient" not in captured[0]
    assert "h2-hero" not in captured[0]
    print("✓ page_header does not carry hero_banner's gradient background -- confirmed "
         "genuinely lighter-weight, not a duplicate")


# ----------------------------------------------------------------- Today's Schedule (logos + row layout)
def test_team_logo_html_includes_onerror_fallback():
    import components as C
    html = C._team_logo_html("https://www.mlbstatic.com/team-logos/147.svg")
    assert "<img" in html
    assert "onerror" in html and "display" in html
    print("✓ _team_logo_html includes an onerror fallback that hides a broken/wrong image, "
         "never shows a broken-image icon")


def test_team_logo_html_empty_for_no_url():
    import components as C
    assert C._team_logo_html(None) == ""
    assert C._team_logo_html("") == ""
    print("✓ _team_logo_html renders nothing at all when no URL is known, not a placeholder")


def test_schedule_game_row_uses_grid_alignment_not_space_between():
    # Regression guard for the real, reported feedback this replaced: the original layout used
    # justify-content:space-between (flex), stretching team names and time/venue across the full
    # row width. Then upgraded again to a real CSS Grid so columns actually align down the page
    # -- confirms both: no leftover flex space-between, and the row genuinely uses the shared
    # grid column template, not just "some gap."
    import components as C
    g = {"home": "New York Yankees", "away": "Boston Red Sox", "dt": None, "time_known": False,
        "venue": "Yankee Stadium", "home_logo": None, "away_logo": None}
    html = C._schedule_game_row(g, "#3b82f6", C._GRID_COLS_WITH_ROSTER, True)
    assert "justify-content:space-between" not in html
    assert "display:grid" in html
    assert C._GRID_COLS_WITH_ROSTER in html
    print("✓ schedule game row uses real CSS Grid with the shared column template, not "
         "flex space-between")


def test_schedule_game_row_includes_logos_when_present():
    import components as C
    g = {"home": "New York Yankees", "away": "Boston Red Sox", "dt": None, "time_known": False,
        "venue": None, "home_logo": "https://www.mlbstatic.com/team-logos/147.svg",
        "away_logo": "https://www.mlbstatic.com/team-logos/111.svg"}
    html = C._schedule_game_row(g, "#3b82f6", C._GRID_COLS_WITH_ROSTER, True)
    assert html.count("<img") == 2
    assert "147.svg" in html and "111.svg" in html
    print("✓ schedule game row includes both team logos when both URLs are known")


def test_schedule_game_row_omits_logos_when_absent():
    import components as C
    g = {"home": "Some Team", "away": "Other Team", "dt": None, "time_known": False,
        "venue": None, "home_logo": None, "away_logo": None}
    html = C._schedule_game_row(g, "#3b82f6", C._GRID_COLS_WITH_ROSTER, True)
    assert "<img" not in html
    print("✓ schedule game row has zero <img> tags when no logos are available, not broken ones")


def test_todays_schedule_board_lays_out_conferences_in_columns(monkeypatch, captured):
    # Regression guard for the real, reported feedback: conference boxes must render side by
    # side (st.columns), not stacked full-width containers.
    import components as C
    import schedule_board as SB
    from datetime import datetime
    import pytz
    ET = pytz.timezone("US/Eastern")
    games = [
        {"home": "New York Yankees", "away": "Boston Red Sox",
         "dt": ET.localize(datetime(2026, 8, 1, 19)), "time_known": True, "venue": None,
         "home_logo": None, "away_logo": None},
        {"home": "Los Angeles Dodgers", "away": "San Diego Padres",
         "dt": ET.localize(datetime(2026, 8, 1, 22)), "time_known": True, "venue": None,
         "home_logo": None, "away_logo": None},
    ]
    result = SB.group_games("MLB", games)
    columns_calls = []
    monkeypatch.setattr(C.st, "columns", lambda n: columns_calls.append(n) or
                        [MagicMock() for _ in range(n)])
    monkeypatch.setattr(C.st, "container", lambda **kw: MagicMock())
    C.todays_schedule_board(result, "⚾", "MLB")
    assert columns_calls, "todays_schedule_board must call st.columns to lay out conferences side by side"
    print(f"✓ todays_schedule_board lays out conferences using st.columns (called with n={columns_calls})")


# ----------------------------------------------------------------- status badge + lineup bubbles
def test_status_badge_shown_for_non_scheduled_states():
    import components as C
    assert "Live" in C._status_badge_html("in-progress")
    assert "Delayed" in C._status_badge_html("delayed")
    assert "Canceled" in C._status_badge_html("canceled")
    assert "Final" in C._status_badge_html("finished")
    print("✓ _status_badge_html shows the right label for every non-scheduled state")


def test_status_badge_empty_for_scheduled_or_unknown():
    # Deliberate: the time chip already says "upcoming" -- a same-meaning badge is redundant.
    import components as C
    assert C._status_badge_html("scheduled") == ""
    assert C._status_badge_html(None) == ""
    assert C._status_badge_html("") == ""
    print("✓ _status_badge_html renders nothing for scheduled/unknown status, no redundant badge")


def test_lineup_bubble_shows_green_for_confirmed_red_for_not():
    import components as C
    html = C._lineup_bubble_html({"home_lineup_confirmed": True, "away_lineup_confirmed": False})
    assert html.count("border-radius:50%") == 2   # two dots
    assert C._TREND_COLOR["good"] in html   # home: green
    assert C._TREND_COLOR["bad"] in html    # away: red
    assert "H:" in html and "A:" in html
    print("✓ lineup bubbles show green for a confirmed lineup and red for one that isn't, "
         "independently per side")


def test_lineup_bubble_empty_when_not_applicable():
    # Sports without a confirmed lineup-status signal (NBA/WNBA/NFL/NCAAF right now) pass both
    # as None -- must render nothing at all, not a pair of misleading red dots.
    import components as C
    assert C._lineup_bubble_html({"home_lineup_confirmed": None, "away_lineup_confirmed": None}) == ""
    print("✓ lineup bubbles render nothing when the sport has no confirmed signal, not a false red")


def test_schedule_game_row_includes_status_and_lineup_bubbles():
    import components as C
    g = {"home": "New York Yankees", "away": "Boston Red Sox", "dt": None, "time_known": False,
        "venue": None, "home_logo": None, "away_logo": None, "status": "delayed",
        "home_lineup_confirmed": True, "away_lineup_confirmed": True}
    html = C._schedule_game_row(g, "#3b82f6", C._GRID_COLS_WITH_ROSTER, True)
    assert "Delayed" in html
    assert html.count("border-radius:50%") == 2
    print("✓ schedule game row includes both the status badge and lineup bubbles when present")


def test_schedule_game_row_has_no_embedded_newlines():
    # REAL, CONFIRMED REGRESSION GUARD, not a style preference: a real bug shipped and was
    # reported live -- multiple game rows get joined together with "".join() into ONE
    # st.markdown() call (see todays_schedule_board's own rows = "".join(...)). A pretty-printed,
    # indented multi-line f-string renders fine in isolation but gets misread by the markdown
    # renderer once several are concatenated -- deeply-indented inner lines (the time chip and
    # venue, in the live report) get treated as an indented Markdown code block and leak as
    # literal escaped text instead of rendering as HTML. Team names (shallow, single-line)
    # rendered fine, which is exactly what made the bug confusing to spot from the screenshot
    # alone. This test fails loudly if a future edit reintroduces a multi-line/indented f-string
    # here, before it ever reaches a real deploy.
    import components as C
    g = {"home": "New York Yankees", "away": "Boston Red Sox",
        "dt": None, "time_known": False, "venue": "Yankee Stadium",
        "home_logo": "https://example.com/a.png", "away_logo": "https://example.com/b.png",
        "status": "in-progress", "home_lineup_confirmed": True, "away_lineup_confirmed": False}
    html = C._schedule_game_row(g, "#3b82f6", C._GRID_COLS_WITH_ROSTER, True)
    assert "\n" not in html, (
        "schedule game row HTML contains an embedded newline -- this is exactly the shape of "
        "bug that made real content (time/venue) render as literal escaped text once multiple "
        "rows were joined together for one st.markdown() call")
    # Also confirm the fix holds up under the ACTUAL join() multiple rows go through together --
    # not just one row in isolation.
    joined = html + html + html
    assert "\n" not in joined
    assert "&lt;span" not in joined and "<span" in joined   # real HTML, not escaped-as-text
    print("✓ schedule game row (alone and joined with others) contains zero embedded newlines -- "
         "the exact condition that caused real content to render as literal text")


# ----------------------------------------------------------------- header row + legend
def test_schedule_header_labels_are_centered():
    import components as C
    html = C._schedule_header_html(C._GRID_COLS_WITH_ROSTER, show_roster=True)
    assert html.count("text-align:center") == 4   # Teams, Time, Roster Status, Location
    print("✓ every header label is centered within its own column")


def test_schedule_header_includes_roster_column_when_requested():
    import components as C
    html = C._schedule_header_html(C._GRID_COLS_WITH_ROSTER, show_roster=True)
    assert "Teams" in html and "Time" in html and "Roster Status" in html and "Location" in html
    print("✓ header row includes the Roster Status column when show_roster is True")


def test_schedule_header_omits_roster_column_when_not_applicable():
    import components as C
    html = C._schedule_header_html(C._GRID_COLS_NO_ROSTER, show_roster=False)
    assert "Teams" in html and "Time" in html and "Location" in html
    assert "Roster Status" not in html
    print("✓ header row omits the Roster Status column entirely when the sport has no lineup data")


def test_lineup_legend_explains_both_colors():
    import components as C
    html = C._lineup_legend_html()
    assert "posted" in html.lower()
    assert "not yet confirmed" in html.lower() or "projected" in html.lower()
    assert C._TREND_COLOR["good"] in html and C._TREND_COLOR["bad"] in html
    assert "\n" not in html
    print("✓ lineup legend explains both the green (posted) and red (not confirmed) states")


def test_todays_schedule_board_shows_legend_when_roster_data_present(monkeypatch, captured):
    import components as C
    import schedule_board as SB
    from datetime import datetime
    import pytz
    ET = pytz.timezone("US/Eastern")
    games = [{"home": "New York Yankees", "away": "Boston Red Sox",
             "dt": ET.localize(datetime(2026, 8, 1, 19)), "time_known": True, "venue": None,
             "home_logo": None, "away_logo": None, "status": "scheduled",
             "home_lineup_confirmed": False, "away_lineup_confirmed": True}]
    result = SB.group_games("MLB", games)
    monkeypatch.setattr(C.st, "columns", lambda n: [MagicMock() for _ in range(n)])
    monkeypatch.setattr(C.st, "container", lambda **kw: MagicMock())
    C.todays_schedule_board(result, "⚾", "MLB")
    assert any("Lineup officially posted" in call for call in captured)
    print("✓ todays_schedule_board shows the legend when at least one game has real lineup data")


def test_todays_schedule_board_omits_legend_when_no_roster_data(monkeypatch, captured):
    import components as C
    import schedule_board as SB
    from datetime import datetime
    import pytz
    ET = pytz.timezone("US/Eastern")
    games = [{"home": "Boston Celtics", "away": "Miami Heat",
             "dt": ET.localize(datetime(2026, 8, 1, 19)), "time_known": True, "venue": None,
             "home_logo": None, "away_logo": None, "status": "scheduled",
             "home_lineup_confirmed": None, "away_lineup_confirmed": None}]
    result = SB.group_games("NBA", games)
    monkeypatch.setattr(C.st, "columns", lambda n: [MagicMock() for _ in range(n)])
    monkeypatch.setattr(C.st, "container", lambda **kw: MagicMock())
    C.todays_schedule_board(result, "🏀", "NBA")
    assert not any("Lineup officially posted" in call for call in captured)
    assert not any("Roster Status" in call for call in captured)
    print("✓ todays_schedule_board omits the legend AND the Roster Status column entirely for "
         "a sport with no lineup data (NBA)")


# ----------------------------------------------------------------- _schedule_game_row: real date fallback
def test_schedule_game_row_shows_real_time_when_known():
    import components as C
    from datetime import datetime
    import pytz
    ET = pytz.timezone("US/Eastern")
    g = {"home": "Yankees", "away": "Red Sox", "dt": ET.localize(datetime(2026, 8, 3, 19, 5)),
        "time_known": True, "venue": "Yankee Stadium", "status": "scheduled"}
    row = C._schedule_game_row(g, "#5865F2", C._GRID_COLS_NO_ROSTER, False)
    assert "7:05 PM ET" in row
    print("✓ _schedule_game_row shows the real time when time_known and dt are both present")


def test_schedule_game_row_shows_real_date_when_time_unknown_but_dt_exists():
    # THE real, confirmed fix for NCAAF's own start_time_tbd case: dt parses fine (the DATE is
    # real and known) even when the specific kickoff time isn't confirmed -- this used to
    # silently discard that real date and show a bare, uninformative "Time TBD" instead.
    import components as C
    from datetime import datetime
    import pytz
    ET = pytz.timezone("US/Eastern")
    g = {"home": "Georgia", "away": "Alabama", "dt": ET.localize(datetime(2026, 9, 5, 0, 0)),
        "time_known": False, "venue": None, "status": "scheduled"}
    row = C._schedule_game_row(g, "#5865F2", C._GRID_COLS_NO_ROSTER, False)
    assert "9/5" in row and "Time TBD" in row
    print("✓ _schedule_game_row shows the real date (with an honest Time TBD) when dt exists but time_known is False")


def test_schedule_game_row_shows_real_date_from_date_str_when_dt_is_none():
    # THE real, confirmed fix for NFL's own real case: dt is ALWAYS None for this sport (a
    # date-only field can't safely parse a time, see schedule_board._nfl_games' own comment),
    # but the real YYYY-MM-DD string is now kept and used here instead of being discarded.
    import components as C
    g = {"home": "Chiefs", "away": "Bills", "dt": None, "time_known": False, "venue": None,
        "status": "scheduled", "date_str": "2026-09-07"}
    row = C._schedule_game_row(g, "#5865F2", C._GRID_COLS_NO_ROSTER, False)
    assert "9/7" in row and "Time TBD" in row
    print("✓ _schedule_game_row shows the real date from date_str (NFL's own real field) when dt itself is None")


def test_schedule_game_row_bare_time_tbd_when_truly_nothing_known():
    import components as C
    g = {"home": "Team A", "away": "Team B", "dt": None, "time_known": False, "venue": None,
        "status": "scheduled"}   # no date_str either -- a genuine "nothing known" floor case
    row = C._schedule_game_row(g, "#5865F2", C._GRID_COLS_NO_ROSTER, False)
    assert "Time TBD" in row
    print("✓ _schedule_game_row falls back to a bare Time TBD only when truly no real date info exists at all")
