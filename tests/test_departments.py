"""The department configuration obeys its own rules: unique slugs and ports, the port rule,
every theme key exists, nothing on a reserved port.

    python3 -m unittest tests.test_departments -v
"""
from __future__ import annotations

import re
import unittest

from api import departments as d
from api.themes import SLOTS, THEMES, theme_for


class DepartmentConfig(unittest.TestCase):
    def test_eighty_six_departments_with_unique_codes_slugs_and_ports(self) -> None:
        self.assertEqual(len(d.DEPARTMENTS), 86)
        for attr in ("code", "slug", "port"):
            values = [getattr(x, attr) for x in d.DEPARTMENTS]
            self.assertEqual(len(values), len(set(values)), f"duplicate {attr}")

    def test_slugs_are_valid_usernames_and_follow_the_rule(self) -> None:
        for x in d.DEPARTMENTS:
            self.assertRegex(x.slug, r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$", x.name)
            self.assertEqual(d.slugify(x.name), x.slug, x.name)

    def test_ports_follow_the_rule_and_avoid_reserved_ones(self) -> None:
        self.assertEqual(d.assign_ports(d.DEPARTMENTS), {x.code: x.port for x in d.DEPARTMENTS})
        for x in d.DEPARTMENTS:
            self.assertNotIn(x.port, d.RESERVED_PORTS, x.name)
            self.assertNotEqual(x.port, d.AG_PORTAL_PORT)
        self.assertEqual(d.BY_CODE["PUNJAB_POLICE"].port, 5180)
        self.assertEqual(d.BY_CODE["SCHOOL_EDUCATION"].port, 5181)
        self.assertEqual(min(x.port for x in d.DEPARTMENTS if x.code not in d.PINNED_PORTS), 5182)

    def test_police_units_wear_the_police_theme_and_every_theme_exists(self) -> None:
        for x in d.DEPARTMENTS:
            self.assertIn(x.theme, THEMES, x.name)
            if x.is_police:
                self.assertEqual(x.theme, "police", x.name)
        self.assertEqual(sum(1 for x in d.DEPARTMENTS if x.is_police), 25)
        self.assertEqual(d.BY_CODE["SCHOOL_EDUCATION"].theme, "education")

    def test_every_theme_fills_every_slot_with_a_hex(self) -> None:
        for key, t in THEMES.items():
            for slot in SLOTS:
                self.assertRegex(t[slot], r"^#[0-9A-Fa-f]{6}$", f"{key}.{slot}")
        full = theme_for("police", title="Punjab Police")
        self.assertEqual(full["title"], "Punjab Police")
        self.assertEqual(full["primary"], "#140D44")

    def test_portal_for_each_role(self) -> None:
        self.assertEqual(d.portal_for("AG_REVIEWER", None), "ag")
        self.assertEqual(d.portal_for("ADMIN", None), "ag")
        self.assertEqual(d.portal_for("DEPT_OFFICER", "PUNJAB_POLICE"), "ag" if d.SINGLE_PORTAL else "punjab-police")
        self.assertIsNone(d.portal_for("DEPT_OFFICER", "LEGACY"))
        self.assertIsNone(d.portal_for("DEPT_OFFICER", None))

    def test_next_free_port_skips_used_and_reserved(self) -> None:
        p = d.next_free_port()
        self.assertNotIn(p, d.BY_PORT)
        self.assertNotIn(p, d.RESERVED_PORTS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
