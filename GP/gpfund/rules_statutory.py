"""The statutory guard on R13. Build specification §5.3, "to build; not in the prototype".

R13 is the office's clarification that an OSD post on the SAP pay slip removes the succession
certificate. The specification adds a guard the prototype does not carry, and it is the one
place in this module where the STATUTE is stricter than both the circular and the office:

    Rule 1.35 applies section 4 of the Provident Funds Act 1925. Where a payee is neither a
    family member (Rule 1.2(1)(c)) nor a dependant nominee, no subsisting nomination covers
    the share, and the balance exceeds Rs 5,000, section 4(1)(c) requires probate, letters of
    administration or a succession certificate. Raise an officer-decision item in that case
    even when an OSD post exists.

So this check is deliberately NOT part of ``DEATH-SUCCESSION``: it has to be able to fire
when that check has already been satisfied by an OSD post. It raises an officer decision, not
a hard stop -- whether section 4 bites on a given set of claimants is a question of law for
the officer, and §14 rule 1 keeps the module recommending rather than deciding.

The converse, which the specification states in the same paragraph, is open item GPF-O17: the
Rules do NOT require a certificate from multiple widows or other family members, so circular
A.2(vi) is stricter than the Rules there. The module follows the circular and reports the
tension rather than resolving it.
"""

from __future__ import annotations

from typing import Any

from .contracts import CONF, NA, OK, Facts
from .engine import check, ev, fmt, num, verified, verified_result

#: Section 4(2) of the Provident Funds Act 1925: below this the Accounts Officer may pay
#: without probate. The figure is the Act's and is carried here as an effective-dated
#: parameter so a later amendment is a data change (§15).
SECTION_4_THRESHOLD_RS = 5_000

#: Who counts as "family" under Rule 1.2(1)(c). Anyone outside this, and outside a subsisting
#: nomination, is where section 4(1)(c) can bite.
FAMILY_RELATIONS = (
    "widow", "widower", "wife", "husband", "son", "daughter", "child",
    "father", "mother", "parent", "brother", "sister",
)


def _is_family(relation: Any) -> bool:
    text = str(relation or "").lower()
    return any(word in text for word in FAMILY_RELATIONS)


check(
    id="DEATH-SECTION4", group="checklist", ref="Rule 1.35 · Provident Funds Act 1925 s.4(1)(c)",
    code="A2-vi", title="Probate or succession certificate under section 4 of the Act",
    applies=lambda facts: facts.is_kind("death") and bool(facts.doc("death")),
    run=lambda facts: _section_4(facts),
)


def _section_4(facts: Facts) -> dict[str, Any]:
    death = facts.doc("death") or {}
    heirs = death.get("heirs") or []
    claim = facts.claim or {}
    balance = num(claim.get("amount"))

    if not heirs:
        # DEATH-HEIRS already reports that the heirs could not be established, and reporting
        # it twice would put the same gap on the officer's list under two headings.
        return {"status": NA,
                "finding": ("The heirs could not be established from the case, so section 4 cannot "
                            "be applied yet; see the legal heirs check.")}

    outsiders = [h for h in heirs
                 if not _is_family(h.get("relation")) and not h.get("nomineeDependant")]
    nomination = death.get("nomination") or {}
    covered_by_nomination = bool(nomination.get("subsists"))

    if not outsiders:
        who = ", ".join(f"{h.get('name')} ({h.get('relation')})" for h in heirs)
        return {"status": OK,
                "finding": (f"Every payee is a family member under Rule 1.2(1)(c): {who}. Section "
                            f"4(1)(c) of the Provident Funds Act 1925 does not require probate, "
                            f"letters of administration or a succession certificate, whatever the "
                            f"balance.")}

    if covered_by_nomination:
        return {"status": OK,
                "finding": (f"A payee is outside Rule 1.2(1)(c), but a subsisting nomination covers "
                            f"the share ({nomination.get('reference') or 'nomination on file'}), so "
                            f"section 4(1)(c) does not require probate.")}

    if balance is not None and balance <= SECTION_4_THRESHOLD_RS:
        return {"status": OK,
                "finding": (f"A payee is outside Rule 1.2(1)(c) and no nomination covers the share, "
                            f"but the balance of Rs {fmt(balance)} does not exceed "
                            f"Rs {fmt(SECTION_4_THRESHOLD_RS)}, so section 4(2) allows payment "
                            f"without probate.")}

    record = verified(facts, "DEATH-SECTION4")
    if record:
        return verified_result(
            record,
            "Section 4(1)(c) settled: payment may issue without probate on the grounds recorded.",
            "Section 4(1)(c) applies: probate, letters of administration or a succession "
            "certificate is required before payment.")

    who = ", ".join(f"{h.get('name')} ({h.get('relation')})" for h in outsiders)
    amount = f"Rs {fmt(balance)}" if balance is not None else "the balance"
    return {"status": CONF,
            "finding": (f"{who} is not a family member under Rule 1.2(1)(c) and is not shown as a "
                        f"dependant nominee, no subsisting nomination covers the share, and "
                        f"{amount} exceeds Rs {fmt(SECTION_4_THRESHOLD_RS)}. Rule 1.35 applies "
                        f"section 4 of the Provident Funds Act 1925, and section 4(1)(c) then "
                        f"requires probate, letters of administration or a succession certificate. "
                        f"This stands even where an OSD post has removed the certificate under R13, "
                        f"because R13 is an office instruction and this is the statute."),
            "remedy": ("Officer to decide whether section 4(1)(c) applies to these payees. If it "
                       "does, obtain probate, letters of administration or a succession "
                       "certificate before payment. The tension between circular A.2(vi) and "
                       "Rule 1.34 is open item GPF-O17."),
            "cure": {"kind": "verify", "vid": "DEATH-SECTION4"}}
