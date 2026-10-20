"""Test-suite wide guards.

A test must not write into the live installation. The call log (pipeline/timing.py) puts a
run's calls in ``<run root>/artifacts/run-<id>/calls.jsonl``, and the run root defaults to the
installation root -- so any test that binds a run id writes a directory into
/var/lib/pension/artifacts next to real cases. tests/test_run_timings.py was given its own
redirect when the log was added on 20 Oct 2026; tests/test_audit_fixes_13oct.py was not, and
left run-r-no-db in the live artefacts directory on the next full run.

Patching each suite that happens to bind a run id is the wrong shape -- the next one to do it
will leak again, and nothing will say so. The redirect belongs here, where importing anything
under tests/ picks it up. A suite that wants its own root still sets PENSION_RUN_ROOT itself
and wins, because this only fills in a value that is not already there.
"""
from __future__ import annotations

import atexit
import os
import tempfile

if not os.environ.get("PENSION_RUN_ROOT"):
    _run_root = tempfile.mkdtemp(prefix="pension-tests-")
    os.environ["PENSION_RUN_ROOT"] = _run_root

    @atexit.register
    def _clean_run_root() -> None:
        import shutil
        shutil.rmtree(_run_root, ignore_errors=True)
