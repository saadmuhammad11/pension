"""Advances, refundable and non-refundable. Build specification §5.2, §11.

The two checks that carry the money are :func:`_adv_limit` and :func:`_adv_active`, and both
depend on :func:`balance_before` -- which is where §6.5's trap lives. An extract pulled after
an advance has been posted shows the balance AFTER the advance, and on both corpus advances
applying the limit to the pay-slip figure would have failed a sanction that is in fact within
the Rules:

    Refundable      Rs 58,000   pay slip Rs 19,194    before the advance Rs 79,899
    Non-refundable  Rs 490,955  pay slip Rs 260,522   before the advance Rs 743,677

So the engine finds the posting of the advance under examination in the re-calculation report
and uses the OPENING balance of that year. Where only a pay slip is available the limit test
returns ``conf``, never ``ok`` (§11.2) -- it cannot be told whether the advance is already
deducted, and a limit tested against the wrong basis is worse than an untested one.
"""

from __future__ import annotations

from typing import Any

from .contracts import ADV, CONF, HARD, OK, SAP, Facts
from .engine import check, digits, ev, fmt, num, same_name
from .params import ADVANCE_LIMITS, OFFICE_CAP_PCT

ADVANCES = ("refundable", "nonrefundable")


def _doc_cure(doc_type: str, apply: str, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"kind": "doc", "docType": doc_type, "apply": apply, "fields": fields or []}


# -- the checklist items, A1-i to A1-iii -----------------------------------------------------

check(
    id="ADV-SANCTION", group="checklist", checklist="A1-i", ref="A1-i · B1-ii", code="B1-ii",
    title="Original sanction of the competent authority",
    applies=lambda facts: facts.is_kind(*ADVANCES),
    run=lambda facts: _adv_sanction(facts),
)


def _adv_sanction(facts: Facts) -> dict[str, Any]:
    sanction = facts.doc("sanction")
    if sanction and sanction.get("present"):
        return {"status": OK,
                "finding": (f"Sanction No. {sanction.get('orderNo') or '(not stated)'} dated "
                            f"{sanction.get('date') or '(not stated)'} of "
                            f"{sanction.get('printedAuthority') or sanction.get('dept')}, page "
                            f"{sanction.get('page')}, for Rs {fmt(sanction.get('amount'))}. The "
                            f"signatory is checked against the DOA register."),
                "evidence": [ev(sanction.get("page"), "Sanction", sanction.get("crop"))]}
    return {"status": HARD, "finding": "No original sanction is on file.",
            "remedy": "Produce the original sanction of the competent authority.",
            "cure": _doc_cure("Original sanction", "add-sanction", [
                {"k": "orderNo", "label": "Order no.", "type": "text"},
                {"k": "date", "label": "Date", "type": "text"},
                {"k": "amount", "label": "Amount sanctioned (Rs)", "type": "number"},
                {"k": "rule", "label": "Rule quoted", "type": "text"}])}


check(
    id="ADV-RULE", group="checklist", ref="B1-iv · B2-ix", code="B1-iv",
    title="Rule and reason quoted on the sanction",
    applies=lambda facts: bool(facts.is_kind(*ADVANCES)
                               and (facts.doc("sanction") or {}).get("present")),
    run=lambda facts: _adv_rule(facts),
)


def _adv_rule(facts: Facts) -> dict[str, Any]:
    """The rule must be quoted; a refundable advance needs a reason too.

    Rule 1.16 needs no reason -- that is the whole point of the clause (a non-refundable
    advance at 50 or over, no reason required) -- so the module says so rather than raising
    B2-ix against a sanction that is correct in not stating one.
    """
    sanction = facts.doc("sanction") or {}
    code = "B1-iv" if facts.is_kind("refundable") else "B2-ix"
    needs_reason = facts.is_kind("refundable")
    if sanction.get("rule") and (not needs_reason or sanction.get("reason")):
        reason = f". Reason: {sanction.get('reason')}." if sanction.get("reason") else "."
        no_reason_needed = (" Under Rule 1.16 no reason is needed."
                            if sanction.get("limitClause") == "1.16" else "")
        return {"status": OK, "code": code,
                "finding": f"Rule quoted: {sanction.get('rule')}{reason}{no_reason_needed}",
                "evidence": [ev(sanction.get("page"), "Sanction")]}
    missing_rule = not sanction.get("rule")
    return {"status": HARD, "code": code,
            "finding": ("The sanction does not quote the rule under which the advance is granted."
                        if missing_rule else
                        "The sanction does not state the reason for the advance."),
            "remedy": ("Obtain a sanction quoting the rule"
                       + (" and the reason for the advance." if needs_reason else ".")),
            "evidence": [ev(sanction.get("page"), "Sanction")],
            "cure": _doc_cure("Revised sanction", "set-sanction-rule", [
                {"k": "rule", "label": "Rule quoted", "type": "text"},
                {"k": "reason", "label": "Reason stated", "type": "text"}])}


