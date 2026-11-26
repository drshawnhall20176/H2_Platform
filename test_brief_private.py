"""Nov 26: the owner's notes and bets never reach the public job logs; the brief shows on Today for the owner."""
import inspect

import brief_panel
import morning_brief as MB
import reconcile_bets as RB


def test_the_brief_text_is_never_printed():
    src = inspect.getsource(MB.run)
    assert "print(text)" not in src


def test_reconcile_writes_nothing_in_github_actions(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    summary = tmp_path / "s.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    RB._out("| 1 | a bet | -110 | $5.00 |")
    assert capsys.readouterr().out == ""
    assert not summary.exists()


def test_reconcile_prints_locally(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    RB._out("hello")
    assert "hello" in capsys.readouterr().out


def test_panel_stays_off_the_public_build(monkeypatch):
    import streamlit as st
    monkeypatch.setattr(st, "secrets", {"AUDIENCE": "public"}, raising=False)
    assert brief_panel.render("2026-11-26") is False


def test_today_draws_the_brief_once():
    src = open("views/57_Today.py").read()
    assert src.count("_BPT.render()") == 1
