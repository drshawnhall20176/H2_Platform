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

URL = "https://h2ownersplatform.streamlit.app/"
WAKE_TEXT = ("get this app back up", "Yes, get this app back up")
DONE_TEXT = ("GAMES · EARLIEST", "No pick clears the bar", "Player picks today", "PLAYER PICKS TODAY")


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
        b.close()
    marks["total"] = round(time.time() - t0, 1)
    return marks


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    m = visit(argv[0] if argv else URL)
    print("keep-warm:", m)
    return 0 if "done" in m else 1


if __name__ == "__main__":
    sys.exit(main())
