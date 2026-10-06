"""The case inventory: ONE source of truth per product for every list, count and chart. 30 Sep 2026.

Before this, each screen fetched its own copy on its own timer -- the register every 8 s, the AG
Review sidebar every 8 s from a different query, the dashboards every 15 s from a third -- and
the register's tab counts were worked out in the browser from whatever list it had last. Two of
those queries also disagreed about Pension sections: the sidebar grouped a department by the
``departments.pension_section`` column, the lists by ``PENSION_SECTION_OF``, where "Legacy" meant
only the legacy code; a case of a department with no section (a retired code such as HEALTH)
showed in the sidebar and vanished from the section's list.

Now every view reads through here:

*   :func:`scope` is the only definition of which cases a user may see and which a filter
    selects (product, department, Pension section). ``/cases``, ``/departments/counts``,
    ``/stats`` and ``/inventory`` all use it.
*   :func:`section_of` is the only definition of a department's Pension section: its section
    in api.departments, or LEGACY where it has none.
*   :func:`inventory` returns the rows AND their counts from one query: the total, by status,
    by department and by section. Counts are never derived in the browser.
*   :func:`version` is a cheap token that changes whenever any case, event or run changes; the
    portal polls it and refetches every open view together when it moves.

Pension and GP Fund are separate inventories (``product``), each consistent within itself.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from api import workflow
from api.departments import LEGACY_DEPARTMENT, PENSION_SECTION_OF, PENSION_SECTION_ORDER

LEGACY = LEGACY_DEPARTMENT[0]


def section_of(code: str | None) -> str:
    """A department's Pension section; LEGACY for the legacy bucket and any code with none."""
    return PENSION_SECTION_OF.get(code or "") or LEGACY


def section_codes(conn: sqlite3.Connection, section: str) -> list[str]:
    """Every department code in one Pension section, LEGACY included, from the same rule."""
    if section != LEGACY and section not in PENSION_SECTION_ORDER:
        raise KeyError(section)
    codes = {r[0] for r in conn.execute("SELECT code FROM departments")}
    codes |= {r[0] for r in conn.execute("SELECT DISTINCT department_code FROM cases")}
    return sorted(c for c in codes if section_of(c) == section)


def scope(conn: sqlite3.Connection, user: Any, *, product: str | None = None, department: str | None = None,
          section: str | None = None, alias: str = "c") -> tuple[str, list]:
    """The SQL restriction for "the cases this user may see, narrowed by these filters"."""
    where, args = ["1 = 1"], []
    if getattr(user, "role", "") == "DEPT_OFFICER":
        where.append(f"{alias}.department_code = ?"); args.append(user.department_code)
    if product:
        where.append(f"{alias}.product = ?"); args.append(product)
    if department:
        where.append(f"{alias}.department_code = ?"); args.append(department)
    if section:
        codes = section_codes(conn, section)
        where.append(f"{alias}.department_code IN ({','.join('?' * len(codes)) or 'NULL'})"); args.extend(codes)
    return " AND ".join(where), args


def version(conn: sqlite3.Connection) -> str:
    """Changes whenever a case, its history or one of its runs changes."""
    c = conn.execute("SELECT COUNT(*), COALESCE(MAX(updated_at), '') FROM cases").fetchone()
    e = conn.execute("SELECT COUNT(*) FROM case_events").fetchone()
    r = conn.execute("SELECT COUNT(*), COALESCE(MAX(COALESCE(finished_at, started_at)), ''), "
                     "SUM(CASE WHEN state IN ('queued','running') THEN 1 ELSE 0 END) FROM case_runs").fetchone()
    return f"{c[0]}.{c[1]}.{e[0]}.{r[0]}.{r[1]}.{r[2] or 0}"


def counts_of(rows: list[dict], departments: list[sqlite3.Row]) -> dict:
    """Every count a view shows, from the rows themselves: they cannot disagree with the list."""
    by_status = {s: 0 for s in workflow.STATUSES}
    by_dept: dict[str, dict] = {}
    for d in departments:
        by_dept[d["code"]] = {"code": d["code"], "name": d["name"], "digital": bool(d["digital"]),
                              "pension_section": section_of(d["code"]), "active": bool(d["active"]),
                              "total": 0, "awaiting_review": 0, "by_status": {}}
    by_section: dict[str, int] = {}
    for r in rows:
        st = r["status"]
        by_status[st] = by_status.get(st, 0) + 1
        entry = by_dept.setdefault(r["department_code"], {
            "code": r["department_code"], "name": r.get("department_name") or r["department_code"], "digital": False,
            "pension_section": section_of(r["department_code"]), "active": False,
            "total": 0, "awaiting_review": 0, "by_status": {}})
        entry["total"] += 1
        entry["by_status"][st] = entry["by_status"].get(st, 0) + 1
        if st in workflow.AG_HOLDS:
            entry["awaiting_review"] += 1
        sec = section_of(r["department_code"])
        by_section[sec] = by_section.get(sec, 0) + 1
    return {"total": len(rows), "by_status": by_status,
            "awaiting_review": sum(v for k, v in by_status.items() if k in workflow.AG_HOLDS),
            # The sidebar's shape: no section (None) is the Legacy group.
            "by_department": [{**d, "pension_section": None if d["pension_section"] == LEGACY else d["pension_section"]}
                              for d in sorted(by_dept.values(), key=lambda d: d["name"].lower())
                              if d["active"] or d["total"]],
            "by_section": by_section}
