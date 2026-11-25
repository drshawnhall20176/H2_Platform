"""
today_visual.py — the clickable Today page (Nov 25, commercial preview only).

Owner, Nov 24: "One thing that I like on the H2 site is the today page ... we are missing some good functionality like
the ability to click a card and have it jump to a game or prop." The customer Today page (views/57_Today.py) gets a
Cards view, in H2's own look (h2_brand.py):

  * one bordered row per sport playing today: its strongest picks as cards (player picks from pick types with a
    winning 30-day record; game lines for the game-line sports, each saying 🃏 Bet / 🧪 Tracking / Info only), each
    with an "Open" button -> the player card (player_card.py) or the game card (game_card.py) in a pop-up;
  * under it, a strip of that sport's games, by start time, each opening its game card.

It is shown only in the commercial layout (a commercial deployment, or the owner previewing it); the tables stay one
click away (the page's Cards | Table switch). It reads only what the boards already saved.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Sequence

import h2_brand as HB

STRIP_MAX = 8
CARDS_PER_SPORT = 4


# --------------------------------------------------------------------------- data (no Streamlit)
def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()


def _nick(team) -> str:
    w = _norm(team).split()
    return w[-1] if w else ""


def same_game(prop_game, home, away) -> bool:
    """A prop row's game string against a board game's teams: exact, or both teams' last names in it."""
    g = _norm(prop_game)
    if not g:
        return False
    if g == _norm(f"{away} @ {home}"):
        return True
    h, a = _nick(home), _nick(away)
    return bool(h and a) and h in g.split() and a in g.split()


def props_in_game(rows: Sequence[Dict], w: Dict) -> List[Dict]:
    rec = w.get("_rec") or {}
    home, away = rec.get("home"), rec.get("away")
    sp = w.get("sport")
    return [r for r in rows or [] if r.get("kind") == "Prop" and r.get("sport") == sp
            and same_game(r.get("game"), home, away)]


def kickoff_key(w: Dict) -> str:
    return str((w.get("_rec") or {}).get("kickoff") or (w.get("_full") or {}).get("kickoff") or "9999")


def games_for(winners: Sequence[Dict], sport: str) -> List[Dict]:
    """A sport's games, earliest first; games already started go last."""
    import game_lines_table as GLT
    ws = [w for w in winners or [] if w.get("sport") == sport]

    def started(w):
        try:
            return GLT.started(w)
        except Exception:                                       # noqa: BLE001
            return False
    return sorted(ws, key=lambda w: (started(w), kickoff_key(w)))


def prop_row_for(rows: Sequence[Dict], card: Dict) -> Optional[Dict]:
    return next((r for r in rows or [] if r.get("kind") == "Prop" and r.get("sport") == card.get("sport")
                 and r.get("pick") == card.get("pick")), None)


def sport_cards(sport: str, rows: Sequence[Dict], winners: Sequence[Dict], day: str,
                records_for: Optional[Callable] = None, line_rows: Optional[Callable] = None) -> List[Dict]:
    """Up to four cards for one sport: game-line sports show their game lines (Bet? first); the others their player
    picks from winning pick types, topped up with playable game lines."""
    import college_lines as CLT
    import customer_today as CT
    if sport in CLT.LINE_SPORTS_TODAY:
        lr = (line_rows or (lambda s: CLT.today_rows(s, day, winners)))(sport)
        return [dict(c, kind="Line") for c in CLT.today_cards(lr, n=CARDS_PER_SPORT)]
    out = []
    if sport in CT.PROPS_SPORTS:
        for c in CT.top_cards([r for r in rows or [] if r.get("sport") == sport], records_for=records_for,
                              n=CARDS_PER_SPORT):
            out.append(dict(c, kind="Prop"))
    if len(out) < CARDS_PER_SPORT:
        for ln in CT.line_picks([w for w in winners or [] if w.get("sport") == sport]):
            out.append({"sport": sport, "pick": ln["Pick"], "chance": ln.get("Chance"), "price": ln.get("Best price"),
                        "game": ln.get("Game") or "", "time": ln.get("Time") or "", "record": ln.get("Record (30 days)"),
                        "basis": ln.get("Basis"), "kind": "Line", "lock": False, "money": False})
            if len(out) >= CARDS_PER_SPORT:
                break
    return out


