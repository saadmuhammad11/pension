"""The Accountant General and the Additional Accountant General differ by name, not by power.

24 Oct 2026. AG_REVIEWER was one role for two offices -- its label read "AG / Additional AG
and senior officers (all wings, every tier)" -- so the register could not say which of them
had acted on a case. The office asked for two, with the same authority: the split is so the
audit distinguishes them, and deliberately NOT a new rank between them.

That makes every place the old role granted something a place the new one must grant the same
thing, and there are more than twenty of them across workflow, v2, desks, departments,
server, gpf_bridge and check_inventory. A missed one is a silent hole -- an Additional AG who
cannot see a wing, or who can do something the AG cannot. So rather than list the sites, this
asserts the property: whatever the question, the two roles answer it alike.

    python3 -m unittest tests.test_the_two_ag_desks_are_equal -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import check_inventory, departments, desks, gpf_bridge, v2, workflow  # noqa: E402

AG = "AG_REVIEWER"
ADDL = "AG_ADDL"


def _user(role: str):
    return mock.Mock(role=role, id="u-" + role, pension_wing=None, department_code=None,
                     display_name=role, username=role.lower())


class TheyAreBothTheAgsOwnDesk(unittest.TestCase):

    def test_both_are_roles_a_user_can_hold(self) -> None:
        self.assertIn(ADDL, departments.ROLES)
        self.assertIn(ADDL, departments.AG_ROLES)

    def test_both_are_bound_to_no_wing_and_no_tier(self) -> None:
        self.assertIn(ADDL, workflow.ANY_TIER)
        self.assertIn(AG, workflow.ANY_TIER)

    def test_so_both_are_on_the_ag_side_and_read_ag_material(self) -> None:
        for group in (workflow.AG_SIDE, workflow.AG_READERS):
            self.assertIn(ADDL, group)
            self.assertIn(AG, group)

    def test_neither_is_a_tier(self) -> None:
        """A tier climbs; these two act wherever the case is."""
        self.assertNotIn(ADDL, workflow.TIER_ROLES)
        self.assertNotIn(AG, workflow.TIER_ROLES)


class WhateverIsAskedTheyAnswerAlike(unittest.TestCase):
    """The property, rather than a list of the sites that have to honour it."""

    def test_the_screens_may_offer_them_the_same_things(self) -> None:
        self.assertEqual(v2.capabilities(_user(AG)), v2.capabilities(_user(ADDL)))

    def test_they_oversee_alike(self) -> None:
        self.assertEqual(AG in v2.OVERSIGHT_ROLES, ADDL in v2.OVERSIGHT_ROLES)

    def test_they_decide_at_the_same_desks_of_the_old_register(self) -> None:
        self.assertEqual(desks.ACCOUNT_DESKS.get(AG), desks.ACCOUNT_DESKS.get(ADDL))

    def test_they_act_as_the_same_band_in_the_gp_fund_module(self) -> None:
        self.assertEqual(gpf_bridge.OFFICER_FOR_ROLE.get(AG), gpf_bridge.OFFICER_FOR_ROLE.get(ADDL))
        self.assertEqual(gpf_bridge.OFFICER_FOR_ROLE.get(ADDL), "dag")

    def test_they_see_every_department(self) -> None:
        for role in (AG, ADDL):
            self.assertTrue(v2.capabilities(_user(role))["all_departments"], role)

    def test_the_inventory_check_counts_them_both_as_the_office(self) -> None:
        src = (ROOT / "api" / "check_inventory.py").read_text(encoding="utf-8")
        line = next(ln for ln in src.splitlines() if ln.strip().startswith("ag = role in"))
        self.assertIn(AG, line)
        self.assertIn(ADDL, line)

    def test_every_transition_open_to_one_is_open_to_the_other(self) -> None:
        """The workflow table is the whole of what an officer may do to a case."""
        for action, (roles, _from, _to) in workflow.TRANSITIONS.items():
            self.assertEqual(AG in roles, ADDL in roles, action)

    def test_and_each_is_named_in_the_office_s_own_words(self) -> None:
        self.assertEqual(departments.ROLE_LABELS[AG], "Accountant General")
        self.assertEqual(departments.ROLE_LABELS[ADDL], "Additional Accountant General")
        self.assertNotEqual(departments.ROLE_LABELS[AG], departments.ROLE_LABELS[ADDL])


class TheDatabaseWillHoldIt(unittest.TestCase):

    def test_a_migration_widens_the_check(self) -> None:
        for rel in ("api/migrations/0018_additional_ag_role.sql",
                    "api/migrations/postgres/0018_additional_ag_role.sql"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("AG_ADDL", text, rel)

    def test_the_sqlite_rebuild_keeps_every_column(self) -> None:
        """0010 and 0014 rebuilt this table; a column dropped here is a column lost."""
        text = (ROOT / "api/migrations/0018_additional_ag_role.sql").read_text(encoding="utf-8")
        for col in ("id", "username", "display_name", "password_hash", "role", "department_code",
                    "active", "token_version", "created_at", "updated_at",
                    "must_change_password", "pension_wing"):
            self.assertIn(col, text, col)
        # ...and carries them across, pension_wing included -- 0014 added it and the copy in
        # that migration did not list it, so it must be listed here.
        copy = text[text.index("INSERT OR IGNORE"):text.index("DROP TABLE")]
        self.assertIn("pension_wing", copy)


if __name__ == "__main__":
    unittest.main()
