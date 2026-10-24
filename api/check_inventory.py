"""Every view's case count must be the same number. 30 Sep 2026.

    python3 -m api.check_inventory                  # against the running portal (:5184)
    python3 -m api.check_inventory --base URL

For each product, and each of the AG reviewer, the administrator and every department that has
cases, it reads the count every screen shows -- the register's list (/cases), the inventory
(/inventory: rows and counts), the AG sidebar (/departments/counts and the inventory's sidebar),
the dashboards (/stats) -- for "all", for every department and for every Pension section, and
fails (exit 1) on the first pair that differ. tests/test_inventory_consistency.py runs the same
comparison inside the test suite, after every status change.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from typing import Callable

PRODUCTS = ("PENSION", "GPF")


def compare(get: Callable[[str], object], role: str) -> list[str]:
    """The disagreements between views, as lines. ``get(path)`` returns the parsed JSON."""
    problems: list[str] = []
    ag = role in ("AG_REVIEWER", "AG_ADDL", "ADMIN", "AG_DAG", "AG_SENIOR_AUDITOR", "AG_ASSISTANT_AO", "AG_AO")
    for product in PRODUCTS:
        inv = get(f"/api/v2/inventory?product={product}")
        base = {
            "list": len(get(f"/api/v2/cases?product={product}")),
            "inventory rows": len(inv["rows"]),
            "inventory total": inv["counts"]["total"],
            "inventory by status": sum(inv["counts"]["by_status"].values()),
            "stats": sum(get(f"/api/v2/stats?product={product}")["by_status"].values()),
        }
        if ag:
            base["sidebar"] = sum(d["total"] for d in get(f"/api/v2/departments/counts?product={product}"))
            base["inventory sidebar"] = inv["sidebar"]["total"]
            base["sidebar by section"] = sum(inv["sidebar"]["by_section"].values())
        if len(set(base.values())) > 1:
            problems.append(f"{role} {product} all: {base}")
        if not ag:
            continue
        for d in inv["sidebar"]["by_department"]:
            code = urllib.parse.quote(d["code"])
            views = {"sidebar": d["total"],
                     "list": len(get(f"/api/v2/cases?product={product}&department={code}")),
                     "inventory": get(f"/api/v2/inventory?product={product}&department={code}")["counts"]["total"],
                     "stats": sum(get(f"/api/v2/stats?product={product}&department={code}")["by_status"].values())}
            if len(set(views.values())) > 1:
                problems.append(f"{role} {product} department {d['code']}: {views}")
        for section, n in inv["sidebar"]["by_section"].items():
            q = urllib.parse.quote(section)
            in_sidebar = sum(d["total"] for d in inv["sidebar"]["by_department"]
                             if (d["pension_section"] or "LEGACY") == section)
            views = {"sidebar": in_sidebar, "section count": n,
                     "list": len(get(f"/api/v2/cases?product={product}&pension_section={q}")),
                     "inventory": get(f"/api/v2/inventory?product={product}&pension_section={q}")["counts"]["total"],
                     "stats": sum(get(f"/api/v2/stats?product={product}&pension_section={q}")["by_status"].values())}
            if len(set(views.values())) > 1:
                problems.append(f"{role} {product} section {section}: {views}")
    return problems


def main(argv: list[str]) -> int:
    base = argv[argv.index("--base") + 1] if "--base" in argv else "http://127.0.0.1:5184"

    # The accounts and password the check signs in with. The trial's "1234" is the default; in
    # production (where it is refused) set PENSION_CHECK_PASSWORD, and PENSION_CHECK_USERS as
    # "username:ROLE,username:ROLE" for a reviewer and the administrator (go-live runbook, step 17).
    import os
    password = os.environ.get("PENSION_CHECK_PASSWORD") or "1234"
    users_spec = os.environ.get("PENSION_CHECK_USERS") or "ag.reviewer:AG_REVIEWER,admin:ADMIN"

    def login(user: str) -> str:
        req = urllib.request.Request(f"{base}/api/v2/auth/login", data=json.dumps({"username": user, "password": password}).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=30))["token"]

    def getter(token: str):
        return lambda path: json.load(urllib.request.urlopen(urllib.request.Request(
            base + path, headers={"Authorization": f"Bearer {token}"}), timeout=60))

    users = [tuple(part.split(":", 1)) for part in users_spec.split(",") if ":" in part]
    reviewer = next((u for u, r in users if r in ("AG_REVIEWER", "AG_ADDL", "AG_DAG", "ADMIN")), users[0][0])
    ag = getter(login(reviewer))
    from api.departments import DEPARTMENTS
    slug = {d.code: d.slug for d in DEPARTMENTS}
    for product in PRODUCTS:
        for d in ag(f"/api/v2/inventory?product={product}")["sidebar"]["by_department"]:
            if d["total"] and d["code"] in slug and (slug[d["code"]], "DEPT_OFFICER") not in users:
                users.append((slug[d["code"]], "DEPT_OFFICER"))
    problems: list[str] = []
    for user, role in users:
        problems += compare(getter(login(user)), f"{role}:{user}")
    for p in problems:
        print("MISMATCH", p)
    print(f"{'FAIL' if problems else 'OK'}: {len(users)} users x {len(PRODUCTS)} products compared"
          f"{'' if not problems else f', {len(problems)} mismatch(es)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