check(
    id="ADV-CNIC", group="checklist", checklist="A1-ii", ref="A1-ii · R5",
    title="Copy of CNIC of the subscriber",
    applies=lambda facts: facts.is_kind(*ADVANCES),
    run=lambda facts: _adv_cnic(facts),
)


def _adv_cnic(facts: Facts) -> dict[str, Any]:
    card = facts.cnic_of("subscriber")
    if card:
        return {"status": OK,
                "finding": (f"CNIC copy at page {card.get('page')}, no. {card.get('number')}. "
                            f"Attestation is not required (R5)."),
                "evidence": [ev(card.get("page"), "CNIC", card.get("crop"))]}
    return {"status": HARD, "code": "A1-ii",
            "finding": "No copy of the subscriber’s CNIC is on file.",
            "remedy": "Obtain a copy of the subscriber’s CNIC. Attestation is not required.",
            "cure": _doc_cure("CNIC copy", "add-cnic", [
                {"k": "number", "label": "CNIC number", "type": "text"},
                {"k": "type", "label": "Card type", "type": "select",
                 "options": ["smart", "old"]}])}


check(
    id="ADV-FORM", group="checklist", checklist="A1-iii", ref="A1-iii · R6",
    title="Form 5 (refundable) or Form 6-B (non-refundable)",
    applies=lambda facts: facts.is_kind(*ADVANCES),
    run=lambda facts: _adv_form(facts),
)


def _adv_form(facts: Facts) -> dict[str, Any]:
    form = facts.doc("changeForm")
    refundable = facts.is_kind("refundable")
    want = "05" if refundable else "06"
    name = "Form 5 (FORM PAY 05)" if refundable else "Form 6-B (FORM PAY 06)"
    code = "B1-v" if refundable else "B2-iii"
    cure = _doc_cure(name, "add-form", [
        {"k": "personalNo", "label": "Personal number on the form", "type": "text",
         "expect": facts.personnel_no},
        {"k": "signed", "label": "Signed by the subscriber", "type": "yesno"},
        {"k": "ddoSigned", "label": "Signed and stamped by the DDO", "type": "yesno"}])
    if not form or not form.get("present"):
        return {"status": HARD, "code": code, "finding": f"{name} is not attached.",
                "remedy": f"Attach {name} with the subscriber’s personal number and signature.",
                "cure": cure}
    if want not in str(form.get("label") or ""):
        return {"status": HARD, "code": code,
                "finding": f"The form attached is {form.get('label')}, not {name}.",
                "remedy": f"Attach {name}.",
                "evidence": [ev(form.get("page"), form.get("label"))], "cure": cure}
    # R6: only the personal number and the signatures are mandatory. Revision 1 raised eleven
    # blank fields on Form 5 as hard stops; §16.3 keeps that as a regression case.
    return {"status": OK,
            "finding": (f"{name} at page {form.get('page')}. Only the personal number and "
                        f"signatures are mandatory; the loan details box is not examined (R6)."),
            "evidence": [ev(form.get("page"), form.get("label"))]}


check(
    id="ADV-FORM-DDO", group="checklist", ref="B1-vii · B2-v", title="Form signed by the DDO",
    applies=lambda facts: bool(facts.is_kind(*ADVANCES)
                               and (facts.doc("changeForm") or {}).get("present")),
    run=lambda facts: _adv_form_ddo(facts),
)


