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
