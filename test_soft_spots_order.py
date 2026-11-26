"""Nov 26 (speed): the Today game card draws Soft spots after the players list."""
import game_card as GC
import today_visual as TV


def test_soft_spots_come_after_players(monkeypatch):
    order = []
    monkeypatch.setattr(GC, "build", lambda w: {"league": "NFL", "home": "B", "away": "A"})
    monkeypatch.setattr(GC, "render", lambda g, props, key=None: order.append("card"))
    monkeypatch.setattr(GC, "render_extras", lambda g, w, d, k, soft_spots=True: order.append(f"extras:{soft_spots}"))
    monkeypatch.setattr(GC, "render_soft_spots", lambda g, w, d: order.append("soft"))
    monkeypatch.setattr(TV, "_players_section", lambda w, p, k: order.append("players"))
    monkeypatch.setattr(TV, "all_props", lambda sp: [])
    TV._game_dialog.__wrapped__({"sport": "NFL", "game": "A @ B"}, [])
    assert order == ["card", "extras:False", "players", "soft"]