# --------------------------------------------------------------------------- drawing
import streamlit as _st


# The two pop-ups, at module level so a click inside one (a player picker in the game card) reruns just the pop-up.
FAV_KEY = "h2_favs"


def favorites() -> List[str]:
    """Nov 25: the viewer's ⭐ players. Kept for the session and in the page's web address (?fav=...), so a bookmark
    of the page brings them back; nothing is saved on the server."""
    if FAV_KEY not in _st.session_state:
        try:
            raw = _st.query_params.get("fav") or ""
        except Exception:                                       # noqa: BLE001
            raw = ""
        _st.session_state[FAV_KEY] = [x for x in str(raw).split("|") if x]
    return list(_st.session_state[FAV_KEY])


def set_favorite(name: str, on: bool) -> List[str]:
    favs = [f for f in favorites() if f != name] + ([name] if on else [])
    _st.session_state[FAV_KEY] = favs
    try:
        if favs:
            _st.query_params["fav"] = "|".join(favs)
        elif "fav" in _st.query_params:
            del _st.query_params["fav"]
    except Exception:                                           # noqa: BLE001
        pass
    return favs


def player_of(row: Dict) -> str:
    return str(row.get("player") or row.get("Player") or "")


@_st.dialog("Player card", width="large")
def _player_dialog(row: Dict, sport: str):
    import game_previews as GP
    import player_card as PC
    c = PC.from_row(row)
    name = player_of(row)
    if name:
        on = _st.toggle("⭐ Favorite", value=name in favorites(), key=f"fav_{_norm(name).replace(' ', '_')}",
                        help="Your favorites show first on Today. Bookmark the page to keep them.")
        if on != (name in favorites()):
            set_favorite(name, on)
    PC.render(c, sport, bet=GP.prop_bet(sport, str(c.get("Use") or ""), c))


@_st.dialog("Game card", width="large")
def _game_dialog(w: Dict, props: List[Dict]):
    import game_card as GC
    if w.get("sport") == "SOCCER":                              # Nov 25: soccer's own card (three results)
        GC.render_soccer(GC.build_soccer(w, props))
        return
    if w.get("sport") == "UFC":                                 # Nov 25: a fight card (market only)
        GC.render_fight(GC.build_fight(w))
        return
    if w.get("sport") == "TENNIS":                              # Nov 25: a match card, not a basketball box
        GC.render_tennis(GC.build_tennis(w))
        return
    k = f"gcd_{_norm(w.get('game')).replace(' ', '_')}"
    g = GC.build(w)
    GC.render(g, props, key=k)
    try:                                                        # Nov 25: pace, form, team strength, log boxes
        GC.render_extras(g, w, _today_et(), k)
    except Exception:                                           # noqa: BLE001 -- the card never breaks on an extra
        pass


@_st.dialog("Pick", width="large")
def _basic_dialog(c: Dict):
    import game_card as GC
    GC.render_basic(c)


@_st.cache_data(ttl=600, show_spinner=False, max_entries=8)
def _soccer_rows_cached(day: str, past: bool) -> List[Dict]:
    import todays_best as TB
    return TB.soccer_rows(day, past=past)


@_st.cache_data(ttl=600, show_spinner=False, max_entries=8)
def _soccer_flags_cached(day: str) -> List[Dict]:
    import todays_best as TB
    return TB.soccer_flags(day)


def _today_et() -> str:
    import pytz
    from datetime import datetime as _dt
    return _dt.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")


