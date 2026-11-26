"""Nov 26: keep-warm opens the site like a visitor."""
import clockwork as CW
import keep_warm as KW


def test_keep_warm_is_dispatched_by_clockwork_on_its_own_cron():
    assert "keep-warm" in CW.WORKFLOWS
    assert CW.crons_of("keep-warm") == ["57 * * * *"]


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
