"""Nov 7: live-data pages carry the shared load-time notice; quick pages don't."""
import components as C


def test_which_pages_get_the_notice():
    for t in ("Best Bets", "Analyst Desk", "Game Script", "Position Matchups  ·  🏀 NBA", "H2 Sports — Command Center",
              "League Schedules", "H2 Sports — The Sports Trading Desk", "H2 Sports — Dinger Engine"):
        assert C.needs_load_notice(t), t
    for t in ("Reports", "Progression Plan", "Model Performance", "Analyst Record", "Highlights"):
        assert not C.needs_load_notice(t), t


def test_notice_renders_on_a_live_page(monkeypatch):
    shown = []
    monkeypatch.setattr(C.st, "caption", lambda text, **k: shown.append(text))
    monkeypatch.setattr(C.st, "markdown", lambda *a, **k: None)
    C.page_header("💰", "Best Bets", "x")
    C.page_header("📊", "Reports", "x")
    assert shown == [C.LOAD_NOTICE]
