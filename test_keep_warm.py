"""Nov 26: keep-warm opens the site like a visitor."""
import clockwork as CW
import keep_warm as KW


def test_keep_warm_is_dispatched_by_clockwork_on_its_own_cron():
    assert "keep-warm" in CW.WORKFLOWS
    assert CW.crons_of("keep-warm") == ["27,57 * * * *"]


def test_page_text_reads_every_frame():
    class F:
        def __init__(self, t):
            self.t = t

        def inner_text(self, sel, timeout=0):
            if self.t is None:
                raise RuntimeError("detached")
            return self.t

    class P:
        frames = [F("Hosted with Streamlit"), F(None), F("Today · Thursday · GAMES · EARLIEST FIRST")]
    t = KW.page_text(P())
    assert "Today ·" in t and any(d in t for d in KW.DONE_TEXT)


def test_no_url_is_a_quiet_skip(monkeypatch, capsys):
    monkeypatch.setattr(KW, "URL", "")
    assert KW.main([]) == 0 and "isn't set" in capsys.readouterr().out


def test_warm_page_times_one_more_page_and_never_raises(monkeypatch):
    """Nov 28: Pick'em and All picks are opened after Today so members don't pay their cold load."""
    monkeypatch.setattr(KW.time, "sleep", lambda s: None)

    class Frame:
        url = "x"

        def __init__(self, t):
            self.t = t

        def inner_text(self, sel, timeout=0):
            return self.t

    class Page:
        def __init__(self, t, boom=False):
            self.frames, self.boom = [Frame(t)], boom

        def goto(self, url, **k):
            if self.boom:
                raise RuntimeError("net")
    assert KW.warm_page(Page("266 DK Pick6 lines read"), "u", ("lines read",)) is not None
    assert KW.warm_page(Page("", boom=True), "u", ("lines read",)) is None
    assert [p for p, _ in KW.EXTRA][0] == "pickem_board"


def test_the_pickem_only_visit_is_its_own_mode(monkeypatch):
    """Nov 28: warm-pickem.yml opens just the Pick'em board every 10 minutes."""
    seen = []
    monkeypatch.setattr(KW, "visit_pickem", lambda url: seen.append(url) or {"pickem_board": 12.0})
    monkeypatch.setattr(KW, "visit", lambda url: (_ for _ in ()).throw(AssertionError("full visit")))
    assert KW.main(["--pickem", "https://x.app"]) == 0 and seen == ["https://x.app"]
    import pathlib
    wf = pathlib.Path(".github/workflows/warm-pickem.yml").read_text()
    assert "keep_warm.py --pickem" in wf and "workflow_dispatch" in wf