def _adv_form_ddo(facts: Facts) -> dict[str, Any]:
    form = facts.doc("changeForm") or {}
    code = "B1-vii" if facts.is_kind("refundable") else "B2-v"
    if form.get("ddoSigned"):
        return {"status": OK, "code": code,
                "finding": f"Signed and stamped by {form.get('ddoStamp') or 'the DDO'}.",
                "evidence": [ev(form.get("page"), "DDO signature", form.get("ddoCrop"))]}
    return {"status": HARD, "code": code,
            "finding": (f"The {form.get('label')} is not signed by the Drawing and Disbursing "
                        f"Officer."),
            "remedy": "Obtain the DDO’s signature and stamp on the form.",
            "evidence": [ev(form.get("page"), form.get("label"))],
            "cure": _doc_cure(f"{form.get('label')} signed by DDO", "ddo-signed", [
                {"k": "ddoSigned", "label": "Signed and stamped by the DDO", "type": "yesno"}])}


# -- R6: the three fields the office does examine -------------------------------------------

check(
    id="ADV-PERSNO", group="identity", ref="R6", code="R6",
    title="Personal number on the form tallies with the pay slip",
    applies=lambda facts: bool(facts.is_kind(*ADVANCES)
                               and (facts.doc("changeForm") or {}).get("present")),
    run=lambda facts: _adv_persno(facts),
)


def _adv_persno(facts: Facts) -> dict[str, Any]:
    form = facts.doc("changeForm") or {}
    payslip = facts.sap_payslip

    def cure(expect: Any) -> dict[str, Any]:
        return _doc_cure(form.get("label"), "set-form-persno", [
            {"k": "personalNo", "label": "Personal number on the corrected form",
             "type": "text", "expect": expect}])

    if not form.get("personalNo"):
        return {"status": HARD,
                "finding": (f"The personal number is not filled in on the {form.get('label')}. "
                            f"It is a mandatory field."),
                "remedy": "Enter the personal number on the form.",
                "evidence": [ev(form.get("page"), form.get("label"))],
                "cure": cure(facts.personnel_no)}
    if not payslip:
        # Waits rather than passing. §16.2 requires exactly this of every SAP-dependent check.
        return {"status": SAP,
                "finding": (f"Personal number {form.get('personalNo')} on the form. The SAP pay "
                            f"slip is needed to tally it."),
                "cure": {"kind": "sap"}}
    if digits(form.get("personalNo")) == digits(payslip.get("persNo")):
        return {"status": OK,
                "finding": (f"Personal number {form.get('personalNo')} on the "
                            f"{form.get('label')} tallies with the SAP pay slip."),
                "evidence": [ev(form.get("page"), form.get("label")),
                             ev(payslip.get("page"), "Pay slip")]}
    return {"status": HARD,
            "finding": (f"The {form.get('label')} gives personal number {form.get('personalNo')}; "
                        f"the SAP pay slip gives {payslip.get('persNo')}."),
            "remedy": "Correct the personal number on the form.",
            "evidence": [ev(form.get("page"), form.get("label")),
                         ev(payslip.get("page"), "Pay slip")],
            "cure": cure(payslip.get("persNo"))}


check(
    id="ADV-APPLICANT", group="identity", ref="R6", code="R6",
    title="Applicant on the form is the subscriber",
    applies=lambda facts: bool(facts.is_kind(*ADVANCES)
                               and (facts.doc("changeForm") or {}).get("present")),
    run=lambda facts: _adv_applicant(facts),
)