def soccer_games(day: str, loader: Optional[Callable] = None) -> List[Dict]:
    """Nov 25 (owner: soccer cards said "isn't on the saved board yet"): the day's soccer games, earliest first."""
    try:
        if loader is None:
            import todays_best as TB
            from datetime import datetime as _dt
            import pytz
            past = day < _dt.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
            rows = _soccer_rows_cached(day, past)              # Nov 25: cached -- reading every league is slow
        else:
            rows = loader(day)
    except Exception:                                           # noqa: BLE001
        rows = []
    return sorted(rows, key=kickoff_key)


@_st.cache_data(ttl=600, show_spinner=False, max_entries=4)
def _ufc_card_cached(day: str) -> List[Dict]:
    import customer_today as CT
    import ufc_engine as UE
    k = CT.odds_key()
    return UE.main_card_only(UE.get_card(k, day)) if k else []


def ufc_bouts(day: str, loader: Optional[Callable] = None) -> List[Dict]:
    """Nov 25 (owner: "how do we handle UFC that one seems like an outlier"): the day's main-card bouts (one odds
    request, cached 10 minutes), each as a game-strip row."""
    try:
        card = loader(day) if loader is not None else _ufc_card_cached(day)
    except Exception:                                           # noqa: BLE001
        card = []
    out = []
    for b in card or []:
        out.append(dict(b, sport="UFC", game=f"{b.get('a')} vs {b.get('b')}", _rec={"kickoff": b.get("commence")}))
    return sorted(out, key=kickoff_key)


def soccer_flags(day: str) -> List[Dict]:
    try:
        return _soccer_flags_cached(day)
    except Exception:                                           # noqa: BLE001
        return []


def _chance(x) -> str:
    try:
        return f"{float(x):.0%}"
    except (TypeError, ValueError):
        return "—"


def pick_card_html(c: Dict) -> str:
    tag = c.get("bet") or (c.get("record") and f"✅ {c['record']}") or ""
    top = HB.bet_chip(c["bet"]) if c.get("bet") else (
        f'<span style="color:{HB.INK_SOFT};font-size:12px;">{tag}</span>' if tag else "")
    icons = ("💰 " if c.get("money") else "") + ("🔒 " if c.get("lock") else "")
    price = c.get("price") if c.get("price") not in (None, "", "—") else ""
    ch = _chance(c.get("chance"))
    # Nov 25: an untested line pick shows no chance on the boards -- say what it is instead of a bare dash
    big = (f'<div style="color:{HB.BLUE};font-size:24px;font-weight:800;margin-top:4px;">{ch}'
           f'<span style="color:{HB.GOLD};font-size:13px;font-weight:700;"> {price}</span></div>' if ch != "—" else
           f'<div style="color:{HB.INK_SOFT};font-size:13px;margin-top:6px;">{c.get("basis") or "No chance shown"}'
           + (f'<span style="color:{HB.GOLD};font-weight:700;"> · {price}</span>' if price else "") + '</div>')
    inj = ""
    if c.get("_inj"):                                           # Nov 25: tonight's injury report says questionable
        import injury_check as IC
        inj = (f'<div style="color:{HB.GOLD};font-size:12px;font-weight:700;margin-top:3px;">'
               f'{IC.chip(c["_inj"])} — check news before betting</div>')
    return (f'<div style="min-height:132px;">{top}'
            f'<div style="color:{HB.INK};font-weight:800;font-size:15.5px;margin-top:7px;line-height:1.25;">'
            f'{icons}{c.get("pick") or ""}</div>' + inj + big +
            f'<div style="color:{HB.INK_SOFT};font-size:12px;margin-top:2px;">{c.get("game") or ""}'
            f'{" · " + c["time"] if c.get("time") else ""}</div></div>')


def _win_txt(w: Dict) -> str:
    """Nov 25 (tennis): the model's pick to win, when a game has no spread or total."""
    try:
        return f"{w['winner']} {float(w['chance']):.0%} to win" if w.get("winner") else "—"
    except (TypeError, ValueError):
        return "—"


