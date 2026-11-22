"""show_picks (Nov 22): the Media Room and Podcast Studio talk about the platform's own picks and its shown record."""
import props_engine as PE


def _p(name, use, **kw):
    p = {"Player": name, "Team": "BOS", "Market": "Points", "Side": "Over", "Line": 20.5, "ModelProb": 0.62,
         "RealPrice": -110, "Use": use, "Why": "w", "Game": "A @ B"}
    p.update(kw)
    return p


def test_platform_plays_drop_no_edge_reads_and_rank_by_earned_edge(monkeypatch):
    import props_money as PM
    import show_picks as SP
    monkeypatch.setattr(PE, "play_is_money", lambda sport, p: p["Player"] == "Money Man")
    monkeypatch.setattr(PE, "play_is_lock", lambda p: False)
    monkeypatch.setattr(PM, "play_earned", lambda sport, p: {"Good": 0.58, "Money Man": 0.55, "Meh": 0.50}.get(p["Player"]))
    plays = [_p("Good", PE.USE_SINGLE), _p("Skip", PE.USE_PASS), _p("Money Man", PE.USE_PASS), _p("Meh", PE.USE_PARLAY)]
    out = {p["Player"]: p for p in SP.platform_plays("NBA", plays)}
    assert set(out) == {"Good", "Money Man", "Meh"}                       # a ⚪ No edge only when 💰
    assert out["Good"]["ModelProb"] == 0.58 and out["Good"]["RawProb"] == 0.62   # the show quotes the earned chance
    assert out["Good"]["EarnedEdge"] > 0 > out["Meh"]["EarnedEdge"]
    assert SP.tag(out["Money Man"]) == "💰 " and SP.tag(out["Good"]) == ""


def test_an_untagged_board_is_not_filtered():
    import show_picks as SP
    plays = [{"Player": "X", "Market": "Points", "Side": "Over", "Line": 1.5, "ModelProb": 0.6}]
    assert len(SP.platform_plays("NBA", plays)) == 1


def test_ledger_review_counts_each_shown_pick_once_for_the_sport():
    import pick_ledger as PL
    import show_picks as SP
    store = {
        PL.KEY.format(kind="strong", sport="ALL", day="2026-11-21"): {"rows": {
            "a": {"sport": "NBA", "pick": "A Over", "price": 100, "result": "win", "clv_mark": "beat"},
            "b": {"sport": "NFL", "pick": "B Over", "price": 100, "result": "loss"}}},
        PL.KEY.format(kind="money", sport="NBA", day="2026-11-21"): {"rows": {
            "a": {"sport": "NBA", "pick": "A Over", "price": 100, "result": "win", "clv_mark": "beat"},
            "c": {"sport": "NBA", "pick": "C Under", "price": -110, "result": "loss", "clv_mark": "lost"}}},
    }
    r = SP.ledger_review("NBA", "2026-11-21", get=lambda k, d=None: store.get(k, d))
    assert (r["hits"], r["misses"], r["beat"], r["lost"]) == (1, 1, 1, 1)
    assert abs(r["units"] - 0.0) < 1e-9
    assert "1–1" in SP.record_line(r, "Yesterday") and "1 of 2" in SP.record_line(r, "Yesterday")
    assert SP.ledger_review("NHL", "2026-11-21", get=lambda k, d=None: store.get(k, d)) is None


def test_the_show_opens_with_the_shown_record_and_each_sport_has_its_own_lessons():
    import podcast as PC
    ledger = {"hits": 3, "misses": 2, "units": 0.8, "beat": 4, "lost": 1, "open": 0,
              "wins": [{"pick": "A Over 20.5"}], "losses": [{"pick": "B Under 5.5"}]}
    running = {"hits": 10, "misses": 8, "units": 1.2, "since": "2026-11-21", "beat": 0, "lost": 0}
    S = PC.assemble_script("2026-11-22", [], [], None, None, sport="NBA", ledger=ledger, running=running)
    text = PC.script_to_text("2026-11-22", S)
    assert "the picks we showed yesterday: 3–2" in text and "A Over 20.5" in text and "B Under 5.5" in text
    assert "beat the closing line on 4 of the 5" in text and "10–8" in text
    assert PC.rotating_teaching("2026-11-22", "NFL") in PC.TEACHING_SEGMENTS_FOOTBALL
    assert PC.rotating_teaching("2026-11-22", "NCAAMB") in PC.TEACHING_SEGMENTS_BASKETBALL
    assert not any("she" in b.get("text", "").split() for seg in PC.TEACHING_SEGMENTS_BASKETBALL[:3]
                   for b in seg["beats"] if seg is not PC.TEACHING_SEGMENTS_WNBA[1])


def test_a_selection_beat_names_the_money_flag_and_earned_edge():
    import podcast as PC
    p = {"Player": "A", "Team": "BOS", "Market": "Points", "Side": "Over", "Line": 20.5, "ModelProb": 0.56,
         "Earned": 0.56, "EarnedEdge": 0.04, "Money": True, "RealPrice": -110, "PriceSource": "book", "Why": "w"}
    beats = PC.selection_beats(p)
    assert "💰 A" in beats[0]["text"] and "earned edge +4.0 pts" in beats[0]["text"]
    assert any("earned chance" in b["text"] for b in beats)


def test_a_board_ev_without_a_live_price_is_not_called_live_value():
    import podcast as PC
    p = {"Player": "A", "Team": "BOS", "Market": "Points", "Side": "Over", "Line": 20.5, "ModelProb": 0.56,
         "EV": 0.047, "RealPrice": -110, "PriceSource": "book", "Why": "w"}
    text = " ".join(b["text"] for b in PC.selection_beats(p))
    assert "Live price" not in text and "-110" in text


def test_no_picks_yesterday_still_reads_the_running_record():
    import podcast as PC
    running = {"hits": 4, "misses": 3, "units": 0.5, "since": "2026-11-21", "beat": 0, "lost": 0}
    text = PC.script_to_text("2026-11-22", PC.assemble_script("2026-11-22", [], [], None, None, sport="NFL",
                                                              running=running))
    assert "no NFL picks were shown yesterday" in text and "4–3" in text and "pick-six" in text