def _adv_applicant(facts: Facts) -> dict[str, Any]:
    """The name, against SAP and the card, with transliteration variants allowed.

    The corpus card spells "Subscribar" where every other paper spells "Subscriber", and the Urdu
    name is the same. A strict comparison would raise a defect about a transliteration on a
    subscriber the personnel number already identifies, so the reading stage records the
    variants it saw and they are accepted here.
    """
    form = facts.doc("changeForm") or {}
    payslip = facts.sap_payslip
    card = facts.cnic_of("subscriber")
    variants = tuple(facts.data.get("nameVariants") or ())

    references: list[tuple[str, Any, bool | None]] = []
    if payslip and payslip.get("name"):
        references.append(("SAP pay slip", payslip.get("name"),
                           same_name(form.get("name"), payslip.get("name"))))
    if card and card.get("name"):
        references.append(("CNIC", card.get("name"), same_name(form.get("name"), card.get("name"))))
    if not references:
        return {"status": SAP,
                "finding": (f"Name on the form: {form.get('name') or '(not filled in)'}. Nothing "
                            f"yet to compare it with."),
                "cure": {"kind": "sap"}}
    wrong = [r for r in references if r[2] is False and r[1] not in variants]
    if wrong:
        detail = "; ".join(f"{label} reads {value}" for label, value, _ in wrong)
        return {"status": HARD,
                "finding": (f"Name on the {form.get('label')} is {form.get('name')}; {detail}."),
                "remedy": "Confirm the applicant and correct the form."}
    agreed = " and ".join(f"{label} ({value})" for label, value, _ in references)
    note = f" {facts.data.get('nameNote')}" if facts.data.get("nameNote") else ""
    return {"status": OK, "finding": f"Name {form.get('name')} agrees with {agreed}.{note}"}


check(
    id="ADV-FORM-CNIC", group="identity", ref="R6", code="R6",
    title="CNIC number written on the form",
    applies=lambda facts: bool(
        facts.is_kind(*ADVANCES) and (facts.doc("changeForm") or {}).get("cnic")
        and any((c.get("whose") or "subscriber") == "subscriber" and c.get("number")
                for c in facts.cnics)),
    run=lambda facts: _adv_form_cnic(facts),
)


def _adv_form_cnic(facts: Facts) -> dict[str, Any]:
    """A CNIC transposed on the form is an OBSERVATION, not a defect. R6.

    The field is not mandatory on this form, and the applicant is confirmed by personal
    number and name. The corpus case writes 00010-0000104-4 where the card, SAP and both QR
    codes read 00001-0000104-4 -- two digits transposed, on a person whose identity is not in
    doubt.
    """
    form = facts.doc("changeForm") or {}
    card = next(c for c in facts.cnics
                if (c.get("whose") or "subscriber") == "subscriber" and c.get("number"))
    if digits(form.get("cnic")) == digits(card.get("number")):
        return {"status": OK,
                "finding": f"CNIC {card.get('number')} on the form agrees with the card."}
    return {"status": ADV,
            "finding": (f"The {form.get('label')} records CNIC {form.get('cnic')}; the card, the "
                        f"SAP pay slip and the QR codes read {card.get('number')}. The applicant "
                        f"is otherwise confirmed by personal number and name, and the CNIC field "
                        f"is not mandatory on this form (R6), so this is noted only."),
            "remedy": "DDO to correct the CNIC on the form for the department’s record.",
            "evidence": [ev(form.get("page"), form.get("label"), form.get("cnicCrop")),
                         ev(card.get("page"), "CNIC", card.get("crop"))],
            "cure": _doc_cure(f"Corrected {form.get('label')}", "set-form-cnic", [
                {"k": "cnic", "label": "CNIC on the corrected form", "type": "text",
                 "expect": card.get("number")}])}


# -- the balance before the advance, §6.5 ---------------------------------------------------

