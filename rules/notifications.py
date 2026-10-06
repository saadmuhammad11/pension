"""Notifications to departments and claimants. BRAIN §12.2, the five SOP classes.

Two audiences, two registers, the same facts.

**To the department** -- specific and actionable. Each defect names what is wrong, where it
was found, what the correct value appears to be, and what to do about it. Departments correct
faster when told exactly which field on which form, and every extra round trip is another
month a family waits.

**To the claimant** -- plain language, no rule citations, no form numbers, bilingual, and
explicit about whether they need to do anything. Most of the time they do not, and BRAIN §12.2
calls saying so "the single most valuable sentence in the message". Never imply blame: a
departmental error is not the claimant's failing.

Why this ships early
--------------------
BUILD §13 puts notifications in Phase 2 rather than last, and §10 says to start the SMS
gateway on day one, for a reason that is not technical. The SOP's own objective is to
"eradicate the role of the middle man", and middlemen exist because pensioners cannot see
their own case and cannot tell whether a delay is normal. Every clear status message removes
a reason to pay someone for information that should be free.

On the Urdu
-----------
The Urdu here is assembled from fixed templates with only names, numbers and counts
substituted -- never free-composed. Templated text can be reviewed once by a native speaker
and then trusted; generated prose cannot. Department names are carried as data on the case
record rather than transliterated, because an automatic transliteration of an arbitrary
department name will eventually be wrong in a message read by a bereaved family.

**The Urdu strings in this module have not yet been reviewed by a native Urdu speaker.
That review is required before any message goes to a real claimant.**
"""

from __future__ import annotations

from dataclasses import dataclass

from .caserecord import CaseRecord
from .checklist import SELF_PENSION_VARIANTS, Checklist, DEFECTIVE, MISSING
from .flags import Flag
from .verdict import HOLD, RETURN_FOR_CORRECTION, Recommendation

# -- the five classes the SOP mandates notification on -----------------------------------------
PAYMENT_PROCESSED = "PAYMENT_PROCESSED"
PAYMENT_DELAYED = "PAYMENT_DELAYED"
ADDITIONAL_DOCUMENTS_REQUIRED = "ADDITIONAL_DOCUMENTS_REQUIRED"
CASE_RETURNED = "CASE_RETURNED"
CASE_HOLD = "CASE_HOLD"

DEPARTMENT = "DEPARTMENT"
CLAIMANT = "CLAIMANT"

#: Counts one to ten in Urdu words. Beyond ten the digits are used, which reads naturally in
#: Urdu and avoids inflection mistakes a lookup table would introduce.
_URDU_COUNTS = {
    1: "ایک", 2: "دو", 3: "تین", 4: "چار", 5: "پانچ",
    6: "چھ", 7: "سات", 8: "آٹھ", 9: "نو", 10: "دس",
}


#: Counts one to ten in English words. §12.2 requires plain language for the claimant, and
#: "Three corrections are needed" reads as a sentence where "3 corrections" reads as a form.
_ENGLISH_COUNTS = {
    1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
    6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
}


def _count_ur(n: int) -> str:
    return _URDU_COUNTS.get(n, str(n))


def _count_en(n: int) -> str:
    return _ENGLISH_COUNTS.get(n, str(n))


@dataclass(frozen=True)
class Notification:
    """One message, ready for the SMS/email gateway.

    ``body_ur`` is populated only for claimant-facing messages: §12.2 requires bilingual
    text for the pensioner, while departmental correspondence is in English, which is the
    working language of the offices involved.
    """

    recipient_class: str
    notification_class: str
    subject: str
    body_en: str
    body_ur: str | None = None
    requires_recipient_action: bool = False
    channel: str = "SMS+EMAIL"

    @property
    def bilingual(self) -> bool:
        return bool(self.body_ur)

    def to_dict(self) -> dict:
        return {
            "recipient_class": self.recipient_class,
            "notification_class": self.notification_class,
            "channel": self.channel,
            "subject": self.subject,
            "body_en": self.body_en,
            "body_ur": self.body_ur,
            "bilingual": self.bilingual,
            "requires_recipient_action": self.requires_recipient_action,
        }


