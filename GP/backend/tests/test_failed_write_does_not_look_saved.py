"""A write that fails must not leave the officer's decision looking recorded.

Audit of 13 October 2026, H-17, both halves.

The service mutated the case in memory and persisted afterwards, with no rollback. A write
that raised gave the caller a 500 while every later read went on showing the disposal, the
waiver and the verification -- until the next restart, when they were gone, because memory is
rebuilt from gpf_cases. An officer who saw an error, looked again, and found their decision
there would reasonably conclude it had gone in. It had not.

Ordering the two was not enough on its own: get() hands back the stored object and the service
mutates it in place, so the change is already in memory before save() is reached. Memory is
reloaded from the database on failure, which is the only state that really exists.

The other half: the module holds one connection opened at import and never reopened, so a
PostgreSQL restart broke every GP Fund write permanently until someone restarted the service.
One retry on a fresh connection, then the error goes to the caller.

    pytest tests/test_failed_write_does_not_look_saved.py
"""
import sqlite3

import pytest

from gpf.engine import CaseState
from gpf.store import DbCaseRepository


@pytest.fixture
def repo(tmp_path):
    return DbCaseRepository(tmp_path / "gpf.sqlite3")


def _case(label="first"):
    return CaseState(k="refundable", F={"kind": "refundable", "note": label}, without_sap=False)


class TestAFailedWriteIsAFailure:
    def test_the_change_is_not_visible_afterwards(self, repo, monkeypatch):
        repo.save("c1", _case("first"))
        assert repo.get("c1").F["note"] == "first"

        # The officer's second decision, against a database that refuses it.
        s = repo.get("c1")
        s.F["note"] = "second"                        # mutated in place, as the service does
        monkeypatch.setattr(repo, "_write", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
        with pytest.raises(sqlite3.OperationalError):
            repo.save("c1", s)

        assert repo.get("c1").F["note"] == "first", \
            "the failed decision is still being shown as recorded"

    def test_a_successful_write_is_still_visible(self, repo):
        repo.save("c2", _case("first"))
        s = repo.get("c2")
        s.F["note"] = "second"
        repo.save("c2", s)
        assert repo.get("c2").F["note"] == "second"

    def test_memory_matches_the_database_after_a_failure(self, repo, monkeypatch):
        """Not just 'the old value' -- the value the table actually holds."""
        repo.save("c3", _case("first"))
        s = repo.get("c3")
        s.F["note"] = "second"
        monkeypatch.setattr(repo, "_write", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
        with pytest.raises(RuntimeError):
            repo.save("c3", s)
        row = repo.conn.execute("SELECT state_json FROM gpf_cases WHERE id = ?", ("c3",)).fetchone()
        import json
        assert json.loads(row["state_json"])["F"]["note"] == repo.get("c3").F["note"]


class TestADroppedConnectionIsReopened:
    def test_one_retry_on_a_fresh_connection(self, repo, monkeypatch):
        """A PostgreSQL restart used to break every write until the service was restarted."""
        calls = {"n": 0}
        real = repo.conn

        class _Dead:
            def execute(self, *a, **k):
                calls["n"] += 1
                raise sqlite3.OperationalError("server closed the connection unexpectedly")

        repo.conn = _Dead()
        monkeypatch.setattr("gpf.store.dbcore.connect", lambda *a, **k: real)
        repo.save("c4", _case("after a restart"))
        assert calls["n"] == 1, "it should have tried the dead connection once, then reconnected"
        assert repo.get("c4").F["note"] == "after a restart"

    def test_it_does_not_spin_when_the_database_is_really_down(self, repo, monkeypatch):
        """One retry, not a loop: the caller has to hear that the database is gone."""
        class _Dead:
            def execute(self, *a, **k):
                raise sqlite3.OperationalError("connection refused")

        repo.conn = _Dead()
        monkeypatch.setattr("gpf.store.dbcore.connect", lambda *a, **k: _Dead())
        with pytest.raises(sqlite3.OperationalError):
            repo.save("c5", _case())