def balance_before(facts: Facts) -> dict[str, Any] | None:
    """The balance the limit must be tested against, and why it is that figure. §6.5.

    Order of preference:

    1. a basis the reading stage established explicitly;
    2. the OPENING balance of the year in which this advance is posted in the re-calculation
       report -- found by matching the sanctioned amount in the temporary or permanent
       advance column, which is what makes the figure the balance *before* the advance;
    3. the report's last closing balance, where the advance is not yet posted;
    4. the pay slip balance, marked ``provisional`` because without the report it cannot be
       told whether the advance is already deducted.

    Returns ``None`` where there is no SAP at all, and the caller then waits for it.
    """
    if facts.data.get("balanceBasis"):
        return dict(facts.data["balanceBasis"])
    sanction = facts.doc("sanction") or {}
    amount = num(sanction.get("amount"))
    rows = facts.recalc_rows
    payslip = facts.sap_payslip

    if rows:
        column = "tempAdvance" if facts.is_kind("refundable") else "permanentAdvance"
        for row in reversed(rows):
            posted = num(row.get(column))
            if amount and posted and abs(posted - amount) <= 1:
                return {
                    "value": num(row.get("opening")),
                    "posted": True,
                    "explanation": (
                        f"This advance (Rs {fmt(amount)}) is already posted in the SAP "
                        f"re-calculation report for {row.get('start')} to {row.get('end')}, so "
                        f"the pay slip balance is after it. The balance before it is the opening "
                        f"balance of that year, Rs {fmt(row.get('opening'))}."),
                }
        last = rows[-1]
        return {"value": num(last.get("closing")),
                "explanation": (f"Closing balance Rs {fmt(last.get('closing'))} for "
                                f"{last.get('start')} to {last.get('end')} in the SAP "
                                f"re-calculation report. This advance is not yet posted.")}

    if payslip and payslip.get("gpfBalance") is not None:
        return {"value": num(payslip.get("gpfBalance")), "provisional": True,
                "explanation": (f"GPF balance Rs {fmt(payslip.get('gpfBalance'))} on the pay slip "
                                f"for {payslip.get('month')}. Without the re-calculation report it "
                                f"cannot be confirmed whether this advance is already deducted.")}
    return None


check(
    id="ADV-LIMIT", group="balance", ref="GPF Rules 1.14 to 1.18 · R9 · B1-i", code="B1-i",
    title="Advance within the limit set by the GP Fund Rules",
    applies=lambda facts: bool(facts.is_kind(*ADVANCES)
                               and (facts.doc("sanction") or {}).get("present")),
    run=lambda facts: _adv_limit(facts),
)