def fight_tile_html(w: Dict) -> str:
    import game_card as GC
    g = GC.build_fight(w)
    a, b = g["fighters"]

    def px(x):
        v = GC._num(x.get("price"))
        return "—" if v is None else f"{v:+.0f}"
    fav = max(g["fighters"], key=lambda x: x.get("market") or 0)
    return (f'<div style="min-height:108px;"><div style="color:{HB.INK_SOFT};font-size:11.5px;letter-spacing:.05em;">'
            f'{g.get("time") or ""}</div><div style="color:{HB.INK};font-weight:800;font-size:14px;margin-top:3px;'
            f'line-height:1.25;">{g["game"]}</div><div style="color:{HB.GOLD};font-size:12.5px;margin-top:4px;">'
            f'{(a["name"] or "").split()[-1]} {px(a)} · {(b["name"] or "").split()[-1]} {px(b)}</div>'
            f'<div style="color:{HB.INK_SOFT};font-size:12px;">Market: {fav["name"]} '
            + ("—" if fav.get("market") is None else f'{fav["market"]:.0%}') + '</div>'
            f'<div style="margin-top:6px;">{HB.bet_chip("Info only")}</div></div>')


def game_tile_html(w: Dict) -> str:
    if w.get("sport") == "UFC":
        return fight_tile_html(w)
    import game_lines_table as GLT
    try:
        bet = GLT.bet(w)
    except Exception:                                           # noqa: BLE001
        bet = ""
    try:
        gone = GLT.started(w)
    except Exception:                                           # noqa: BLE001
        gone = False
    lines = " · ".join(x for x in (w.get("spread_txt") or "", f"O/U {w['total_txt']}" if w.get("total_txt") else "")
                       if x) or (str(w.get("lean_detail") or "").replace("market: ", "Market: ")
                                 or (f"{w['winner']} {float(w['price']):+.0f}" if w.get("winner")
                                     and isinstance(w.get("price"), (int, float)) else "No line yet"))
    return (f'<div style="min-height:108px;{"opacity:.55;" if gone else ""}">'
            f'<div style="color:{HB.INK_SOFT};font-size:11.5px;letter-spacing:.05em;">'
            f'{w.get("time") or ""}{" · started" if gone else ""}</div>'
            f'<div style="color:{HB.INK};font-weight:800;font-size:14px;margin-top:3px;line-height:1.25;">'
            f'{w.get("game") or ""}</div>'
            f'<div style="color:{HB.GOLD};font-size:12.5px;margin-top:4px;">{lines}</div>'
            f'<div style="color:{HB.BLUE_SOFT};font-size:12px;">Model: {w.get("model_txt") or w.get("best") or _win_txt(w)}</div>'
            + (f'<div style="color:{HB.INK};font-size:12px;margin-top:3px;">📏 Line pick: <b>{w["best"]}</b></div>'
               if w.get("best") and w.get("sport") not in ("SOCCER", "UFC", "TENNIS") else "")
            + f'<div style="margin-top:6px;">{HB.bet_chip(bet) if bet else ""}</div></div>')


