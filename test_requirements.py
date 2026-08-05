"""
test_requirements.py — guards against a real, confirmed class of deploy break: a transitive
dependency of a pinned package quietly resolving to a newer, incompatible version between two
deploys with no other change in this repo.

Real, confirmed incident this guards against directly: streamlit==1.59.1 was unchanged between a
working deploy on 2026-08-03 (starlette auto-resolved to 1.3.1) and a broken one on 2026-08-05
(starlette auto-resolved to 1.4.0) — 1.4.0's own GZip middleware started requiring a real new
keyword-only argument streamlit 1.59.1's own internal call site doesn't pass, and the app
couldn't even start (500 on every health check, confirmed directly from the real deploy log,
before a single line of this platform's own code ever ran).

    python test_requirements.py    # or: pytest test_requirements.py
"""

from pathlib import Path

_HERE = Path(__file__).parent


def test_starlette_stays_explicitly_pinned():
    # The real, confirmed fix: streamlit's own transitive dependency on starlette must stay
    # pinned to a real, known-working version, not left to auto-resolve to whatever's newest at
    # install time -- same real reasoning this file's own header already documents for pyarrow/
    # matplotlib after an earlier real incident.
    text = (_HERE / "requirements.txt").read_text()
    lines = [l.split("#")[0].strip() for l in text.splitlines()]
    assert "starlette==1.3.1" in lines, (
        "starlette must stay explicitly pinned in requirements.txt -- an unpinned transitive "
        "dependency of streamlit already caused one real, confirmed production outage (2026-08-05)")
    print("✓ starlette stays explicitly pinned, preventing the exact class of transitive-dependency "
         "break that already caused one real deploy outage")


def test_requirements_has_no_duplicate_pins():
    # A real, simple sanity check -- two conflicting pins for the same real package would mean
    # pip installs whichever one happens to resolve last, silently, not a real, intended version.
    text = (_HERE / "requirements.txt").read_text()
    names = []
    for line in text.splitlines():
        stripped = line.split("#")[0].strip()
        if not stripped or "==" not in stripped:
            continue
        names.append(stripped.split("==")[0].strip())
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate real pins found for: {dupes}"
    print("✓ requirements.txt has no duplicate real package pins")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
