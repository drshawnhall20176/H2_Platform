"""Nov 25: the sport rides in the link so a restart reopens on it; the owner's own site never auto-opens the tour."""
import sports
import tour
import today_visual as TV


class _QP(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


def test_from_link_reads_an_offered_sport(monkeypatch):
    import streamlit as st
    monkeypatch.setattr(st, "query_params", _QP(sport="nba"), raising=False)
    assert sports.from_link(["NFL", "NBA"]) == "NBA"
    assert sports.from_link(["NFL"]) is None


def test_from_link_without_a_sport(monkeypatch):
    import streamlit as st
    monkeypatch.setattr(st, "query_params", _QP(), raising=False)
    assert sports.from_link(["NBA"]) is None


def test_keep_in_link_writes_only_on_change(monkeypatch):
    import streamlit as st
    qp = _QP(sport="NBA")
    monkeypatch.setattr(st, "query_params", qp, raising=False)
    sports.keep_in_link("NFL")
    assert qp["sport"] == "NFL"


def test_owner_site_counts_the_tour_as_seen(monkeypatch):
    import streamlit as st
    monkeypatch.setattr(st, "query_params", _QP(), raising=False)
    monkeypatch.setattr(st, "session_state", {}, raising=False)
    monkeypatch.setattr(st, "secrets", {"AUDIENCE": "owner"}, raising=False)
    assert tour.seen() is True
    monkeypatch.setattr(st, "secrets", {"AUDIENCE": "public"}, raising=False)
    assert tour.seen() is False


def test_cards_carry_the_phone_class():
    assert 'class="h2-card"' in TV.pick_card_html({"pick": "X Over 1.5", "chance": 0.6, "game": "A @ B"})


def test_team_possessive():
    import player_context as PX
    assert PX.possessive("Charlotte Hornets") == "Charlotte Hornets'"
    assert PX.possessive("Miami Heat") == "Miami Heat's"