def render(live: Sequence, rows: Sequence[Dict], winners: Sequence[Dict], day: str,
           records_for: Optional[Callable] = None, line_rows: Optional[Callable] = None,
           search_rows: Optional[Sequence[Dict]] = None) -> None:
    """The Cards view: one row per sport (busiest first), its pick cards, then its game strip."""
    import streamlit as st
    import game_card as GC
    player_dlg, game_dlg = _player_dialog, _game_dialog
    sections = []
    for s in live:
        try:
            cards = sport_cards(s.key, rows, winners, day, records_for, line_rows)
        except Exception:                                       # noqa: BLE001 -- one sport never blanks the page
            cards = []
        games = (soccer_games(day) if s.key == "SOCCER" else ufc_bouts(day) if s.key == "UFC"
                 else games_for(winners, s.key))
        if cards or games:
            sections.append((s, cards, games))
    if not sections:
        st.info("No games or picks on today's boards yet. Boards fill in through the day as the books post lines.")
        return
    sections.sort(key=lambda x: (-len(x[1]), -len(x[2])))
    try:
        _search_and_favorites(list(rows or []) + list(search_rows or []), player_dlg)
    except Exception:                                           # noqa: BLE001 -- extras never blank the page
        pass
    keys = {s.key for s in live}
    try:                                                        # Nov 25 (second PropSeason pass): two strips
        _moves_strip([w for w in winners or [] if w.get("sport") in keys], game_dlg, rows)
    except Exception:                                           # noqa: BLE001
        pass
    try:
        _streaks_strip([r for r in list(rows or []) + list(search_rows or []) if r.get("sport") in keys], player_dlg)
    except Exception:                                           # noqa: BLE001
        pass
    for s, cards, games in sections:
        with st.container(border=True):
            st.markdown(f"#### {s.icon} {s.key}  \n<span style='opacity:.7'>{len(games)} {'fight' if s.key == 'UFC' else 'game'}"
                        f"{'s' if len(games) != 1 else ''} today</span>", unsafe_allow_html=True)
            if cards:
                for i, (col, c) in enumerate(zip(st.columns(CARDS_PER_SPORT), cards)):
                    with col.container(border=True):
                        st.markdown(pick_card_html(c), unsafe_allow_html=True)
                        if st.button("Open →", key=f"tv_card_{s.key}_{i}", width="stretch",
                                     help="Open this pick's player card" if c.get("kind") == "Prop"
                                     else "Open this game's card"):
                            if c.get("kind") == "Prop":
                                row = prop_row_for(rows, c)
                                if row is not None:
                                    player_dlg(row, s.key)
                                else:
                                    st.toast("That player's card isn't on the saved board yet.")
                            else:
                                w = GC.for_game(list(winners or []) + list(games if s.key == "SOCCER" else []),
                                                c.get("game"))
                                if w is not None and w.get("sport") == "SOCCER":
                                    game_dlg(w, soccer_flags(day))
                                elif w is not None:
                                    game_dlg(w, props_in_game(rows, w))
                                else:                           # Nov 25: never a dead end -- the pick's own facts
                                    _basic_dialog(dict(c, sport=s.key))
            else:
                st.caption("H2 has no UFC model yet — tonight's card at market odds. Open a fight for the odds."
                           if s.key == "UFC" else "No pick clears the bar here yet. Open a game below for the model's "
                           "read.")
            if games:
                st.markdown(f"<div style='color:{HB.INK_SOFT};font-size:12.5px;margin:6px 0 2px;letter-spacing:.05em;'>"
                            f"{'FIGHTS' if s.key == 'UFC' else 'GAMES'} · EARLIEST FIRST</div>", unsafe_allow_html=True)
                shown = games[:STRIP_MAX]
                for start in range(0, len(shown), 4):
                    cols = st.columns(4)
                    for j, w in enumerate(shown[start:start + 4]):
                        with cols[j].container(border=True):
                            st.markdown(game_tile_html(w), unsafe_allow_html=True)
                            if st.button("Game card →", key=f"tv_game_{s.key}_{start + j}", width="stretch"):
                                game_dlg(w, soccer_flags(day) if w.get("sport") == "SOCCER"
                                         else props_in_game(rows, w))
                if len(games) > STRIP_MAX:
                    st.caption(f"{len(games) - STRIP_MAX} more {s.key} games under **Games** in the sidebar, or "
                               "switch to **Table** above.")


def pick_text(r: Dict) -> str:
    """The pick without the player's name in front ("Tre Jones Pts+Reb+Ast Under 22.5" -> "Pts+Reb+Ast Under 22.5")."""
    pick, name = str(r.get("pick") or ""), player_of(r)
    return pick[len(name):].strip() if name and pick.startswith(name) else pick


