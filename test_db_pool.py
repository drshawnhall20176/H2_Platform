"""Nov 17: Postgres connections are pooled and the schema runs once per process."""
import betlog as B


class FakeCur:
    def __init__(self, log, fail=False): self.log, self.fail = log, fail
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, q, *a):
        if self.fail: raise RuntimeError("gone")
        self.log.append(q[:20])


class FakeCon:
    def __init__(self, log): self.log, self.closed, self.dead = log, 0, False
    def cursor(self, **k): return FakeCur(self.log, self.dead)
    def commit(self): self.log.append("commit")
    def rollback(self): self.log.append("rollback")
    def close(self): self.closed = 1


def test_pool_reuses_connections_and_runs_schema_once(monkeypatch):
    log, made = [], []
    monkeypatch.setattr(B, "_PG_POOL", [])
    monkeypatch.setattr(B, "_PG_SCHEMA_DONE", False)
    monkeypatch.setattr(B, "_pg_new_connection", lambda: made.append(FakeCon(log)) or made[-1])
    for _ in range(3):
        with B._pg_conn() as con:
            con.cursor().execute("SELECT x")
    assert len(made) == 1                                    # one connection, reused
    assert sum(1 for q in log if q.startswith("\nCREATE") or "CREATE TABLE" in q) <= 1


def test_dead_idle_connection_is_replaced(monkeypatch):
    log, made = [], []
    dead = FakeCon(log); dead.dead = True
    monkeypatch.setattr(B, "_PG_POOL", [(dead, 0.0)])         # idle since the epoch -> checked
    monkeypatch.setattr(B, "_PG_SCHEMA_DONE", True)
    monkeypatch.setattr(B, "_pg_new_connection", lambda: made.append(FakeCon(log)) or made[-1])
    with B._pg_conn() as con:
        assert con is made[0]
    assert dead.closed


def test_error_rolls_back_and_keeps_pool_usable(monkeypatch):
    log, made = [], []
    monkeypatch.setattr(B, "_PG_POOL", [])
    monkeypatch.setattr(B, "_PG_SCHEMA_DONE", True)
    monkeypatch.setattr(B, "_pg_new_connection", lambda: made.append(FakeCon(log)) or made[-1])
    try:
        with B._pg_conn():
            raise ValueError("boom")
    except ValueError:
        pass
    assert "rollback" in log and len(B._PG_POOL) == 1
