"""
keep_warm.py -- open the site like a visitor, so it stays awake and its caches are full (Nov 26, owner: "need to check
the speed on the initial load of the site").

Measured Nov 26: a visit to a running site with warm caches shows Today in ~1 s and the whole page in ~4 s; the first
visitor after a restart or an hour's cache expiry waited 11-21 s, and a site Streamlit has put to sleep shows a wake-up
screen first. A headless browser opening Today a few minutes after each hourly board build makes that first visitor
this job instead of a member. Prints timings only.

    python keep_warm.py [URL]
"""
from __future__ import annotations

import sys
import time

import os

# The members' (public) site: the owner site is private on Streamlit -- a bot visit there gets "You do not have access
# to this app" (Nov 26), and it is never signed in with anyone's credentials. The members' site is public (owner,
# Nov 26); PUBLIC_APP_URL overrides it.
PUBLIC = "https://h2discorduser.streamlit.app/"
URL = os.environ.get("PUBLIC_APP_URL", "").strip() or PUBLIC
WAKE_TEXT = ("get this app back up", "Yes, get this app back up")
DONE_TEXT = ("GAMES · EARLIEST", "No pick clears the bar", "Player picks today", "PLAYER PICKS TODAY")
# Nov 28: after Today, the pages whose first load is slowest (measured cold: Pick'em 56 s, All picks 51 s). Their
# caches are shared by every visitor, so one bot visit after each board build makes them quick for members.
_BB_DONE = ("How 'best' is defined", "No play", "No picks")
EXTRA = (("pickem_board", ("lines read", "isn't carrying", "lines to read")),
         ("best_bets?sport=NBA", _BB_DONE), ("best_bets?sport=NCAAMB", _BB_DONE), ("best_bets?sport=NCAAF", _BB_DONE))


def page_text(page) -> str:
    out = []
    for fr in page.frames:
        try:
            out.append(fr.inner_text("body", timeout=2000))
        except Exception:                                       # noqa: BLE001
            pass
    return "\n".join(out)


def visit(url: str = URL, wait_s: int = 180) -> dict:
    from playwright.sync_api import sync_playwright
    t0 = time.time()
    marks = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=120000)
        while time.time() - t0 < wait_s:
            txt = page_text(page)
            if "woke" not in marks and any(w.lower() in txt.lower() for w in WAKE_TEXT):
                marks["asleep"] = round(time.time() - t0, 1)
                try:
                    page.get_by_role("button", name="Yes, get this app back up!").click(timeout=5000)
                except Exception:                               # noqa: BLE001
                    try:
                        page.get_by_text("get this app back up").first.click(timeout=5000)
                    except Exception:                           # noqa: BLE001
                        pass
                marks["woke"] = round(time.time() - t0, 1)
            if "Today ·" in txt and "today" not in marks:
                marks["today"] = round(time.time() - t0, 1)
            if any(d in txt for d in DONE_TEXT):
                marks["done"] = round(time.time() - t0, 1)
                break
            time.sleep(1)
        time.sleep(5)                                           # let the last cached loads finish
        if "done" in marks:
            for path, done in EXTRA:
                marks[path] = warm_page(page, url.rstrip("/") + "/" + path, done)
        if "done" not in marks:                                 # say what it saw instead (no picks are printed)
            marks["frames"] = [(fr.url[:80]) for fr in page.frames]
            marks["saw"] = " | ".join(page_text(page).split("\n")[:12])[:400]
        b.close()
    marks["total"] = round(time.time() - t0, 1)
    return marks


def warm_page(page, url: str, done, wait_s: int = 100):
    """Open one more page in the same browser; seconds until it shows one of `done`, or None. Never raises."""
    t0 = time.time()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)                                           # let Streamlit swap out the previous page
        while time.time() - t0 < wait_s:
            if any(d in page_text(page) for d in done):
                return round(time.time() - t0, 1)
            time.sleep(1)
    except Exception:                                           # noqa: BLE001
        pass
    return None


def visit_pickem(url: str = URL) -> dict:
    """Nov 28 (owner: speed on a big college Saturday): just the Pick'em board, every 10 minutes (warm-pickem.yml) --
    its lines are saved for 10 minutes, so a visit this often keeps a member's first open quick. Opening the board
    (not the site's Today) is enough: its loads are the shared caches."""
    from playwright.sync_api import sync_playwright
    t0 = time.time()
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        secs = warm_page(page, url.rstrip("/") + "/" + EXTRA[0][0], EXTRA[0][1], wait_s=150)
        b.close()
    return {"pickem_board": secs, "total": round(time.time() - t0, 1)}


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    pickem_only = "--pickem" in argv
    argv = [a for a in argv if a != "--pickem"]
    url = argv[0] if argv else URL
    if not url:
        print("keep-warm: PUBLIC_APP_URL isn't set -- nothing to visit (the owner site is private)")
        return 0
    if pickem_only:
        m = visit_pickem(url)
        print("keep-warm (pick'em):", m)
        return 0 if m.get("pickem_board") is not None else 1
    m = visit(url)
    print("keep-warm:", m)
    return 0 if "done" in m else 1


if __name__ == "__main__":
    sys.exit(main())