def search_options(rows: Sequence[Dict]) -> List[Dict]:
    """Every player pick on today's boards, one per player and market, A to Z by player."""
    seen, out = set(), []
    for r in rows or []:
        if r.get("kind") != "Prop" or not player_of(r):
            continue
        k = (r.get("sport"), player_of(r), r.get("market") or r.get("pick"))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return sorted(out, key=lambda r: player_of(r).lower())


def _open_search():
    _st.session_state["tv_search_open"] = True


def _search_and_favorites(rows: Sequence[Dict], player_dlg) -> None:
    import streamlit as st
    opts = search_options(rows)
    if not opts:
        return
    c1, c2 = st.columns([3, 2])
    with c1:
        i = st.selectbox(f"🔎 Find a player tonight ({len(opts)} picks)", [None] + list(range(len(opts))),
                         key="tv_search", on_change=_open_search,
                         format_func=lambda i: "Type a name…" if i is None else
                         f"{player_of(opts[i])} — {pick_text(opts[i])} ({opts[i].get('sport')}, "
                         f"{opts[i].get('time') or ''})")
    if i is not None and st.session_state.pop("tv_search_open", False):
        player_dlg(opts[i], opts[i].get("sport") or "")
    favs = favorites()
    mine = [r for r in opts if player_of(r) in favs]
    with c2:
        st.caption(f"⭐ {len(favs)} favorite player{'s' if len(favs) != 1 else ''}"
                   + (f" · {len(mine)} pick{'s' if len(mine) != 1 else ''} tonight" if favs else
                      " — open any player card and tap ⭐ Favorite to pin him here."))
    if mine:
        with st.container(border=True):
            st.markdown("#### ⭐ Your players tonight")
            for start in range(0, min(len(mine), 8), 4):
                cols = st.columns(4)
                for j, r in enumerate(mine[start:start + 4]):
                    c = {"pick": r.get("pick"), "chance": r.get("chance"), "price": r.get("price"),
                         "game": r.get("game"), "time": r.get("time"), "money": r.get("money"), "lock": r.get("lock")}
                    with cols[j].container(border=True):
                        st.markdown(pick_card_html(c), unsafe_allow_html=True)
                        if st.button("Open →", key=f"tv_fav_{start + j}", width="stretch"):
                            player_dlg(r, r.get("sport") or "")



# --------------------------------------------------------------------------- line moves and streaks (Nov 25)
MOVE_MIN = 1.0


def line_moves(winners: Sequence[Dict], n: int = 8) -> List[Dict]:
    """Today's biggest spread moves (open -> now, 1+ point), biggest first: {"w", "size", "text", "our_way"}."""
    out = []
    for w in winners or []:
        p = w.get("_full") or {}
        try:
            o, l = float(p["open_line"]), float(p["line"])
        except (TypeError, ValueError, KeyError):
            continue
        if abs(l - o) < MOVE_MIN:
            continue
        # line = the market's expected home margin, so the home spread is its negative
        text = w.get("spread_move_why") or f"{p.get('home')} {-o:+g} → {-l:+g}"
        out.append({"w": w, "size": abs(l - o), "text": text,
                    "our_way": None if not w.get("spread_move") else w["spread_move"].startswith("📈")})
    return sorted(out, key=lambda m: -m["size"])[:n]


def streak(values: Sequence[float], line, side: str) -> int:
    """How many games in a row, newest first, the player cleared tonight's line for the pick's side."""
    import player_card as PC
    try:
        ln = float(line)
    except (TypeError, ValueError):
        return 0
    k = 0
    for v in values or []:
        if v is None or not PC.cleared(float(v), ln, side):
            break
        k += 1
    return k


