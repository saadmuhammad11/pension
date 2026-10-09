"""The pension tree's database engine shim, loaded by file so this module stays its own process.

``api/dbcore.py`` at the top of the pension tree knows how to open PostgreSQL (through the
vendored psycopg) or a SQLite file and hand back the same kind of connection and rows. The GP
Fund module keeps its cases in the same database (gpf/store.py) and writes its timings to the same
table (gpf/reading/timing.py), so it uses the same shim -- loaded here by path, the way
store.py already reaches that tree's migration file, rather than by importing the ``api`` package.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PENSION_ROOT = Path(__file__).resolve().parents[3]
DBCORE_PATH = PENSION_ROOT / "api" / "dbcore.py"


def _load():
    if "api.dbcore" in sys.modules:                   # the pension API itself, in-process (tests, bench)
        return sys.modules["api.dbcore"]
    spec = importlib.util.spec_from_file_location("gpf._dbcore", DBCORE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the database shim from {DBCORE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gpf._dbcore"] = mod
    spec.loader.exec_module(mod)
    return mod


dbcore = _load()
