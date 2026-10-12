"""JSON schemas for schema-constrained document extraction.

Every request to the vision model carries one of these as
``response_format={"type": "json_schema", ...}``. This is not a convenience:

  Measured on source page 42 of the golden case (the densest page in the file)
    free-form "return JSON" prompt   6000 output tokens, truncated, INVALID
    response_format json_schema       867 output tokens, valid

The free-form failure mode was specific and instructive. Asking for
``amounts_rs: [int]`` ("every rupee figure on the page") let the model place a
phone number in the array -- ``03000000001`` -- and JSON forbids leading zeros,
so one character invalidated an entire page's extraction.

Two rules follow, and both are load-bearing:

1.  An identifier is a STRING, never an integer. A CNIC, IBAN, personnel
    number or phone number is not a quantity. Typing them numerically loses
    leading zeros and invites the model to enumerate digit runs as money.
2.  Monetary figures are LABELLED, never pooled into a bare array. Given an
    unlabelled bucket the model mislabels: on Form D-I it offered the bank
    account number as "Gratuity", the date of birth as "Recovery", and basic
    pay as "GPF". Constraining shape does not constrain semantics -- only a
    per-document-type field list does that.

AGPB-BRAIN §5.3 (extraction discipline), §6 (output schema).
"""

from __future__ import annotations

from typing import Any

# --- shared fragments -------------------------------------------------------------------------

_CONF = {
    "type": "number",
    "description": "Your own 0-1 confidence in this value. Not a formality: "
                   "<0.80 routes to human verification and is never silently accepted.",
}


