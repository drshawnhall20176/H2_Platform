"""
deploy_reload.py -- pick up newly deployed code without a restart (Nov 27).

Streamlit Cloud pulls each merge into the running app, and the page scripts rerun with the new code -- but the
platform's own modules (model_store, live_games, today_visual ...) stay as they were first imported. A module that
changed is only half-swapped: other modules still hold the old copy (`import model_store as MS` at their top), so a
new page could call a function the old copy doesn't have. That is why every deploy has needed "tap restart" and why
new code carries getattr / hasattr guards.

check(), called by streamlit_app.py at the start of every run: at most every CHECK_EVERY seconds it looks at the
newest .py file in the project. When the code on disk has changed since the last look, every project module is
dropped from sys.modules at once (not just the changed ones), so the next imports load one consistent new copy --
the same as a restart for the code, without dropping anyone's session or the data caches. Never raises.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
CHECK_EVERY = 20.0
# install-once patches and this module itself stay as they are
KEEP = {"deploy_reload", "cache_guard", "table_style", "conftest", "__main__"}
_STATE: Dict = {"stamp": None, "last": 0.0, "reloads": 0}


def stamp(root: Path = ROOT) -> Tuple[float, int]:
    """(newest mtime, file count) over the project's .py files (top level and views/)."""
    newest, n = 0.0, 0
    for d in (root, root / "views"):
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.name.endswith(".py"):
                        n += 1
                        try:
                            newest = max(newest, e.stat().st_mtime)
                        except OSError:
                            pass
        except OSError:
            continue
    return newest, n


def project_modules(modules: Optional[Dict] = None, root: Path = ROOT) -> List[str]:
    """Names of loaded modules whose file is in the project folder (not packages installed elsewhere)."""
    out = []
    r = str(root)
    for name, mod in list((modules if modules is not None else sys.modules).items()):
        f = getattr(mod, "__file__", None)
        if not f or name in KEEP or name.split(".")[0] in KEEP or name.startswith("test_"):
            continue
        try:
            p = str(Path(f).resolve())
        except (OSError, RuntimeError):
            continue
        if p.startswith(r + os.sep) and "site-packages" not in p:
            out.append(name)
    return out


def check(now: Optional[float] = None, stamp_fn: Callable = stamp, modules: Optional[Dict] = None,
          log: Callable = print) -> bool:
    """True when new code was found and the project modules were dropped for a fresh import."""
    try:
        now = time.time() if now is None else now
        if now - _STATE["last"] < CHECK_EVERY:
            return False
        _STATE["last"] = now
        s = stamp_fn()
        if _STATE["stamp"] is None:
            _STATE["stamp"] = s
            return False
        if s == _STATE["stamp"]:
            return False
        _STATE["stamp"] = s
        mods = modules if modules is not None else sys.modules
        names = project_modules(mods)
        for n in names:
            mods.pop(n, None)
        _STATE["reloads"] += 1
        log(f"[deploy_reload] new code on disk: {len(names)} modules will load fresh (reload {_STATE['reloads']})")
        return True
    except Exception:                                           # noqa: BLE001 -- never costs a page
        return False