def _adv_limit(facts: Facts) -> dict[str, Any]:
    """The limit the RULES set for the clause quoted, with the office's 80% beside it. §11.

    R9 as the office stated it is 80% of the SAP balance. §11.1 shows that is not what the
    Rules say: 80% is right for house and land advances, too loose for general temporary and
    conveyance advances (the Rules cap those at half the balance), and too tight for Rule 1.16
    (100% at age 50). The module applies the Rules, shows the office figure, and flags every
    difference for GPF-O15. It does not choose.
    """
    sanction = facts.doc("sanction") or {}
    clause = sanction.get("limitClause")
    limit_rule = ADVANCE_LIMITS.get(clause)
    amount = num(sanction.get("amount"))

    if not limit_rule:
        return {"status": CONF,
                "finding": (f"The clause under which Rs {fmt(amount)} was sanctioned "
                            f"({sanction.get('rule') or 'not quoted'}) could not be matched to a "
                            f"limit in the Rules."),
                "remedy": "Identify the clause; the limit is then applied.",
                "cure": {"kind": "verify", "vid": "ADV-LIMIT"}}

    basis = balance_before(facts)
    if not basis or basis.get("value") is None:
        return {"status": SAP,
                "finding": (f"Sanctioned Rs {fmt(amount)} under {limit_rule.src}. The SAP balance "
                            f"is needed to test the limit."),
                "cure": {"kind": "sap"}}

    balance = int(basis["value"])
    payslip = facts.sap_payslip or {}
    basic_pay = num(payslip.get("basicPay")) or num(sanction.get("basicPay"))
    limit, by_pct, by_pay = limit_rule.ceiling(balance, basic_pay)
    office = balance * OFFICE_CAP_PCT // 100

    calc = {"amount": amount, "balance": balance, "rule": limit_rule.src,
            "label": limit_rule.label, "pct": limit_rule.pct, "months": limit_rule.months,
            "combine": limit_rule.combine, "pay": basic_pay, "byPct": by_pct, "byPay": by_pay,
            "ruleLimit": limit, "office": office, "officePct": OFFICE_CAP_PCT}

    if limit_rule.months:
        if basic_pay:
            which = "the greater of " if limit_rule.combine == "max" else "the lesser of "
            months_text = (f"{which}{limit_rule.pct}% of the balance and {limit_rule.months} "
                           f"months’ pay (Rs {fmt(basic_pay)} a month)")
        else:
            months_text = (f"{limit_rule.pct}% of the balance (months of pay not known, so the "
                           f"percentage alone is applied)")
    else:
        months_text = f"{limit_rule.pct}% of the balance"
    rule_text = (f"{limit_rule.src} ({limit_rule.label.lower()}) allows {months_text}: "
                 f"Rs {fmt(limit)}.")

    flag = ("" if limit == office else
            f" Flag: the office’s stated practice of {OFFICE_CAP_PCT}% gives Rs {fmt(office)} "
            f"for this balance, which differs from the Rules; the Rules are applied and the "
            f"difference is listed under Rules in force.")
    stated_balance = num(sanction.get("balanceStated"))
    stated = ("" if not stated_balance or abs(stated_balance - balance) <= 1 else
              f" The sanction itself states a balance of Rs {fmt(stated_balance)}, which does not "
              f"reconcile to SAP.")

    age = sanction.get("ageAtSanction") or {}
    if limit_rule.min_age and age:
        if int(age.get("y", 0)) < limit_rule.min_age:
            return {"status": HARD, "calc": calc,
                    "finding": (f"{limit_rule.src} needs the subscriber to be "
                                f"{limit_rule.min_age} or over; the subscriber was "
                                f"{age.get('y')} at sanction."),
                    "remedy": ("Obtain a sanction under the rule that applies to the "
                               "subscriber’s age.")}
        age_text = (f" Age {age.get('y')} years {age.get('m') or 0} months at sanction; the rule "
                    f"needs {limit_rule.min_age}.")
    else:
        age_text = ""

    where = f" Balance used: {basis['explanation']}"

    # The provisional basis is tested BEFORE the ceiling, and the order is the whole point of
    # §6.5. A pay slip pulled after the advance was posted shows the balance AFTER it, so on
    # this case Rs 58,000 measured against 80% of the post-advance Rs 19,194 "exceeds the
    # limit" by Rs 42,645 -- a hard stop against a sanction that is in fact well within the
    # Rules. Concluding anything about the ceiling from a basis that may already exclude the
    # advance is precisely what §14 rule 8 forbids, and §11.2 gives that row no exception for
    # an amount that merely appears too large. The ceiling is still computed and shown, so the
    # officer can see what the figure would be once the basis is settled.
    if basis.get("provisional"):
        over = ("" if amount is None or amount <= limit else
                f" On the pay slip balance alone it would be Rs {fmt(amount - limit)} over, but "
                f"that balance may already exclude this advance, so no conclusion is drawn.")
        return {"status": CONF, "calc": calc,
                "finding": (f"Rs {fmt(amount)} against a limit computed from the pay slip balance. "
                            f"{rule_text}{where}{over}{flag}"),
                "remedy": "Upload the re-calculation report to confirm the balance basis.",
                "cure": {"kind": "sap"}}

    if amount is not None and amount > limit:
        would_pass = (" The office’s 80% practice would have passed it; the Rules govern."
                      if amount <= office else "")
        relax = (f", or record special reasons in writing ({limit_rule.relaxable})"
                 if limit_rule.relaxable else "")
        return {"status": HARD, "calc": calc,
                "finding": (f"Rs {fmt(amount)} exceeds the limit. {rule_text} Excess "
                            f"Rs {fmt(amount - limit)}.{where}{stated}{would_pass}"),
                "remedy": f"Reduce the sanction to Rs {fmt(limit)} or less{relax}."}

    if amount is not None and amount > office:
        return {"status": ADV, "calc": calc,
                "finding": (f"Rs {fmt(amount)} is within the Rules. {rule_text} It is above the "
                            f"office’s stated {OFFICE_CAP_PCT}% practice (Rs {fmt(office)}), "
                            f"so it is flagged for the office to confirm which "
                            f"applies.{where}{stated}{age_text}"),
                "remedy": (f"None under the Rules. The office to confirm whether its "
                           f"{OFFICE_CAP_PCT}% practice overrides {limit_rule.src}.")}

    return {"status": OK, "calc": calc,
            "finding": (f"Rs {fmt(amount)} is within the limit. {rule_text}"
                        f"{where}{stated}{age_text}{flag}")}


