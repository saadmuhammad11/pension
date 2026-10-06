"""Deterministic classification of a printed pay label into its canonical component.

Why this is code and not a model call
-------------------------------------
The reckonable set is a closed list fixed by Note 2 of every prescribed form (BRAIN §9.3,
``EMOL-01``..``EMOL-07``). Deciding whether a printed line falls inside it is therefore a rules
decision with a rupee consequence, not a reading task -- and BRAIN §9.3 calls it "the most
consequential extraction judgement you make". On the golden case the excluded allowances total
161,765 against reckonable pay of 192,030: misfiling one allowance inflates a pension for life.

Asking the vision model to do it was tried on source page 29 and failed three ways:

  1. duplicated 13,590 into both ``special_pay`` and ``personal_pay`` (form prints a dash for
     special pay), giving a reckonable sum of 205,620 against a printed 192,030;
  2. with an ``other`` bucket available, routed every allowance into it;
  3. with that bucket removed, routed them into ``special_pay`` -- which is RECKONABLE -- while
     simultaneously emitting ``reckonable: false``, contradicting itself.

The trap is structural, not a model defect. "Special Allow 2021 25%" is an *allowance* and is not
reckonable; "Special Pay" is a *pay component* and is. The two labels differ by one word. A
curated table gets this right every time and can be reviewed by an officer; a model cannot be
audited and cannot be pinned.

Unknown labels are never guessed and never summed -- they raise a finding.
"""

from __future__ import annotations

import re

RECKONABLE = frozenset({
    "basic_pay", "special_pay", "personal_pay", "qualification_pay",
    "technical_pay", "senior_post_allowance", "orderly_allowance",
})

#: Non-line-item categories: excluded from any line-item sum so that a printed total can serve
#: as an independent check on the lines.
NOT_LINE_ITEMS = frozenset({"printed_total", "deduction", "recovery", "unknown"})

# Order matters: the FIRST match wins, so the specific traps come before the generic patterns.
# Every entry cites why it lands where it does.
_RULES: tuple[tuple[str, str, str], ...] = (
    # --- traps: an allowance whose name contains a reckonable component's name ---------------
    (r"special\s*allow(ance)?\b.*\b(19|20)\d{2}", "non_reckonable_allowance",
     "'Special Allowance <year>' is an allowance, NOT the 'special pay' of Note 2."),
    (r"\bsenior\s*post\s*allow", "senior_post_allowance",
     "Senior post allowance IS reckonable (EMOL-06)."),
    (r"\borderly\s*allow", "orderly_allowance",
     "Orderly allowance is reckonable where admissible (EMOL-07)."),

    # --- printed totals: never summed, used as the check -------------------------------------
    (r"^\s*(gross|total)\b", "printed_total", "A printed total, not a line item."),
    (r"\b(gross\s*pays?|total\s*pay|total\s*deduction|net\s*pay)\b", "printed_total",
     "A printed total, not a line item."),

    # --- recovery / demand -------------------------------------------------------------------
    (r"\b(rop\b|recover|demand\s*due)", "recovery",
     "A recoverable amount. LPC recoveries are a high-yield defect source (BRAIN §8.4)."),

    # --- deductions --------------------------------------------------------------------------
    (r"\b(income\s*tax|gpf|g\.?p\.?\s*fund|benevolent|group\s*insur|advance|loan|"
     r"subscription|deduct)", "deduction", "A deduction, not an emolument."),

    # --- the six reckonable components of Note 2 ---------------------------------------------
    (r"\bbasic\s*pay", "basic_pay", "EMOL-01."),
    (r"\bpersonal\s*pay", "personal_pay", "EMOL-03."),
    (r"\bqualification\s*pay", "qualification_pay", "EMOL-04."),
    (r"\btechnical\s*pay", "technical_pay", "EMOL-05."),
    (r"\bspecial\s*pay\b", "special_pay",
     "EMOL-02 -- reached only after the 'Special Allowance <year>' rule above has been tried."),

    # --- known non-reckonable allowances -----------------------------------------------------
    (r"\b(house\s*rent|hra)\b", "non_reckonable_allowance", "Not in Note 2."),
    (r"\bmedical\b", "non_reckonable_allowance", "Not in Note 2."),
    (r"\b(convey|transport)", "non_reckonable_allowance", "Not in Note 2."),
    (r"\badhoc\b|\bad[- ]?hoc\b", "non_reckonable_allowance",
     "Ad-hoc relief is not reckonable, however large."),
    (r"\b(dearness|integrated|washing|entertain|utilit|charge\s*allow|"
     r"computer\s*allow|mobile)", "non_reckonable_allowance", "Not in Note 2."),
)


def classify_pay_label(printed_label: str) -> dict[str, object]:
    """Map a printed pay label to its canonical component. Never guesses.

    Returns a dict with ``component``, ``reckonable``, ``is_line_item``, ``basis`` and
    ``needs_human``. An unrecognised label yields ``component='unknown'`` with
    ``needs_human=True``: it is excluded from sums and must be resolved by an officer, because
    silently treating an unknown allowance as non-reckonable would understate a pension and
    treating it as reckonable would overstate one.
    """
    label = re.sub(r"\s+", " ", printed_label or "").strip()
    lowered = label.lower()

    for pattern, component, basis in _RULES:
        if re.search(pattern, lowered):
            return {
                "component": component,
                "reckonable": component in RECKONABLE,
                "is_line_item": component not in NOT_LINE_ITEMS,
                "basis": basis,
                "needs_human": False,
            }

    return {
        "component": "unknown",
        "reckonable": False,
        "is_line_item": False,
        "basis": f"No rule matches {label!r}. Not classified, not summed.",
        "needs_human": True,
    }
