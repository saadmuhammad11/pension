"""Specimen signatures from the shared master store, for the "Signatories and delegation of
authority" task (scope change C1, 9 Oct 2026).

The pension API keeps one store of signing authorities and their specimens in the shared database
(``signing_authorities`` / ``signatory_specimens``, migration 0013 in the pension tree,
``api/signatories.py``). This module reads it through the module's own connection (``gpf.store``,
PostgreSQL or the SQLite file) and answers: for the department a document is issued for and the
post that signed it, which specimens are on file, in force on the document's date. Nothing here
compares a signature: the specimens are put beside the signature as read, for the officer.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date
from pathlib import Path
from typing import Any, Optional

_lock = threading.Lock()
_conn: Any = None

#: S&GAD as a scan reads it: "S&GAD", "S & G A D", "S and GAD", the ampersand misread as R or 8.
_SGAD = re.compile(r"(?i)\bs\s*(?:&|and|r|8)?\s*g\s*\.?\s*a\s*\.?\s*d\b")


def set_connection(conn: Any) -> None:
    """The repository's connection, shared read-only here (set by gpf.api at start-up)."""
    global _conn
    _conn = conn


def _key(text: Optional[str]) -> str:
    t = _SGAD.sub(" sgad ", text or "").lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


def _mentions(text: Optional[str], names: list[str]) -> bool:
    hay = f" {_key(text)} "
    squashed = hay.replace(" ", "")
    for name in names:
        k = _key(name)
        if not k:
            continue
        if f" {k} " in hay or (len(k.replace(" ", "")) >= 4 and k.replace(" ", "") in squashed):
            return True
    return False


def _tables_present(conn: Any) -> bool:
    try:
        from .dbshim import dbcore
        return {"signing_authorities", "signatory_specimens"} <= dbcore.table_names(conn)
    except Exception:                                 # noqa: BLE001
        return False


def specimens_for(department: Optional[str], post: Optional[str], on: Optional[date] = None,
                  conn: Any = None) -> dict:
    """``{"authority": {...}|None, "specimens": [{"id", "url"}], "message": str|None}``.

    The authority is matched by the department's name or aliases and the post's name or aliases,
    among GP Fund (or BOTH) entries in force on ``on`` (today when the document carries no date);
    closed entries are no match. ``message`` is "No specimen on file for <department>, <post>"
    when nothing usable is on file.
    """
    conn = conn or _conn
    none = {"authority": None, "specimens": [], "message": f"No specimen on file for {department or 'this department'}, {post or 'this post'}"}
    if conn is None or not department or not _tables_present(conn):
        return none
    when = (on or date.today()).isoformat()
    try:
        with _lock:
            rows = conn.execute(
                "SELECT * FROM signing_authorities WHERE (product_scope = 'GPF' OR product_scope = 'BOTH') "
                "AND closed_at IS NULL AND effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?) "
                "ORDER BY effective_from", (when, when)).fetchall()
            rows = [dict(r) for r in rows]
            matches = []
            for r in rows:
                dept_names = [r["department_name"], r.get("department_code") or "", *json.loads(r.get("department_aliases_json") or "[]")]
                if not _mentions(department, dept_names):
                    continue
                if post and not _mentions(post, [r["post"], *json.loads(r.get("post_aliases_json") or "[]")]):
                    continue
                matches.append(r)
            if not matches:
                return none
            best = matches[-1]
            specs = [dict(s) for s in conn.execute(
                "SELECT id, stored_path FROM signatory_specimens WHERE authority_id = ? ORDER BY uploaded_at, id", (best["id"],))]
    except Exception:                                 # noqa: BLE001 -- the task stands without the store
        return none
    authority = {"id": best["id"], "department": best["department_name"], "post": best["post"],
                 "officer": best.get("officer_name") or "", "provisional": bool(best.get("provisional"))}
    if not specs:
        return {"authority": authority, "specimens": [],
                "message": f"No specimen on file for {best['department_name']}, {best['post']}"}
    return {"authority": authority, "message": None,
            "specimens": [{"id": s["id"], "url": f"api/signatories/{s['id']}/image"} for s in specs]}


def specimen_path(spec_id: str, conn: Any = None) -> Optional[Path]:
    conn = conn or _conn
    if conn is None or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", spec_id or "") or not _tables_present(conn):
        return None
    with _lock:
        r = conn.execute("SELECT stored_path FROM signatory_specimens WHERE id = ?", (spec_id,)).fetchone()
    if r is None:
        return None
    p = Path(r[0])
    return p if p.is_file() else None


def mark_gpf_final(conn: Any = None) -> int:
    """Every GP Fund row imported as provisional becomes final (the office's list has arrived)."""
    conn = conn or _conn
    if conn is None or not _tables_present(conn):
        return 0
    with _lock:
        n = conn.execute("SELECT COUNT(*) FROM signing_authorities WHERE provisional = 1 AND source = 'GPF_PROVISIONAL'").fetchone()[0]
        conn.execute("UPDATE signing_authorities SET provisional = 0 WHERE provisional = 1 AND source = 'GPF_PROVISIONAL'")
    return int(n)