def _value(desc: str, kind: str = "string") -> dict[str, Any]:
    """A value that may be null. Never omitted, never invented (BRAIN §5.3).

    'Never interpolate. If the basic pay is illegible, the field is null with a
    reason. A plausible reconstruction is worse than an honest gap, because a
    gap gets checked and a plausible number gets paid.'
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "confidence", "unreadable_reason"],
        "properties": {
            "value": {"type": [kind, "null"], "description": desc},
            "confidence": _CONF,
            "unreadable_reason": {
                "type": ["string", "null"],
                "description": "Why the value could not be read. Required when value is null.",
            },
        },
    }


#: A CNIC and WHOSE it is. A bare list of numbers cannot be checked: the sanction form
#: quotes the deceased's and the claimant's on the same page, the bank form adds two
#: witnesses, and the FRC lists a whole household. Without the name beside each number there
#: is no way to say that one person's CNIC is consistent across the case, nor to notice that
#: an attached card belongs to somebody else entirely.
_CNIC_HOLDER = {
    "type": "object",
    "additionalProperties": False,
    "required": ["number", "person", "role"],
    "properties": {
        "number": {
            "type": "string", "maxLength": 20,
            "description": "The CNIC exactly as printed, separators and all.",
        },
        "person": {
            "type": ["string", "null"], "maxLength": 80,
            "description": "The name printed WITH this number -- immediately beside it, or "
                           "in the same table row, or the subject of the sentence that "
                           "quotes it. null if the page gives a number with no name.",
        },
        "role": {
            "type": ["string", "null"], "maxLength": 40,
            "description": "What THIS page calls that person, verbatim: 'deceased', "
                           "'applicant', 'widow', 'son', 'witness', 'attesting officer', "
                           "'agent'. null if the page does not say. Do not infer a role "
                           "from the pension context -- report the word on the page.",
        },
        # Only a CARD prints these. A form quoting a number does not, and the answer there is
        # null -- never a date copied from elsewhere on the page.
        "date_of_issue": {
            "type": ["string", "null"], "maxLength": 12,
            "description": "On a CNIC CARD: the 'Date of Issue' as YYYY-MM-DD. null on any "
                           "other page, and null where the card does not print one.",
        },
        "date_of_expiry": {
            "type": ["string", "null"], "maxLength": 12,
            "description": "On a CNIC CARD: the 'Date of Expiry' as YYYY-MM-DD, or the word "
                           "LIFETIME where the card prints 'Lifetime'. null on any other "
                           "page, and null where the card does not print one.",
        },
    },
}

_IDENTIFIERS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cnic", "personnel_no", "ppo_no", "iban", "account_no", "phone"],
    "properties": {
        "cnic": {
            "type": "array",
            "maxItems": 10,
            "items": _CNIC_HOLDER,
            "description": "Every CNIC printed on the page, each with the person it belongs "
                           "to. A page quoting two people's numbers yields two entries.",
        },
        **{
            k: {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string", "maxLength": 40},
                "description": f"Every distinct {k} printed on the page, verbatim, as a string.",
            }
            for k in ("personnel_no", "ppo_no", "iban", "account_no", "phone")
        },
    },
    "description": "Identifiers are strings. Do not normalise, do not strip separators, "
                   "do not coerce to a number.",
}

# The six reckonable components, per Note 2 of every prescribed form (BRAIN §9.3, EMOL-01..06),
# plus orderly allowance (EMOL-07). Nothing else is reckonable, however large.
RECKONABLE_COMPONENTS = (
    "basic_pay",
    "special_pay",
    "personal_pay",
    "qualification_pay",
    "technical_pay",
    "senior_post_allowance",
    "orderly_allowance",
)

_PAY_COMPONENT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["printed_label", "line_kind", "amount_rs", "confidence"],
    "properties": {
        "printed_label": {
            "type": "string",
            "maxLength": 80,
            "description": "The row's label EXACTLY as printed, including any code, percentage "
                           "and year -- e.g. 'Adhoc Relief All 2023 30%'. Just the label, not the "
                           "surrounding sentence.",
        },
        "line_kind": {
            "type": "string",
            "enum": ["pay_or_allowance", "deduction", "printed_total", "recovery"],
            "description": "What KIND of row this is on the page. This is a layout judgement, "
                           "not a policy one: is it an individual pay/allowance row, a "
                           "deduction, a printed Gross/Total line, or a recoverable amount?",
        },
        "amount_rs": {
            "type": ["integer", "null"],
            # This said "null where the row shows a dash or blank", which put the schema in
            # direct conflict with the majority-amounts-null guard in extraction/client.py.
            # A prescribed form is a PRO-FORMA: Form D-I prints six pay slots and the
            # department strikes a dash through the ones that do not apply, so on the real
            # golden case four of six are dashes. Obeying the old instruction produced a
            # read that was a MAJORITY nulls -- correctly, by its own lights -- and the
            # guard then rejected the page and cost the case its determination. The rows
            # were discarded downstream in any event: pipeline.extract._pay_components
            # drops every component whose amount is null before anything sums them.
            "description": "Whole rupees as printed. Do NOT emit a row at all where the "
                           "form shows a dash, a blank or no figure against the label -- an "
                           "unused slot on a pro-forma is not a pay component. Use null only "
                           "where a figure IS printed but you cannot read it.",
        },
        "confidence": _CONF,
    },
    "description": (
        "One row of the printed pay table, transcribed verbatim.\n\n"
        "Note what the model is NOT asked: whether the row is RECKONABLE for pension. That was "
        "tried and failed three ways on one real page -- duplicating 13,590 into both special and "
        "personal pay; routing every allowance into an 'other' bucket; then, with that bucket "
        "removed, routing them into 'special_pay', which is reckonable and would have inflated "
        "pensionable pay by 161,765. It also emitted component='special_pay' with "
        "reckonable=false, contradicting itself. Removing every discriminating field instead made "
        "the array a junk drawer: the model began dumping whole paragraphs as labels.\n\n"
        "So the split is: `line_kind` is a layout question the model answers reliably; "
        "reckonability is a rules question fixed by Note 2 of the prescribed forms, decided in "
        "deterministic code (extraction.classify.classify_pay_label) that an officer can review "
        "and that cannot drift. BRAIN §9.3 calls that split 'the most consequential extraction "
        "judgement you make' -- which is precisely why a model does not make it."
    ),
}


_LABELLED_AMOUNT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["printed_label", "amount_rs", "confidence"],
    "properties": {
        "printed_label": {"type": "string", "maxLength": 80,
                          "description": "The label exactly as printed."},
        "amount_rs": {"type": "integer"},
        "confidence": _CONF,
    },
}


def _envelope(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    base_props = {
        "doc_type": {"type": "string"},
        "identifiers": _IDENTIFIERS,
        "dates_iso": {
            "type": "array",
            "maxItems": 20,
            "items": {"type": "string", "maxLength": 12},
            "description": "Every date on the page as YYYY-MM-DD. Keep the raw form in "
                           "raw_strings if the printed form is ambiguous.",
        },
        "raw_strings": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "maxLength": 90},
            "description": "Verbatim strings for any value you normalised, so an auditor can "
                           "see the original glyphs (BRAIN §5.3 'preserve what you saw').",
        },
        "document_date": _value(
            "The date this document was SIGNED or ISSUED, as printed on it. Not a date it "
            "merely mentions -- a form that refers to a death in 2021 but is signed in 2026 "
            "has document_date 2026. null if no signing or issue date is printed."
        ),
        "person_name": _value(
            "The government servant or pensioner this document concerns, exactly as printed "
            "here. Spelling varies between documents; reproduce what THIS page says and do "
            "not normalise it to match another document."
        ),
        "unreadable": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "maxLength": 140},
            "description": "Everything you could not read confidently, and why. Report "
                           "occlusion by a stamp rather than guessing the covered digits.",
        },
    }
    base_props.update(props)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["doc_type", "identifiers", "dates_iso", "raw_strings", "unreadable",
                     "document_date", "person_name", *required],
        "properties": base_props,
    }


# --- per-document-type schemas ----------------------------------------------------------------

FORM_D_I = _envelope(
    {
        "pay_components": {"type": "array", "maxItems": 24, "items": _PAY_COMPONENT},
        "total_pay_printed_rs": {
            "type": ["integer", "null"],
            "description": "The 'Total Pay Rs.' figure AS PRINTED on the form. Do not compute it "
                           "and do not correct it -- it is the independent check against the sum "
                           "of the components you extracted (BRAIN §8.4).",
        },
        "deceased_name": _value("Name of the deceased government servant"),
        "claimant_name": _value("Name of the family-pension claimant"),
        "claimant_relation": _value("Claimant's relation to the deceased, as printed"),
        # Asks for the PRINTED TOKEN, not a bare integer. Asked for an integer the model
        # returned 12 at confidence 1.00 on a page that prints "in BS-19, drawing pay
        # Rs: 178440/" -- it had taken the 12 from the adjacent date "12-10-2021"
        # (2026-09-04). A bare number is unverifiable; a quoted token has to match
        # BS-?\d{1,2} in code, and "12-10-2021" does not. BPS is determination-critical: it
        # selects the medical-allowance rate (25% below BS-16, 20% at BS-16 and above).
        "pay_scale_printed": _value(
            "The pay scale EXACTLY as printed, including its prefix -- 'BS-19', 'BPS-17'. "
            "Quote the token; never infer a scale from the pay amount and never report a "
            "number that is not printed beside BS/BPS.",
        ),
        "date_of_birth": _value("Date of birth, YYYY-MM-DD"),
        "date_first_entry": _value("Date of first entry into government service, YYYY-MM-DD"),
        "date_of_death": _value("Date of death, YYYY-MM-DD"),
        "eol_availed": _value("Extraordinary leave availed, as printed"),
        "qualifying_service_printed": _value("Length of service exactly as printed on the form"),
        "recovery_declared": _value("What clause 5 says about demand/recovery, verbatim"),
        # There is deliberately NO psa_signature_date field. One was added here to give the
        # 15-day sanction SLA an end date, because the model had returned Form D-I's
        # notification date (12-10-2021) as the document's own date. Asking for the signature
        # date instead produced 2021-07-26 at high confidence -- a date that appears nowhere
        # on the page, three days before the date of death. The form's signature block is
        # genuinely undated, and a required field over an absent fact does not obtain the
        # fact; it obtains a plausible invention. The SLA is now computed from dates that
        # are printed (see pipeline/report.py), and the missing signature date is reported
        # as missing.
        "signatory": _value("Name and designation of the signing Pension Sanctioning Authority"),
        "key_amounts": {"type": "array", "maxItems": 12, "items": _LABELLED_AMOUNT},
    },
    [
        # Every determination-critical field is REQUIRED, so the model must answer with
        # {value, confidence, unreadable_reason} rather than emitting null for the whole
        # object. Left optional, it did exactly that on the real Form D-I (2026-09-04):
        # date_of_birth, date_first_entry and date_of_death all came back null although the
        # page plainly prints "date of Birth was 19-02-1966" and "first entry ... 08-12-1993".
        # A null object carries no reason, so BRAIN §5.3's "null with a reason" discipline --
        # the thing that makes a gap checkable -- was silently unenforceable.
        "pay_components", "total_pay_printed_rs", "key_amounts",
        "deceased_name", "claimant_name", "claimant_relation", "pay_scale_printed",
        "date_of_birth", "date_first_entry", "date_of_death", "eol_availed",
        "qualifying_service_printed", "recovery_declared", "signatory",
    ],
)

# Fields taken from the two real D-II pages in the bundles, NOT copied from D-I. The two
# forms ask different questions because they describe different events: D-I describes a
# servant who died while serving, so it asks for pay components, qualifying service and EOL.
# D-II describes a PENSIONER who died, so there is no pay table on it at all -- it states the
# pension the deceased was already drawing, and that single figure is the base the family
# pension is computed on.
#
# Two layouts, one schema. The widow bundle carries a printed pro-forma headed "Form D-II /
# FAMILY PENSION FORM"; the divorced-daughter bundle carries the same instrument typed as an
# OFFICE ORDER headed "Proforma D-II". The numbered clauses correspond, so the fields below
# are worded to find either.
FORM_D_II = _envelope(
    {
        # -- the deceased pensioner -----------------------------------------------------
        "deceased_pensioner_name": _value("Name of the deceased PENSIONER (clause 1)"),
        "designation_at_retirement": _value(
            "Designation at the time of retirement, as printed -- e.g. 'Forester', "
            "'Assistant General Foreman'"),
        "pay_scale_printed": _value(
            "The pay scale EXACTLY as printed, including its prefix -- 'BS-09', 'BPS-05'. "
            "Quote the token; never infer a scale from an amount."),
        # THE determination-critical figure on this form. On D-I the base is built from a pay
        # table; here it is stated outright and there is nothing to reconcile it against on
        # the page, so it is asked for on its own and carries its own confidence.
        "pension_drawn_rs": {
            "type": ["integer", "null"],
            "description": "The pension the deceased pensioner was DRAWING, in whole rupees, "
                           "as printed at clause 1 beside 'drawing pension/family pension @' "
                           "or 'having drawing Pension @'. This is the figure the family "
                           "pension is computed on. Do not compute it, do not take it from a "
                           "pension slip elsewhere in the bundle, and do not confuse it with "
                           "the 'Net Pension' or 'Total pension' lines below.",
        },
        "net_pension_rs": {
            "type": ["integer", "null"],
            "description": "The 'Net Pension' figure as printed, or null where the form "
                           "leaves it blank.",
        },
        "total_pension_rs": {
            "type": ["integer", "null"],
            "description": "The 'Total pension Rs.' figure as printed, or null.",
        },
        "orderly_allowance_rs": {
            "type": ["integer", "null"],
            "description": "Orderly allowance at clause 2, in whole rupees. null where the "
                           "form says NIL or leaves it blank -- NIL is not zero rupees "
                           "read off the page, it is the absence of an entitlement.",
        },
        "ppo_no": _value("PPO / FPPO number of the deceased pensioner, as printed"),
        "pensioner_id": _value("Pensioner ID, where the form prints one"),
        "deceased_cnic": _value("CNIC of the deceased pensioner, as printed"),
        "bank_of_deceased": _value("Bank and branch the deceased drew the pension from"),
        "date_of_birth": _value("Date of birth of the deceased pensioner, YYYY-MM-DD"),
        "date_of_retirement": _value("Date of retirement from government service, YYYY-MM-DD"),
        "date_of_death_of_pensioner": _value(
            "Date the PENSIONER died ('expired on'), YYYY-MM-DD"),

        # -- the prior family pensioner: what makes a case a RE-GRANT --------------------
        # The divorced-daughter form opens on the WIDOW, who was herself drawing a family
        # pension and has since died. Two deaths on one form is the signature of a re-grant,
        # and it is a different rule from a first grant. Asked for explicitly so the case
        # class rests on a field rather than on parsing prose.
        "prior_family_pensioner_name": _value(
            "Where the form describes a person who was ALREADY drawing the family pension "
            "and has since died -- typically the widow -- give their name. null where the "
            "form describes only the original pensioner."),
        "prior_family_pensioner_ppo": _value(
            "The PPO/FPPO the prior family pensioner was drawing on, where stated"),
        "date_of_death_of_prior_pensioner": _value(
            "Date the PRIOR family pensioner died, YYYY-MM-DD. null where there is no prior "
            "family pensioner on this form."),

        # -- the claimant ----------------------------------------------------------------
        "claimant_name": _value("Name of the person now claiming the family pension"),
        "claimant_relation": _value(
            "The claimant's relation to the DECEASED PENSIONER exactly as the form words it "
            "-- 'widow', 'divorce daughter', 'unmarried daughter', 'parent'. Quote the "
            "form; do not normalise it and do not infer it from a name."),
        "claimant_cnic": _value("CNIC of the claimant, as printed"),
        "claimant_bank_account": _value("Account the family pension is to be credited to"),
        "date_of_divorce": _value(
            "Where the claimant is a divorced daughter, the date the divorce took effect, "
            "YYYY-MM-DD. null otherwise."),

        "recovery_declared": _value(
            "What the demand/recovery clause says, verbatim"),
        "authority_cited": _value(
            "Any Finance Department letter or rule the form cites as the authority for the "
            "entitlement, verbatim -- e.g. 'FD-SR-III-4-57/2013 dated 15-05-2013'"),
        "signatory": _value(
            "Name and designation of the signing Pension Sanctioning Authority"),
        "key_amounts": {"type": "array", "maxItems": 12, "items": _LABELLED_AMOUNT},
    },
    [
        # Required for the same reason as on D-I: left optional the model returns a bare null
        # for the whole object, which carries no reason, and BRAIN §5.3's "null with a
        # reason" discipline becomes unenforceable exactly where it matters.
        "deceased_pensioner_name", "designation_at_retirement", "pay_scale_printed",
        "pension_drawn_rs", "net_pension_rs", "total_pension_rs", "orderly_allowance_rs",
        "ppo_no", "pensioner_id", "deceased_cnic", "bank_of_deceased",
        "date_of_birth", "date_of_retirement", "date_of_death_of_pensioner",
        "prior_family_pensioner_name", "prior_family_pensioner_ppo",
        "date_of_death_of_prior_pensioner",
        "claimant_name", "claimant_relation", "claimant_cnic", "claimant_bank_account",
        "date_of_divorce", "recovery_declared", "authority_cited", "signatory",
        "key_amounts",
    ],
)

AG_PAY_CERTIFICATE = _envelope(
    {
        "pay_components": {
            "type": "array",
            "maxItems": 24,
            "items": _PAY_COMPONENT,
            "description": "Every printed pay/allowance/deduction line, verbatim, including "
                           "any Gross or Total lines. Code separates line items from totals by "
                           "label; you only transcribe.",
        },
        "gross_printed_rs": {
            "type": ["integer", "null"],
            "description": "The 'Gross Pays and Allowance' figure AS PRINTED. Do not compute it. "
                           "It is the independent check on the line items you extracted.",
        },
        "total_deductions_printed_rs": {
            "type": ["integer", "null"],
            "description": "The 'Total Deductions' figure AS PRINTED. Do not compute it.",
        },
        "key_amounts": {
            "type": "array",
            "maxItems": 12,
            "items": _LABELLED_AMOUNT,
            "description": "Labelled monetary figures: gross pay and allowances, total "
                           "deductions, and any ROP / recovery amount with its period.",
        },
        "recovery_note": _value(
            "Any recoverable amount with its period, verbatim. The recovery field on an "
            "LPC/AG certificate is a high-yield defect source: departments routinely certify "
            "'no demand' on the sanction while the certificate shows a recovery (BRAIN §8.4)."
        ),
    },
    # recovery_note is REQUIRED. Left optional it was returned on one sweep and silently
    # dropped on the next, once two new required fields were added to the envelope and the
    # model's output budget shifted. That single omission removed F-3 -- the undeclared
    # Rs. 126,355 recovery, which BRAIN §13.8 calls "the one that costs money" -- from the
    # case entirely, and the report still looked healthy with five flags. A field that decides
    # a HIGH flag must force an answer, even if the answer is null with a reason.
    ["pay_components", "gross_printed_rs", "total_deductions_printed_rs", "key_amounts",
     "recovery_note"],
)

DESCRIPTIVE_ROLL = _envelope(
    {
        "family_members": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "relation", "cnic", "dob_or_age", "marital_status",
                             "confidence"],
                "properties": {
                    "name": {"type": "string"},
                    "relation": {"type": ["string", "null"],
                                 "description": "As printed. Do not correct it against NADRA -- "
                                                "the contradiction is the finding (BRAIN §8.3)."},
                    "cnic": {"type": ["string", "null"]},
                    "dob_or_age": {"type": ["string", "null"]},
                    "marital_status": {"type": ["string", "null"]},
                    "confidence": _CONF,
                },
            },
        },
        "commutation_pct_opted": _value("Commutation percentage opted, if the form states one",
                                        "number"),
        "attested_by": _value("Who attested the proforma (PSA or DDO)"),
    },
    ["family_members"],
)

NADRA_FRC = _envelope(
    {
        "family_members": DESCRIPTIVE_ROLL["properties"]["family_members"],
        "certificate_no": _value("Certificate or registration number"),
    },
    ["family_members"],
)

#: The Pension Payment Order, and the pension slip that restates it. BRAIN §8.3 makes the
#: PPO/FPPO the AUTHORITY on "existing pension in payment", above any restatement -- and
#: FAM-AR-01 computes a family pension "from the pension in payment as stated on the PPO/FPPO
#: and Form D-II". The unmarried-daughter bundle proves why both are read: the department left
#: every money field of its Form D-II blank, and the figure the determination needs was
#: printed on seven PPO pages in the same file.
PPO = _envelope(
    {
        "pensioner_name": _value("Name of the pensioner the order is issued for"),
        "ppo_no": _value("PPO / FPPO number, as printed"),
        "monthly_pension_rs": {
            "type": ["integer", "null"],
            "description": "The MONTHLY pension this order authorises, in whole rupees -- "
                           "the 'net pension', 'monthly pension' or 'pension per month' "
                           "figure. Not the commuted lump sum, not arrears, not a yearly "
                           "total. null where the page states no monthly figure.",
        },
        "gross_pension_rs": {
            "type": ["integer", "null"],
            "description": "The GROSS pension before commutation, where the order states it "
                           "separately, in whole rupees. null otherwise.",
        },
        "medical_allowance_rs": {
            "type": ["integer", "null"],
            "description": "Medical allowance per month where stated separately. null "
                           "otherwise; it is NOT added into the pension figures above.",
        },
        "commencement_date": _value("Date the pension commences / was sanctioned, YYYY-MM-DD"),
        "is_family_pension": {
            "type": ["boolean", "null"],
            "description": "true where this order authorises a FAMILY pension (an FPPO), "
                           "false where it authorises the pensioner's own pension, null "
                           "where the page does not say.",
        },
    },
    ["monthly_pension_rs"],
)

GENERIC_PAGE = _envelope(
    {
        "summary": {"type": "string", "description": "One line: what this page is."},
        # On the forwarding letter this is the department whose delay the SLA flag names and
        # whose name goes at the top of a shortcoming letter. It was a hardcoded string --
        # "the School Education Department" -- until this field replaced it.
        "issuing_office": _value(
            "The office or department that ISSUED this document, as printed in its letterhead "
            "or above the signature -- the 'Government of ... Department' or 'Office of the "
            "...' line, reproduced as printed. null if the page carries no issuing office."
        ),
        "fields": {
            "type": "array",
            "maxItems": 24,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "value", "confidence"],
                "properties": {
                    "label": {"type": "string", "maxLength": 80},
                    "value": {"type": ["string", "null"], "maxLength": 200},
                    "confidence": _CONF,
                },
            },
        },
        "key_amounts": {"type": "array", "maxItems": 12, "items": _LABELLED_AMOUNT},
    },
    ["summary", "issuing_office", "fields", "key_amounts"],
)

# --- page identity (pipeline stage 3) ---------------------------------------------------------

#: The closed set of document types the bundle can contain. Closed on purpose: an open string
#: field invites the model to invent a plausible near-miss ("Form D1", "Death Cert") that no
#: downstream lookup matches, and the checklist would then report a document missing that is
#: sitting in the file. A page that fits nothing is OTHER, which routes to a human -- never a
#: newly coined type.
DOCUMENT_TYPES = (
    # PSA-prescribed forms. These decide the case type (BRAIN §4.1 rule 1).
    "FORM_B_I", "FORM_B_II", "FORM_B_III", "FORM_B_IV", "FORM_D_I", "FORM_D_II",
    "ANNEX_A",
    # NADRA / identity
    "NADRA_DEATH_CERTIFICATE", "NADRA_FRC", "CNIC",
    "SUCCESSION_CERTIFICATE",
    # pay and service
    "LPC", "SALARY_STATEMENT", "SERVICE_STATEMENT", "SERVICE_BOOK", "POSTING_ORDER",
    "DEPUTATION_CHALLANS", "PPO", "FPPO",
    # departmental
    "FORWARDING_LETTER", "DEATH_OFFICE_ORDER", "NDC", "COMPULSORY_RETIREMENT_ORDER",
    "NAME_CHANGE_ORDER",
    "MEDICAL_BOARD_CERTIFICATE", "SUPERANNUATION_ORDER", "VOLUNTARY_RETIREMENT_REQUEST",
    # claimant-supplied
    "PHOTOGRAPHS", "SPECIMEN_SIGNATURES", "BANK_OPTION_FORM", "NON_REMARRIAGE_CERTIFICATE",
    "MATRIC_CERTIFICATE",
    # required by the AG office checklist of 2026 (Document Checklist.pdf). Until these were
    # added, a bundle could carry an affidavit or a sole-widow certificate and the checklist
    # line for it could never be satisfied: the enum is closed, so the classifier physically
    # could not name the document.
    "SOLE_WIDOW_CERTIFICATE", "NO_REGULAR_INCOME_CERTIFICATE",
    "ARREARS_ENTITLEMENT_CERTIFICATE", "LATE_SUBMISSION_REASON",
    "DIVORCE_CERTIFICATE", "NIKAH_NAMA", "AFFIDAVIT", "BANK_FILE", "COMMUTATION_OPTION",
    "LIFE_CERTIFICATE", "PENSION_SLIP",
    # found unclassified in real bundles: both are service-record papers the office files
    "CHARGE_REPORT", "CHARACTER_SERVICE_ROLL",
    # The AG office's proforma for qualifying service (scope change C2, 12 Oct 2026): a one-page
    # summary of the service record, certified by the office and verified by the AG/DAO, that
    # stands in for the service book on the checklist (decision S3).
    "QUALIFYING_SERVICE_PROFORMA",
    "PENSION_APPLICATION", "DEPARTMENTAL_CHECKLIST",
    # structural
    "FILE_COVER", "OTHER",
)

#: What each token means in the words actually printed on the page. Without this the model
#: reads the heading correctly and still picks the wrong token: on 2026-09-04 a page headed
#: "LAST PAY CERTIFICATE" was answered OTHER while quoting that exact heading as its evidence.
#: An enum constrains shape, not semantics -- the gloss is what constrains semantics.
DOCUMENT_TYPE_GLOSS = {
    "FORM_B_I": "printed 'FORM B-I' - superannuation or retiring pension sanction",
    "FORM_B_II": "printed 'FORM B-II' - anticipatory pension sanction",
    "FORM_B_III": "printed 'FORM B-III' - final pension after anticipatory",
    "FORM_B_IV": "printed 'FORM B-IV' - invalid or compulsory-retirement pension sanction",
    "FORM_D_I": "printed 'FORM D-I' - family pension where the servant died IN SERVICE",
    "FORM_D_II": "printed 'FORM D-II' or 'Proforma D-II' - family pension where a "
                 "RETIRED pensioner died while drawing pension",
    "FORM_D_II": "printed 'FORM D-II' - family pension where a PENSIONER died",
    "ANNEX_A": "'Annexure-A' / Descriptive Roll, with undertaking and commutation option",
    "NADRA_DEATH_CERTIFICATE": "NADRA death certificate / death registration certificate",
    "NADRA_FRC": "NADRA 'Family Registration Certificate' listing family members",
    "CNIC": "a CNIC card copy — say WHOSE in person_named; do not guess the role",
    "SUCCESSION_CERTIFICATE": "succession certificate defining heirs' shares in the estate",
    "LPC": "'Last Pay Certificate' issued by AG/DAO",
    "SALARY_STATEMENT":
        "computerised monthly salary slip or pay statement for a SERVING servant - basic pay "
        "with allowances (house rent, conveyance, medical, washing) and deductions (GPF "
        "subscription, group insurance, income tax). May be headed 'pension slip' when issued "
        "for a pension case; the pay lines decide, not the heading",
    "SERVICE_STATEMENT": "AG-issued service statement or posting profile for a gazetted servant",
    "SERVICE_BOOK":
        "any page of the SERVICE BOOK - the bound manual service record of a NON-GAZETTED "
        "servant, usually decades old, handwritten in English and Urdu, and running to many "
        "pages. Recognise it by any of these, not by the words 'service book':\n"
        "     * a first page of numbered particulars - Name, Nationality and Religion, "
        "Residence, Father's name and residence, Date of birth, Exact height by measurement, "
        "Personal mark for identification, Left hand thumb and finger-impressions, Signature "
        "of Government servant, Signature of the Head of the Office;\n"
        "     * a service-history table with the columns 'Name of post', 'Whether substantive "
        "or officiating and whether permanent or temporary', 'Pay in substantive post', "
        "'Additional pay for officiating', 'Other emoluments falling under the term Pay', "
        "'Date of appointment', 'Date of termination of appointment', 'Signature and "
        "designation of the Head of the Office ... in attestation';\n"
        "     * a leave account, or pages of pay-fixation entries attested by the DDO.\n"
        "     Interior pages carry no title and are still SERVICE_BOOK. Some are printed "
        "sideways or bear a printed form number of their own - neither makes the page a "
        "pension sanction form",
    "POSTING_ORDER": "any departmental service order about this servant — recruitment, appointment, joining, posting, transfer, promotion or re-adjustment — INCLUDING a continuation page of one that carries no heading of its own",
    "DEPUTATION_CHALLANS": "treasury challans proving deposit of pension contributions during deputation",
    "PPO": "Pension Payment Order",
    "FPPO": "Family Pension Payment Order",
    "FORWARDING_LETTER": "ONLY the covering letter that transmits this pension case to the Accountant General. A departmental order about the servant is a POSTING_ORDER, not a forwarding letter, however letter-like it looks",
    "DEATH_OFFICE_ORDER": "departmental office order or obituary notifying a death",
    "NDC": "'No Demand Certificate' / No Enquiry / No Audit Para / No Punishment certificate",
    "COMPULSORY_RETIREMENT_ORDER": "orders imposing compulsory retirement as a penalty",
    "MEDICAL_BOARD_CERTIFICATE": "Category-A medical board invalidation certificate",
    "SUPERANNUATION_ORDER":
        "an order or notification retiring a servant on reaching superannuation age. Often "
        "headed 'SUPERANNUATION NOTIFICATION' and worded 'the following officials will be "
        "retired from Government service on attaining the age of superannuation'. It is a "
        "retirement ORDER, not a pension sanction form - a page saying this is not Form B-I",
    "VOLUNTARY_RETIREMENT_REQUEST": "the servant's own request for voluntary retirement",
    "PHOTOGRAPHS": "attested photographs of the claimant",
    "SPECIMEN_SIGNATURES": "specimen signatures and/or thumb impressions",
    "BANK_OPTION_FORM": "bank account option form, usually with an indemnity bond",
    "NON_REMARRIAGE_CERTIFICATE": "Union Council non-marriage / non-remarriage certificate or affidavit",
    "NAME_CHANGE_ORDER": "an order recording a change of the servant's name",
    "MATRIC_CERTIFICATE": "an educational certificate, e.g. matriculation",
    "FILE_COVER": "the case file cover sheet or index",
    "SOLE_WIDOW_CERTIFICATE":
        "certificate that the claimant is the sole/lawful widow or widower of the deceased, "
        "on department letterhead, verified by the DDO",
    "NO_REGULAR_INCOME_CERTIFICATE":
        "certificate that the claimant has no regular or independent source of income, signed by "
        "the PSA, WHATEVER its title: 'No Regular Source of Income', 'Non Source of Income', "
        "'No Source of Income', 'No Income Certificate', 'Certificate of No Regular Income', or "
        "the same in Urdu",
    "ARREARS_ENTITLEMENT_CERTIFICATE":
        "'entitlement of arrears' certificate signed by the PSA, on department letterhead",
    "LATE_SUBMISSION_REASON":
        "the DDO's stated reason for submitting the case late (more than three years)",
    "DIVORCE_CERTIFICATE": "computerised divorce certificate, NADRA or Union Council",
    "NIKAH_NAMA":
        "computerised marriage registration certificate / Nikah Nama, filed where the "
        "applicant is not shown in the FRC",
    "AFFIDAVIT":
        "a sworn affidavit / solemn declaration by a deponent. Headed 'AFFIDAVIT' or, in "
        "Urdu, 'بیان حلفی' (bayan-e-halfi). Printed on judicial or non-judicial stamp paper "
        "- often an e-stamp header giving Amount Rs 50/- or Rs 100/-, Applicant, Vendor and "
        "Issue Date - and attested below by an OATH COMMISSIONER, usually the round stamp of "
        "an advocate. The declaration itself is frequently handwritten or typed IN URDU; "
        "classify from the heading and the oath-commissioner stamp, not from being able to "
        "read the body",
    "BANK_FILE":
        "the original bank file or 'bank half' of the pension record, or the bank's letter "
        "where it has been misplaced",
    "COMMUTATION_OPTION":
        "the pensioner's written option for commutation of pension",
    "LIFE_CERTIFICATE":
        "printed 'Form-C' - life certificate, the periodic declaration that the pensioner "
        "is alive",
    "PENSION_APPLICATION":
        "printed 'FORM 3 (PEN)' or headed 'APPLICATION FOR PENSION AND / OR GRATUITY' - the "
        "application the retiring servant fills in and signs themselves, addressed to the "
        "Accountant General. It is an APPLICATION, not a sanction: the prescribed forms "
        "(B-I, B-II, B-III, B-IV, D-I, D-II) are issued by the PSA, this one is not",
    "DEPARTMENTAL_CHECKLIST":
        "the department's own 'CHECK LIST FOR PENSION CASES' - a list of the papers the "
        "department believes it has enclosed, with ticks or page numbers against them",
    "CHARGE_REPORT":
        "'Charge Report' - the form on which an officer reports assuming or handing over "
        "charge of a post, giving the post, the office and the date",
    "QUALIFYING_SERVICE_PROFORMA":
        "the one-page proforma headed 'PERFORMA FOR QUALIFYING SERVICE FOR PENSION' (often "
        "'PROPOSED PERFORMA ...', sometimes spelt 'PROFORMA'), with the sections 'PARTICULARS OF "
        "EMPLOYEE', 'SERVICE RECORD SUMMARY' and 'PAY FIXATION', and at the foot a block 'For Use "
        "in the Accountant General/District Accounts Office' signed by an Accounts Officer. It "
        "says '(As Per Service Book)' and mentions the service book, but it is NOT a page of the "
        "service book: it is a printed form filled in by the office",
    "CHARACTER_SERVICE_ROLL":
        "'Character and Service Roll' / 'Character Roll' - the departmental service record of "
        "a non-gazetted servant, carrying a photograph, personal particulars, the posting "
        "history and a declaration. Serves as the service record where no service book is filed",
    "PENSION_SLIP":
        "a slip for a pension ALREADY IN PAYMENT to a pensioner: net pension, increases, "
        "medical allowance, and a PPO or FPPO number. Decide from the pay lines, not the "
        "heading -- a Punjab pay slip issued for a pension case may be headed 'PENSION SLIP' "
        "and still be a serving servant's salary. If it shows GPF subscription, house rent "
        "allowance, conveyance allowance or a pay grade, it is a SERVING employee's monthly "
        "salary and the answer is SALARY_STATEMENT",
    "OTHER": "fits none of the above - use this rather than inventing a type",
}

#: Deliberately NOT built on _envelope(). The envelope forces identifiers, dates_iso,
#: raw_strings and unreadable onto every response, which is right for field extraction and
#: wrong here: on a dense page those arrays alone blew a 512-token budget and the client
#: correctly refused the truncated read (source page 24, 2026-09-04). Identification needs six
#: fields, so it asks for six.
PAGE_IDENTITY: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["document_type", "document_type_confidence", "evidence",
                 "printed_form_number", "person_named", "is_first_page_of_document",
                 "signed_by_psa", "attested", "other_documents_on_page"],
    "properties": {
        # A department photocopies two or three certificates onto one sheet -- a death
        # certificate beside the FRC, a sole-widow and a no-income certificate on one sworn
        # page. document_type can name only one, so the rest were never registered and the
        # checklist reported them MISSING while they sat in the bundle.
        "other_documents_on_page": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string",
                      "enum": [t for t in DOCUMENT_TYPES if t != "OTHER"]},
            "description": "Every OTHER separate document printed on this same page, each "
                           "with its own heading or its own card/certificate layout, besides "
                           "the one in document_type. Empty if the page carries one "
                           "document. Never a document the page only mentions or asks for.",
        },
        "document_type": {
            "type": "string",
            "enum": list(DOCUMENT_TYPES),
            "description": "Which document this page belongs to. Use the mapping given in "
                           "the instruction. OTHER if it fits none -- never invent a type.",
        },
        "document_type_confidence": _CONF,
        "evidence": {
            "type": "string",
            "maxLength": 160,
            "description": "The printed heading, form number or stamp you identified it by. "
                           "Quote it; do not describe the page.",
        },
        "is_first_page_of_document": {
            "type": "boolean",
            "description": "True if this page carries the document's heading or form number. "
                           "A continuation page is False. Page order does not imply document "
                           "boundaries.",
        },
        "printed_form_number": {
            "type": ["string", "null"],
            "maxLength": 12,
            "description": "If a PSA-prescribed form number is PRINTED on the page, quote it "
                           "exactly as printed (e.g. 'D-I', 'B-IV', 'FORM D-I'). null if no "
                           "form number is printed. A page that is merely ABOUT family "
                           "pension has no form number.",
        },
        "person_named": {
            "type": ["string", "null"],
            "maxLength": 80,
            "description": "For a document that belongs to ONE person -- a CNIC card, a "
                           "photograph page, a certificate -- the person's name exactly as "
                           "printed on it. null otherwise. Do not infer a role from it: "
                           "whether this is the deceased or the claimant is decided "
                           "elsewhere, from the case record.",
        },
        "signed_by_psa": {
            "type": ["boolean", "null"],
            "description": "Prescribed forms only: a signature with name, date and stamp of "
                           "the Principal Accounting Officer or delegate? null if not a "
                           "prescribed form.",
        },
        "attested": {
            "type": ["boolean", "null"],
            "description": "Is there an attestation stamp or signature? null if not applicable.",
        },
    },
}


#: A CNIC card, read as the card it is. Deliberately NOT built on ``_envelope()``, for the
#: same reason ``PAGE_IDENTITY`` is not: the envelope forces ``fields`` (up to 24 of them),
#: ``raw_strings``, ``dates_iso`` and ``key_amounts`` onto every response. A card prints
#: every field TWICE -- once in English, once in Urdu -- beside a QR code and a signature
#: block, so a model asked to enumerate its fields enumerates for a very long time. On a
#: real scan it emitted 4,096 tokens and was truncated, three attempts running, and the
#: confirming double read correctly refused all three. The card was legible throughout; the
#: schema asked a question with no end to it.
#:
#: What a card holds is fixed and small. Asking for exactly that bounds the answer.
CNIC_CARD: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["doc_type", "identifiers", "person_name", "identity_number",
                 "father_or_husband_name", "date_of_birth", "unreadable"],
    "properties": {
        "doc_type": {"type": "string"},
        # Kept because the pipeline collects CNICs from here on every document type, and a
        # card is the one page whose number is beyond argument.
        "identifiers": _IDENTIFIERS,
        "person_name": _value(
            "The HOLDER's name, printed under 'Name'. Not the father's or husband's name, "
            "which is printed under its own label directly beneath."
        ),
        "identity_number": {
            "type": ["string", "null"], "maxLength": 20,
            "description": "The Identity Number exactly as printed, separators and all -- "
                           "00000-0000000-0. Never pad or complete it to reach 13 digits: if "
                           "any digit is illegible, report null and say so in unreadable.",
        },
        "father_or_husband_name": {
            "type": ["string", "null"], "maxLength": 80,
            "description": "The name under 'Father Name' or 'Husband Name'. This person is a "
                           "RELATION of the holder and has a card of their own with a "
                           "different number; the number on THIS card is not theirs.",
        },
        "relation_printed": {
            "type": ["string", "null"], "maxLength": 20,
            "description": "Which label that name appears under: 'Father Name' or "
                           "'Husband Name', as printed.",
        },
        "date_of_birth": {"type": ["string", "null"], "maxLength": 12,
                          "description": "As printed, e.g. 08.06.1982."},
        "date_of_issue": {"type": ["string", "null"], "maxLength": 12},
        "date_of_expiry": {
            "type": ["string", "null"], "maxLength": 20,
            "description": "As printed. Some cards state 'Lifetime' rather than a date.",
        },
        "gender": {"type": ["string", "null"], "maxLength": 12},
        "attested_by": {
            "type": ["string", "null"], "maxLength": 120,
            "description": "Where an officer has signed and stamped this photocopy, the "
                           "office named in that stamp -- 'Principal Scientist, Soil Water "
                           "Testing Laboratory' -- as printed. null where the page carries "
                           "only the holder's own signature, which certifies nothing.",
        },
        "unreadable": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "maxLength": 120},
            "description": "Anything on the card you could not read confidently, and why.",
        },
    },
}


#: The signature block of a prescribed form: who signed as Pension Sanctioning Authority, in
#: what post, for which department, and what the stamp says (pipeline.signatory). Read so the
#: signature can be compared with the specimen the department sent the AG for that post.
PSA_SIGNATURE_BLOCK = {
    "type": "object",
    "additionalProperties": False,
    "required": ["signature_present", "stamp_present", "signature_box", "signer_name",
                 "designation", "department", "stamp_text", "date_signed"],
    "properties": {
        "signature_present": {
            "type": "boolean",
            "description": "Is there a handwritten signature in the sanctioning authority's "
                           "signature block (the footer over 'Pension Sanctioning Authority' "
                           "or the officer's designation)? Not the pensioner's signature.",
        },
        "stamp_present": {
            "type": "boolean",
            "description": "Is an officer's rubber stamp printed with, or beside, that signature?",
        },
        "signature_box": {
            "type": ["array", "null"], "minItems": 4, "maxItems": 4, "items": {"type": "integer"},
            "description": "Where the sanctioning authority's signature AND its stamp are on the "
                           "page, as [x1, y1, x2, y2] on a 0-1000 scale of the page's width and "
                           "height. null if there is no such signature.",
        },
        "signer_name": _value("The signing officer's name, as printed or stamped under the signature."),
        "designation": _value("The signing officer's designation as stamped or printed, e.g. "
                              "'Additional Secretary (Admn.)'."),
        "department": _value("The department named in that signature block or stamp, e.g. "
                             "'S&GAD'."),
        "stamp_text": _value("The words of the officer's stamp, line by line joined with ' / '."),
        "date_signed": _value("The date written beside the sanctioning authority's signature, "
                              "YYYY-MM-DD. null if none is written there."),
    },
}


#: The proforma for qualifying service (scope change C2, 12 Oct 2026). Only the facts the
#: cross-document checks compare are asked for -- the particulars that identify the servant and
#: the dates that bound the service -- read with the confirming double read like every other
#: identifier page. The service-record summary is read as the office states it and compared with
#: nothing: no qualifying service is computed (rules/scope.py).
QUALIFYING_SERVICE_PROFORMA = _envelope(
    {
        "employee_name": _value("I. Name of Employee, as written"),
        "father_or_husband_name": _value("II. Father's Name / Husband's Name, as written"),
        "cnic": _value("III. CNIC Number exactly as written, 00000-0000000-0. null if any digit "
                       "is illegible -- never complete it"),
        "designation_at_retirement": _value("V. Designation (at retirement), as written"),
        "personnel_no": _value("VIII. Personnel Number, digits only as written; null where blank"),
        "date_of_birth": _value("IX. Date of Birth, YYYY-MM-DD"),
        "date_of_appointment": _value("X. Date of Appointment, YYYY-MM-DD"),
        "date_of_superannuation": _value("XI. Date of Superannuation, YYYY-MM-DD"),
        "date_of_retirement_or_death": _value(
            "XII. Date of Retirement / Death, YYYY-MM-DD"),
        "type_of_retirement_ticked": _value(
            "XIII. The box TICKED in 'Type of Retirement': Superannuation, Retiring, "
            "Invalid/Medical, Death or Other, exactly one word. null if none is ticked"),
        "total_length_of_service": _value(
            "SERVICE RECORD SUMMARY I. Total Length of Service, as written (e.g. '37 years 17 days')"),
        "net_qualifying_service": _value(
            "SERVICE RECORD SUMMARY VIII. Net Qualifying Service, as written; null where blank"),
        "office_certificate_signed": {
            "type": ["boolean", "null"],
            "description": "Whether the PAY FIXATION certificate ('It is certified that pay "
                           "fixation ... is complete in all respect') carries a signature or "
                           "stamp of the office. null if the page is cut off there.",
        },
        "ag_verification_signed": {
            "type": ["boolean", "null"],
            "description": "Whether the block 'For Use in the Accountant General/District "
                           "Accounts Office' is filled in and signed by the Accounts Officer / "
                           "District Accounts Officer. false where it is blank.",
        },
    },
    ["employee_name", "father_or_husband_name", "cnic", "designation_at_retirement", "personnel_no",
     "date_of_birth", "date_of_appointment", "date_of_superannuation", "date_of_retirement_or_death",
     "type_of_retirement_ticked", "total_length_of_service", "net_qualifying_service",
     "office_certificate_signed", "ag_verification_signed"],
)


SCHEMAS: dict[str, dict[str, Any]] = {
    "QUALIFYING_SERVICE_PROFORMA": QUALIFYING_SERVICE_PROFORMA,
    "PSA_SIGNATURE_BLOCK": PSA_SIGNATURE_BLOCK,
    "PAGE_IDENTITY": PAGE_IDENTITY,
    "CNIC_CARD": CNIC_CARD,
    "FORM_D_I": FORM_D_I,
    "FORM_D_II": FORM_D_II,
    "AG_PAY_CERTIFICATE": AG_PAY_CERTIFICATE,
    "DESCRIPTIVE_ROLL": DESCRIPTIVE_ROLL,
    "NADRA_FRC": NADRA_FRC,
    "PPO": PPO,
    "GENERIC_PAGE": GENERIC_PAGE,
}