def _classify(checklist: Checklist, recommendation: Recommendation) -> str:
    """Pick the SOP class. §7.3's MISSING/DEFECTIVE split decides which letter goes out.

    A missing document asks the department to *send* something
    (``ADDITIONAL_DOCUMENTS_REQUIRED``); a defective one, or a data contradiction, asks it to
    *correct* something (``CASE_RETURNED``). Sending the wrong one costs a round trip.
    """
    if recommendation.verdict == HOLD:
        return CASE_HOLD
    if any(i.status == MISSING for i in checklist.items):
        return ADDITIONAL_DOCUMENTS_REQUIRED
    return CASE_RETURNED


def _shortcomings(
    checklist: Checklist | None, flags: tuple[Flag, ...]
) -> tuple[list[Flag], list, list]:
    """What the department is actually being asked to put right: flags, missing, defective.

    One definition, used by both letters. The claimant's message used to count only the
    HIGH department flags while the department's counted those plus the checklist items,
    so a case returned purely for missing documents told the claimant "0 corrections are
    needed" -- and three flags beside two missing papers told them "Three". The two
    letters describe one set of shortcomings and now count one set.
    """
    actionable = [f for f in flags if f.owner == DEPARTMENT and f.blocks_ppo]
    missing = [i for i in checklist.items if i.status == MISSING] if checklist else []
    defective = [i for i in checklist.items if i.status == DEFECTIVE] if checklist else []
    return actionable, missing, defective


def notify_department(
    record: CaseRecord,
    checklist: Checklist,
    flags: tuple[Flag, ...],
    recommendation: Recommendation,
) -> Notification:
    """The shortcoming report. Itemised, with page references and the correct value.

    Only defects the department can act on are listed. A ``RULE-CAP`` flag is the AG applying
    a statutory cap and an ``SLA-BREACH`` is a dashboard matter -- putting either in a
    shortcoming letter would ask a department to "correct" something that is not wrong.
    """
    diary = record.diary_no or record.case_ref
    dept = record.forwarding_department or "the forwarding department"
    actionable, missing, defective = _shortcomings(checklist, flags)

    lines = [
        f"Pension case diary {diary} - shortcomings identified on AI-assisted scrutiny.",
        "",
        f"Checklist: {checklist.result_line}",
        "",
    ]

    if actionable:
        lines.append(f"{len(actionable)} item(s) require correction before a PPO can issue:")
        lines.append("")
        for f in actionable:
            pages = ", ".join(f"p.{s.page}" for s in sorted(f.asserted, key=lambda s: s.page))
            lines.append(f"  [{f.id}] {f.title}")
            lines.append(f"        Finding : {f.finding}")
            if pages:
                lines.append(f"        Where   : {pages}")
            lines.append(f"        Action  : {f.required_action}")
            lines.append("")

    if missing:
        lines.append("Documents not located in the bundle:")
        for i in missing:
            lines.append(f"  [{i.id}] {i.requirement}")
        lines.append("")

    if defective:
        lines.append("Documents present but defective:")
        for i in defective:
            lines.append(f"  [{i.id}] {i.requirement} - {i.reason}")
        lines.append("")

    lines.append(
        "On resubmission the case is automatically revalidated and diffed against this "
        "submission, so only the changes need review."
    )

    return Notification(
        recipient_class=DEPARTMENT,
        notification_class=_classify(checklist, recommendation),
        subject=f"Pension case {diary}: {len(actionable) + len(missing) + len(defective)} shortcoming(s) - action required",
        body_en="\n".join(lines).rstrip(),
        requires_recipient_action=True,
        channel="EMAIL",
    )


