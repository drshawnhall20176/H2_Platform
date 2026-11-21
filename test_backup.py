"""Nov 21: the nightly backup (backup.py) round-trips through its file."""
import gzip
import json

import backup as BK


def test_write_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr(BK, "dump", lambda today=None: {"day": "2026-11-21", "tables": {"bets": [{"id": 1}],
                                                                                         "app_settings": []}})
    p = BK.write(str(tmp_path))
    assert p.endswith("h2-backup-2026-11-21.json.gz")
    assert BK.read(p)["tables"]["bets"] == [{"id": 1}]


def test_restore_dry_run_counts(tmp_path):
    p = tmp_path / "b.json.gz"
    with gzip.open(p, "wt") as f:
        json.dump({"tables": {"bets": [{"id": 1}, {"id": 2}]}}, f)
    assert BK.restore(str(p), "bets") == 2
