"""Nov 27: new code on disk drops every project module at once, so the next imports load one fresh copy."""
import types

import deploy_reload as DR


def _mods(tmp_path):
    a = types.ModuleType("model_store"); a.__file__ = str(tmp_path / "model_store.py")
    b = types.ModuleType("cache_guard"); b.__file__ = str(tmp_path / "cache_guard.py")
    c = types.ModuleType("pandas"); c.__file__ = "/usr/lib/python3/site-packages/pandas/__init__.py"
    return {"model_store": a, "cache_guard": b, "pandas": c}


def test_drops_project_modules_only_when_the_code_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(DR, "ROOT", tmp_path)
    monkeypatch.setattr(DR, "_STATE", {"stamp": None, "last": 0.0, "reloads": 0})
    mods = _mods(tmp_path)
    stamps = iter([(1.0, 5), (1.0, 5), (2.0, 5)])
    logs = []
    kw = dict(stamp_fn=lambda: next(stamps), modules=mods, log=logs.append)
    orig = DR.project_modules
    monkeypatch.setattr(DR, "project_modules", lambda m: orig(m, tmp_path))
    assert DR.check(now=100, **kw) is False                     # first look: just remember
    assert DR.check(now=110, **kw) is False                     # throttled
    assert DR.check(now=130, **kw) is False and "model_store" in mods   # same code
    assert DR.check(now=160, **kw) is True
    assert set(mods) == {"cache_guard", "pandas"} and "1 modules" in logs[0]


def test_stamp_sees_a_new_file(tmp_path):
    (tmp_path / "a.py").write_text("x = 1")
    s1 = DR.stamp(tmp_path)
    (tmp_path / "views").mkdir()
    (tmp_path / "views" / "b.py").write_text("y = 1")
    assert DR.stamp(tmp_path) != s1
