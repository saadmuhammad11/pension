"""The administrator's password reset is a masked form, not a browser prompt (audit 6 Oct 2026, L9).

    python3 -m unittest tests.test_admin_screen_has_no_browser_prompts -v

window.prompt shows a typed password in clear, cannot be a password field, and some browsers block
it. Disabling an account and resetting a password are ordinary forms now. The portal has no
JavaScript test runner; this reads the source, and the release build's type check keeps it honest.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "portals" / "src"


class NoBrowserPrompts(unittest.TestCase):
    def test_no_screen_uses_a_browser_prompt(self) -> None:
        offenders = [str(p.relative_to(SRC)) for p in SRC.rglob("*.ts*")
                     if re.search(r"\b(window\.)?(prompt|confirm|alert)\s*\(", p.read_text()) and "demo" not in p.parts]
        self.assertEqual(offenders, [])

    def test_the_reset_asks_for_the_password_in_a_password_field(self) -> None:
        users = (SRC / "shared" / "screens" / "admin" / "Users.tsx").read_text()
        form = users[users.index("{ask && ("):users.index("<div className=\"side-grid\"")]
        # The password is typed into the shared PasswordField (frontend review F14, 9 Oct 2026): a
        # masked input with a Show toggle and the server's minimum length, never a browser prompt.
        self.assertIn('<PasswordField id="ask-password"', form)
        field = (SRC / "shared" / "components" / "PasswordField.tsx").read_text()
        self.assertIn("'password'", field)
        self.assertIn("autoComplete", field)
        self.assertIn("minLength", field)
        reason_input = form[form.index('<input id="ask-reason"'):]
        self.assertIn("required", reason_input[:reason_input.index("/>")])
        self.assertIn("resetPassword(user.id, value)", users)
        self.assertIn("disableUser(user.id, value)", users)


if __name__ == "__main__":
    unittest.main()
