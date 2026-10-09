"""The specimen-signature register: whose signature a department told the AG to expect.

A department sends the DAG (Pension) a letter naming its Pension Sanctioning Authority, with that
officer's specimen signature and stamp (the S&GAD letter No.SO.A.III(S&GAD)7-7/2025 of 9 September
2025 is the first). That letter is the standard a sanction form's signature is compared against:
BRAIN §2, "the signature authority on a form is itself a checklist item -- a sanction signed by
the wrong officer is a defect"; SOP §5.2 AG-04, the prescribed form "signed by the PSA".

This is reference data, not code (BUILD §5): ``rules/specimens/register.json`` lists each
specimen with the post it is for, the dates it is in force and the letter it came from, and the
images cut from that letter sit beside it. A specimen is kept per POST, not per department --
a department has several sanctioning authorities, and a post changes hands -- and a new letter
for the same post closes the old entry's ``effective_to`` rather than replacing it, so a case
signed in 2025 is still compared with the officer who held the post in 2025.

Standard library only, like the rest of ``rules``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REGISTER = Path(__file__).resolve().parent / "specimens" / "register.json"

#: Since 9 Oct 2026 (scope change C1) the master copy of this register is the database table
#: ``signing_authorities`` (api.signatories), which the API exports to a JSON file in this same
#: shape after every change and names here. The bundled file stays the fallback for a pipeline
#: that runs without a database (tests, a box without PostgreSQL). ``rules`` stays standard
#: library: it reads a file, whichever one the API has pointed it at.
ACTIVE: Path | None = None


def active_register() -> Path:
    """The register file in use: the API's export where it exists, else the bundled one."""
    if ACTIVE is not None and ACTIVE.exists():
        return ACTIVE
    return REGISTER


@dataclass(frozen=True)
class Specimen:
    id: str
    department: str
    post: str
    officer: str
    scope: str
    effective_from: date
    effective_to: date | None
    stamp_text: str
    images: tuple[Path, ...]
    authority: dict = field(default_factory=dict, compare=False, hash=False)
    department_aliases: tuple[str, ...] = ()
    post_aliases: tuple[str, ...] = ()

    def in_force_on(self, when: date) -> bool:
        return self.effective_from <= when and (self.effective_to is None or when <= self.effective_to)

    @property
    def cite(self) -> str:
        a = self.authority
        return f"{a.get('letter_no', self.id)} dated {a.get('dated', self.effective_from.isoformat())}"


#: S&GAD as a scan reads it: "S&GAD", "S & G A D", "S and GAD", and the ampersand misread as
#: "R" or "8" ("S R G A D", seen on 23 Sep 2026). All become one word before matching.
_SGAD = re.compile(r"(?i)\bs\s*(?:&|and|r|8)?\s*g\s*\.?\s*a\s*\.?\s*d\b")


def _key(text: str | None) -> str:
    """"Additional Secretary (Admn.)" -> "additional secretary admn"; "S & G A D" -> "sgad"."""
    t = _SGAD.sub(" sgad ", text or "").lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


def _mentions(text: str | None, names: tuple[str, ...]) -> bool:
    hay = f" {_key(text)} "
    squashed = hay.replace(" ", "")
    for name in names:
        k = _key(name)
        if not k:
            continue
        if f" {k} " in hay or (len(k.replace(' ', '')) >= 4 and k.replace(" ", "") in squashed):
            return True
    return False


def names_post(spec: Specimen, text: str | None) -> bool:
    """Does ``text`` (a stamp, a printed designation) name this specimen's post?"""
    return _mentions(text, spec.post_aliases)


def load(path: Path | None = None) -> tuple[Specimen, ...]:
    path = active_register() if path is None else path
    if not path.exists():
        return ()
    raw = json.loads(path.read_text())
    out = []
    for s in raw.get("specimens", []):
        out.append(Specimen(
            id=s["id"], department=s["department"], post=s["post"], officer=s.get("officer", ""),
            scope=s.get("scope", ""),
            effective_from=date.fromisoformat(s["effective_from"]),
            effective_to=date.fromisoformat(s["effective_to"]) if s.get("effective_to") else None,
            stamp_text=s.get("stamp_text", ""),
            images=tuple(path.parent / name for name in s.get("images", [])),
            authority=s.get("authority", {}),
            department_aliases=tuple([s["department"], *s.get("department_aliases", [])]),
            post_aliases=tuple([s["post"], *s.get("post_aliases", [])]),
        ))
    return tuple(out)


def departments_on_file(specimens: tuple[Specimen, ...] | None = None) -> tuple[Specimen, ...]:
    return load() if specimens is None else specimens


def for_department(text: str | None, specimens: tuple[Specimen, ...] | None = None) -> list[Specimen]:
    """Every specimen of the department ``text`` names (a stamp, a letterhead, a forwarding letter)."""
    return [s for s in departments_on_file(specimens) if _mentions(text, s.department_aliases)]


def lookup(department: str | None, designation: str | None, signed_on: date | None,
           specimens: tuple[Specimen, ...] | None = None) -> tuple[Specimen | None, str]:
    """The specimen a signature is to be compared with, and why -- or why there is none.

    Returns ``(specimen, "on file")`` or ``(None, reason)`` where reason is one of:
      "department not on file"  -- no specimen from this department at all; nothing to check
      "post not on file"        -- the department is on file, but not for the post that signed
      "not in force on <date>"  -- the post is on file, but no specimen covers the signing date
    Where the form carries no signing date, the specimen in force today is used and the caller
    says so, because a sanction is compared with somebody rather than with nobody.
    """
    specs = for_department(department, specimens)
    if not specs:
        return None, "department not on file"
    posts = [s for s in specs if _mentions(designation, s.post_aliases)]
    if not posts:
        return None, "post not on file"
    if signed_on is None:
        current = [s for s in posts if s.effective_to is None]
        return (current or posts)[-1], "on file (no signing date on the form)"
    live = [s for s in posts if s.in_force_on(signed_on)]
    if not live:
        return None, f"not in force on {signed_on.isoformat()}"
    return live[-1], "on file"