def notify_claimant(
    record: CaseRecord,
    flags: tuple[Flag, ...],
    recommendation: Recommendation,
    checklist: Checklist | None = None,
) -> Notification:
    """The claimant's message. Bilingual, plain, and explicit about whether they must act.

    No rule ids, no flag ids, no form numbers, no rupee figures -- a provisional amount that
    later changes would be worse than no amount at all. The one thing this message must get
    across is whether the person needs to do anything.

    ``checklist`` is optional only so the signature stays compatible; ``notify`` always
    supplies it, and without it the count below cannot see missing or defective documents.
    """
    diary = record.diary_no or record.case_ref
    dept_en = record.forwarding_department or "the forwarding department"
    dept_ur = record.forwarding_department_ur or dept_en

    # A self pension is the pensioner's own, and calling it a family pension in a message
    # to the person who earned it is wrong in the one line they are certain to read. The
    # Urdu drops the same word: "فیملی" is the English "family" as a loanword, so removing
    # it leaves the reviewed phrase intact rather than composing a new one.
    self_pension = record.case_variant in SELF_PENSION_VARIANTS
    kind_en = "pension" if self_pension else "family pension"
    kind_ur = "پنشن" if self_pension else "فیملی پنشن"
    opening_en = f"Your {kind_en} case (diary {diary}) has been checked."
    opening_ur = f"آپ کے {kind_ur} کیس (ڈائری نمبر {diary}) کا جائزہ لے لیا گیا ہے۔"

    claimant_actions = [f for f in flags if f.owner == CLAIMANT]
    needs_action = bool(claimant_actions)
    n = sum(len(group) for group in _shortcomings(checklist, flags))

    # A returned case with nothing for the department to fix is returned on a finding the
    # AG owns -- an unreadable page, say, which blocks the PPO and which no department can
    # correct. Counting it at the department's door would be both wrong and, at n == 0,
    # absurd: "0 corrections are needed from the School Education Department". Such a case
    # is with an officer, so it is described that way, reusing the wording below rather
    # than inventing a fourth message.
    if recommendation.verdict == RETURN_FOR_CORRECTION and not needs_action and n:
        corrections_en = (
            "One correction is" if n == 1 else f"{_count_en(n)} corrections are"
        )
        body_en = (
            f"{opening_en} "
            f"{corrections_en} needed from {dept_en}; they have been informed today. "
            f"No action is required from you."
        )
        body_ur = (
            f"{opening_ur} "
            f"{dept_ur} سے {_count_ur(n)} تصحیحات درکار ہیں؛ انہیں آج مطلع کر دیا گیا ہے۔ "
            f"آپ کو کوئی کارروائی کرنے کی ضرورت نہیں۔"
        )
    elif needs_action:
        what_en = "; ".join(f.required_action for f in claimant_actions)
        body_en = (
            f"{opening_en} "
            f"We need something from you to continue: {what_en} "
            f"Please contact the pension office if anything is unclear."
        )
        body_ur = (
            f"{opening_ur} "
            f"کارروائی جاری رکھنے کے لیے ہمیں آپ سے کچھ درکار ہے۔ "
            f"براہِ کرم پنشن دفتر سے رابطہ کریں۔"
        )
    elif recommendation.verdict in (HOLD, RETURN_FOR_CORRECTION):
        body_en = (
            f"{opening_en} It is with an "
            f"officer for a decision. No action is required from you. "
            f"You will be informed as soon as there is an update."
        )
        body_ur = (
            f"{opening_ur} یہ فیصلے کے "
            f"لیے افسر کے پاس ہے۔ آپ کو کوئی کارروائی کرنے کی ضرورت نہیں۔ "
            f"کوئی پیش رفت ہوتے ہی آپ کو مطلع کر دیا جائے گا۔"
        )
    else:
        body_en = (
            f"{opening_en} It is moving "
            f"forward for approval. No action is required from you."
        )
        body_ur = (
            f"{opening_ur} یہ منظوری کے "
            f"لیے آگے بھیج دیا گیا ہے۔ آپ کو کوئی کارروائی کرنے کی ضرورت نہیں۔"
        )

    return Notification(
        recipient_class=CLAIMANT,
        notification_class=(
            CASE_HOLD if recommendation.verdict == HOLD else CASE_RETURNED
        ),
        subject=f"Pension case {diary} - status update",
        body_en=body_en,
        body_ur=body_ur,
        requires_recipient_action=needs_action,
        channel="SMS",
    )


def notify(
    record: CaseRecord,
    checklist: Checklist,
    flags: tuple[Flag, ...],
    recommendation: Recommendation,
) -> tuple[Notification, ...]:
    """Both messages for one case, department first."""
    return (
        notify_department(record, checklist, flags, recommendation),
        notify_claimant(record, flags, recommendation, checklist),
    )
