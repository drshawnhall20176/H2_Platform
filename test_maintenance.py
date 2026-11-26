"""Nov 21: the restart button (Maintenance.py) -- shut without its secret, clears caches with it."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

PAGE = str(Path(__file__).parent / "Maintenance.py")


def test_shut_without_the_secret():
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.run()
    assert not at.exception
    assert any("isn't set up" in i.value for i in at.info)
    assert not at.button or all("Restart" not in b.label for b in at.button)


def test_wrong_password_then_restart():
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.secrets["MAINT_PASSWORD"] = "fix"
    at.run()
    at.text_input(key="maint_pw").input("nope")
    at.button[0].click().run()
    assert at.error
    at.text_input(key="maint_pw").input("fix")
    at.button[0].click().run()
    assert not at.exception
    btn = next(b for b in at.button if "Restart the site now" in b.label)
    btn.click().run()
    assert not at.exception and at.success



def test_restart_drops_only_the_sites_own_modules():
    import types
    src = open(PAGE).read()
    ns = {"__file__": PAGE}
    exec(src[src.index("def drop_site_modules"):src.index("\n\n\nnote = ")], ns)
    here = str(Path(PAGE).parent)

    def mod(name, f):
        m = types.ModuleType(name)
        m.__file__ = f
        return m
    mods = {"sports": mod("sports", here + "/sports.py"), "pandas": mod("pandas", "/usr/lib/site-packages/pandas/x.py"),
            "venv_lib": mod("venv_lib", here + "/venv/lib/site-packages/x.py"), "__main__": mod("__main__", PAGE)}
    assert ns["drop_site_modules"](mods, here) == 1
    assert set(mods) == {"pandas", "venv_lib", "__main__"}
