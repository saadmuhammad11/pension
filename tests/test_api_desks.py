"""Who may do what, by desk. SOP §4, BUILD §11.1. ``api/desks.py``.

    python3 -m unittest tests.test_api_desks -v

Standard library only: the module is the permission table and the refusal, and the HTTP layer
(``api/server.py``) only turns the refusal into a 403. The portal keeps a mirror of the table
in ``identity.ts``; the last test pins the two together by reading that file.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.desks import (DESKS, PERMISSIONS, DeskNotAuthorised, permissions_table,  # noqa: E402
                       require_desk, resolve_desk)


class TheDesksAreTheDocumentation(unittest.TestCase):
    def test_the_nine_sop_desks_are_present(self):
        self.assertEqual(set(DESKS), {
            "AG_REVIEWER", "AG_DETERMINING", "DAG_PENSION", "AD_SUBMITTER", "PSA",
            "PFC_OPERATOR", "AUDITOR", "REFERENCE_ADMIN", "SYSTEM_ADMIN",
        })

    def test_the_confirming_desks_carry_the_same_labels(self):
        from rules.confirmations import AUTHORISED_DESKS
        for desk_id, label in AUTHORISED_DESKS.items():
            self.assertEqual(DESKS[desk_id], label)

    def test_every_permission_names_known_desks_and_cites_the_sop(self):
        for action, spec in PERMISSIONS.items():
            self.assertTrue(spec["desks"], action)
            for d in spec["desks"]:
                self.assertIn(d, DESKS, f"{action}: {d}")
            self.assertIn("SOP §", str(spec["cite"]), action)


class ResolvingAStatedDesk(unittest.TestCase):
    def test_by_id_by_label_and_case_insensitively(self):
        self.assertEqual(resolve_desk("AG_REVIEWER"), "AG_REVIEWER")
        self.assertEqual(resolve_desk("Auditor, Pension wing (AG / DAO)"), "AG_REVIEWER")
        self.assertEqual(resolve_desk("  deputy accountant general (pension) "), "DAG_PENSION")

    def test_nothing_and_nonsense_resolve_to_none(self):
        self.assertIsNone(resolve_desk(None))
        self.assertIsNone(resolve_desk(""))
        self.assertIsNone(resolve_desk("Syed Haider"))


class WhatEachDeskMayDo(unittest.TestCase):
    def test_the_auditor_selects_the_variant_and_decides(self):
        self.assertEqual(require_desk("intake_choices", "AG_REVIEWER"), "AG_REVIEWER")
        self.assertEqual(require_desk("decide", "Auditor, Pension wing (AG / DAO)"), "AG_REVIEWER")

    def test_the_department_and_the_pfc_submit_but_do_not_choose(self):
        for desk in ("AD_SUBMITTER", "PFC_OPERATOR"):
            self.assertEqual(require_desk("intake", desk), desk)
            with self.assertRaises(DeskNotAuthorised) as cm:
                require_desk("intake_choices", desk)
            self.assertIn("§4.4(1)", str(cm.exception))

    def test_the_dag_decides_and_confirms_the_psa_does_neither(self):
        self.assertEqual(require_desk("decide", "DAG_PENSION"), "DAG_PENSION")
        self.assertEqual(require_desk("confirm_rule", "DAG_PENSION"), "DAG_PENSION")
        for action in ("decide", "confirm_rule", "intake", "recompute"):
            with self.assertRaises(DeskNotAuthorised):
                require_desk(action, "PSA")

    def test_the_audit_office_only_reads(self):
        for action in PERMISSIONS:
            with self.assertRaises(DeskNotAuthorised):
                require_desk(action, "AUDITOR")

    def test_the_reference_admin_confirms_and_recomputes_but_does_not_decide(self):
        self.assertEqual(require_desk("confirm_rule", "REFERENCE_ADMIN"), "REFERENCE_ADMIN")
        self.assertEqual(require_desk("recompute", "REFERENCE_ADMIN"), "REFERENCE_ADMIN")
        with self.assertRaises(DeskNotAuthorised) as cm:
            require_desk("decide", "REFERENCE_ADMIN")
        self.assertIn("§4.4(6)", str(cm.exception))

    def test_no_desk_stated_is_refused_and_told_where_to_sign_in(self):
        with self.assertRaises(DeskNotAuthorised) as cm:
            require_desk("decide", None)
        msg = str(cm.exception)
        self.assertIn("no desk was stated", msg)
        self.assertIn("Deputy Accountant General (Pension)", msg)

    def test_an_unknown_desk_is_named_in_the_refusal(self):
        with self.assertRaises(DeskNotAuthorised) as cm:
            require_desk("decide", "Chief Pilot, VIP Flight")
        self.assertIn("'Chief Pilot, VIP Flight'", str(cm.exception))

    def test_the_refusal_names_the_desk_and_the_paragraph(self):
        with self.assertRaises(DeskNotAuthorised) as cm:
            require_desk("decide", "Pension Sanctioning Authority")
        msg = str(cm.exception)
        self.assertIn("'Pension Sanctioning Authority' may not record a decision", msg)
        self.assertIn("SOP §4.4(6)", msg)


class TheTableThePortalReads(unittest.TestCase):
    def test_get_api_desks_shape(self):
        t = permissions_table()
        self.assertEqual(len(t["desks"]), 9)
        auditor = next(d for d in t["desks"] if d["id"] == "AG_REVIEWER")
        self.assertIn("decide", auditor["may"])
        self.assertIs(t["authenticated"], True)
        self.assertEqual(t["account_desks"]["ADMIN"], ["SYSTEM_ADMIN", "REFERENCE_ADMIN"])

    def test_the_portal_mirror_matches_the_server_table(self):
        """The screens must be able to state what the server enforces. The desk-aware portal
        (portal/src/identity.ts) was retired on 25 Sep 2026 with the one-portal case system,
        whose permissions are the ``capabilities`` the server returns at sign-in (api/v2.py) and
        which every screen consults before offering an action. The desk table still guards the
        old ``/api/*`` routes, which now need a case-system token and no screen calls. So the pin
        moves: the frontend's Capabilities type must name exactly the server's capability keys."""
        from api.auth import User
        from api.v2 import capabilities
        keys = set()
        for role in ("DEPT_OFFICER", "AG_REVIEWER", "ADMIN"):
            keys |= set(capabilities(User("u", "u", "U", role, "PUNJAB_POLICE" if role == "DEPT_OFFICER" else None, True, 1)))
        mirror_file = ROOT / "portals" / "src" / "shared" / "auth" / "session.ts"
        self.assertTrue(mirror_file.exists(), f"{mirror_file.relative_to(ROOT)} is absent: the portal has no capabilities mirror")
        block = re.search(r"export interface Capabilities \{(.*?)\}", mirror_file.read_text(encoding="utf-8"), re.S)
        self.assertIsNotNone(block, "Capabilities interface not found in session.ts")
        mirrored = set(re.findall(r"^\s*([a-z_]+):\s*boolean", block.group(1), re.M))
        self.assertEqual(mirrored, keys, "the frontend's Capabilities differ from the server's capabilities()")

if __name__ == "__main__":
    unittest.main()