def hot_streaks(rows: Sequence[Dict], min_len: int = 5, n: int = 8) -> List[Dict]:
    """Players on a run against tonight's line (5+ straight), longest first, one per player and market."""
    seen, out = set(), []
    for r in rows or []:
        if r.get("kind") != "Prop" or r.get("side") not in ("Over", "Under") or r.get("line") is None:
            continue
        k = (r.get("sport"), player_of(r), r.get("market"), r.get("side"))
        if k in seen:
            continue
        seen.add(k)
        st_ = streak(r.get("values") or [], r.get("line"), r["side"])
        if st_ >= min_len:
            out.append(dict(r, _streak=st_, _of=len(r.get("values") or [])))
    return sorted(out, key=lambda r: (-r["_streak"], -(r.get("chance") or 0)))[:n]


def _moves_strip(winners: Sequence[Dict], game_dlg, rows) -> None:
    import streamlit as st
    mv = line_moves(winners)
    if not mv:
        return
    st.markdown(f"#### 📈 Biggest line moves today")
    st.caption("The spread from its opening number to now. 📈 = moving toward the side the model likes (books agreeing "
               "with it); 📉 = away from it. Context, not a pick — tap a game for the full read.")
    for start in range(0, min(len(mv), 8), 4):
        cols = st.columns(4)
        for j, m in enumerate(mv[start:start + 4]):
            w = m["w"]
            arrow = "" if m["our_way"] is None else ("📈 toward the model" if m["our_way"] else "📉 away from the model")
            with cols[j].container(border=True):
                st.markdown(f'<div style="min-height:92px;"><div style="color:{HB.INK_SOFT};font-size:11.5px;">'
                            f'{w.get("sport")} · {w.get("time") or ""}</div><div style="color:{HB.INK};font-weight:800;'
                            f'font-size:13.5px;margin-top:2px;line-height:1.25;">{w.get("game")}</div>'
                            f'<div style="color:{HB.GOLD};font-size:13px;font-weight:700;margin-top:4px;">{m["text"]}'
                            f'</div><div style="color:{HB.INK_SOFT};font-size:12px;">moved {m["size"]:g} pts'
                            f'{" · " + arrow if arrow else ""}</div></div>', unsafe_allow_html=True)
                if st.button("Game card →", key=f"tv_move_{start + j}", width="stretch"):
                    game_dlg(w, props_in_game(rows, w))


def _streaks_strip(rows: Sequence[Dict], player_dlg) -> None:
    import streamlit as st
    import game_previews as GP
    hs = hot_streaks(rows)
    if not hs:
        return
    st.markdown("#### 🔥 Hot streaks against tonight's line")
    st.caption("Players who cleared tonight's exact line for this side in 5+ straight games. A streak is context, not a "
               "reason by itself: each card shows the model's earned chance and whether it's a bet.")
    for start in range(0, len(hs), 4):
        cols = st.columns(4)
        for j, r in enumerate(hs[start:start + 4]):
            use = ("💰 " if r.get("money") else "") + ("🔒 " if r.get("lock") else "") + str(r.get("use") or "")
            bet = GP.prop_bet(r.get("sport") or "", use, r)
            ch = r.get("chance")
            with cols[j].container(border=True):
                st.markdown(f'<div style="min-height:118px;">{HB.bet_chip(bet)}<div style="color:{HB.INK};font-weight:800;'
                            f'font-size:14.5px;margin-top:6px;line-height:1.25;">{r.get("pick")}</div>'
                            f'<div style="color:{HB.GOLD};font-size:13px;font-weight:700;margin-top:3px;">🔥 '
                            f'{r["_streak"]} straight</div><div style="color:{HB.INK_SOFT};font-size:12px;">'
                            + ("" if ch is None else f"earned chance {float(ch):.0%} · ")
                            + f'{r.get("sport")} · {r.get("time") or ""}</div></div>', unsafe_allow_html=True)
                if st.button("Open →", key=f"tv_streak_{start + j}", width="stretch"):
                    player_dlg(r, r.get("sport") or "")