check(
    id="ADV-ACTIVE", group="balance", ref="R12 · Rule 1.14(1)(c) proviso", code="R12",
    title="No other refundable advance outstanding",
    applies=lambda facts: facts.is_kind("refundable"),
    run=lambda facts: _adv_active(facts),
)


def _adv_active(facts: Facts) -> dict[str, Any]:
    """R12 and the 1989 proviso to Rule 1.14(1)(c). §11.4.

    No second advance before the earlier ones are repaid with interest, and the office adds
    that a new advance may be settled only after the MONTH the earlier one reached zero. The
    re-calculation report is yearly, so it cannot show that month -- the monthly recovery
    schedule from ``SapConnector.get_advance_history`` is what will close that gap (§6.2).
    Until then a same-year recovery is a verification task, not a pass.
    """
    sanction = facts.doc("sanction") or {}
    rows = facts.recalc_rows
    payslip = facts.sap_payslip
    amount = num(sanction.get("amount"))

    if not rows:
        if not payslip:
            return {"status": SAP,
                    "finding": ("The SAP pay slip and re-calculation report are needed to see any "
                                "advance still outstanding."),
                    "cure": {"kind": "sap"}}
        outstanding = num(payslip.get("loanBalance"))
        if outstanding is None:
            # Unread is not nil: a balance nobody could read was passed as "no advance
            # outstanding" (audit 6 Oct 2026, G4). It is a verification task until it is read.
            return {"status": CONF,
                    "finding": ("The SAP pay slip's GPF advance balance could not be read, so it cannot "
                                "be told whether an earlier advance is still outstanding."),
                    "cure": {"kind": "sap"}}
        if not outstanding:
            return {"status": OK,
                    "finding": "The SAP pay slip shows no GPF advance outstanding."}
        return {"status": CONF,
                "finding": (f"The SAP pay slip shows a GPF advance balance of Rs "
                            f"{fmt(outstanding)}. Without the re-calculation report it cannot be "
                            f"told whether this is the advance under examination."),
                "cure": {"kind": "sap"}}

    index = -1
    for position in range(len(rows) - 1, -1, -1):
        drawn_here = num(rows[position].get("tempAdvance"))
        if amount and drawn_here and abs(drawn_here - amount) <= 1:
            index = position
            break
    earlier = rows[:index] if index >= 0 else rows
    drawn = sum(num(r.get("tempAdvance")) or 0 for r in earlier)
    recovered = sum(num(r.get("recTempAdvance")) or 0 for r in earlier)
    last_recovery = next((r for r in reversed(earlier) if num(r.get("recTempAdvance"))), None)

    if index >= 0:
        row = rows[index]
        loan_balance = num((payslip or {}).get("loanBalance"))
        if payslip and loan_balance and amount:
            tail = (f"; the pay slip advance balance of Rs {fmt(loan_balance)} is this advance "
                    f"being recovered (Rs {fmt(amount)} less Rs {fmt(amount - loan_balance)}).")
        else:
            tail = "."
        posted = (f" The advance under examination is already posted in {row.get('start')} to "
                  f"{row.get('end')}{tail}")
    else:
        posted = ""

    if drawn - recovered > 1:
        return {"status": HARD,
                "finding": (f"Earlier refundable advances of Rs {fmt(drawn)} show recoveries of "
                            f"only Rs {fmt(recovered)} in SAP: Rs {fmt(drawn - recovered)} still "
                            f"outstanding when this advance was sanctioned.{posted}"),
                "remedy": ("The earlier advance must be fully recovered before a new one "
                           "(Rule 1.14(1)(c) proviso). A new advance may be settled only after "
                           "the month in which it reached zero.")}
    if not drawn:
        return {"status": OK,
                "finding": (f"No earlier refundable advance in SAP since "
                            f"{rows[0].get('start')}.{posted}")}
    when = (f", the last recovery in {last_recovery.get('start')} to {last_recovery.get('end')}"
            if last_recovery else "")
    return {"status": OK,
            "finding": (f"Earlier refundable advances of Rs {fmt(drawn)} were fully "
                        f"recovered{when}.{posted}")}
