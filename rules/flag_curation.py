"""Only the findings a reviewer must act on, each in one short line. Office rule, 30 Sep 2026.

The battery (rules.flags) raises everything it can see, with the full reasoning, and that stays
the audit record. What reaches the officer -- and what the recommendation, the gate and the
shortcoming letter count -- is curated here:

1.  **Only useful findings.** A finding is set aside when it needs no action: names that differ
    in spelling but match, roles the record settled itself, a statutory cap the engine applies
    anyway, a timeline breach that is no case defect, a finding about a paper the office does
    not require, or a note with nothing wrong in it. Set-aside findings are kept in the report
    (``flags_set_aside``) with the reason, never deleted. A HIGH finding is never set aside:
    whatever blocks a PPO is always shown.
2.  **No duplicates.** Findings of one kind that ask for the same action -- three family members
    Annex-A records differently, two stale certificates -- become one finding citing every page.
3.  **Short and plain.** Each finding carries ``summary``: one sentence, at most 15 words,
    "[problem] — [where]". The full finding and action stay beneath it for whoever needs them.
4.  **Most serious first**, and renumbered F-1, F-2 ... in that order.

The 5-finding display limit is the screen's: every curated finding still counts, because a
real finding hidden from the count would be a case approved over it.
"""
from __future__ import annotations

import re
from dataclasses import replace

from .flags import Flag, _doc_words
from .checklist import FOUND_NOT_REQUIRED, NOT_REQUIRED

MAX_WORDS = 15

#: Mismatches in name, CNIC, dates, amounts and eligibility come first (office rule).
_CLASS_ORDER = [
    "CONTRA-IDENTITY", "CNIC-UNCORROBORATED", "CONTRA-FAMILY", "CONTRA-DATE", "CONTRA-SERVICE-DATES", "CONTRA-MONEY",
    "RULE-UNDECLARED", "DECLARED-TYPE-MISMATCH", "RELATION-INELIGIBLE", "RELATIONSHIP-UNPROVED", "AUTH-DEFECT", "DOC-STALE",
    "DOC-EXPIRED", "EXTRACT-DISAGREE", "DATE-AMBIGUOUS", "EXTRACT-LOWCONF", "ATTEST-MISSING", "RULE-CAP", "SCOPE-CONFUSION",
]
_SEVERITY = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

#: Kinds that are, by what they are, a record rather than a problem.
_NO_ACTION_CLASSES = {"ALIAS-RESOLVED", "EXTRACT-ROLE-SWAP", "SLA-BREACH", "SCOPE-CONFUSION"}

#: The papers behind the checklist lines the office does not require, by document type.
_NOT_REQUIRED_DOCS = {"AG-16": {"SOLE_WIDOW_CERTIFICATE"}, "AG-19": {"LATE_SUBMISSION_REASON"},
                      "AG-23": {"PPO"}, "AG-24": {"BANK_FILE"}}


def _set_aside_reason(f: Flag, not_required_docs: set[str]) -> str | None:
    if f.severity == "HIGH":
        return None                                     # whatever blocks a PPO is always shown
    action = (f.required_action or "").strip().lower()
    if f.flag_class in _NO_ACTION_CLASSES:
        return "a record, not a problem: nothing for the reviewer to do"
    if action.startswith("none") or action.startswith("no case defect") or action.startswith("no action"):
        return "no action needed"
    if f.flag_class == "CNIC-UNCORROBORATED" and "neither party" in (f.title or "").lower():
        return "a doubt with no clear evidence: a witness's card is normal"
    cited = {s.document for s in (*f.asserted, *f.contradicted_by)}
    if cited and cited <= not_required_docs:
        return "about a paper the office does not require"
    return None


def _merge(group: list[Flag]) -> Flag:
    if len(group) == 1:
        return group[0]
    first = group[0]
    asserted, contradicted = [], []
    for f in group:
        asserted += [s for s in f.asserted if s not in asserted]
        contradicted += [s for s in f.contradicted_by if s not in contradicted]
    return replace(first, title=first.title, finding=" ".join(f.finding for f in group),
                   asserted=tuple(asserted), contradicted_by=tuple(contradicted),
                   affects_determination=any(f.affects_determination for f in group))


def _pages(sources) -> str:
    pages = sorted({s.page for s in sources})
    return ", ".join(f"p.{p}" for p in pages[:4]) + (" …" if len(pages) > 4 else "")


def _short_doc(doc: str) -> str:
    return _doc_words(doc).split(" — ")[0]


def _clip(text: str) -> str:
    words = text.split()
    if len(words) > MAX_WORDS:
        text = " ".join(words[:MAX_WORDS]).rstrip(",;:—-")
    text = text.strip()
    return text if text.endswith(".") else text + "."


def summary(f: Flag, merged: int = 1) -> str:
    """One plain sentence, at most 15 words: the problem, then where."""
    a = [_short_doc(s.document) for s in f.asserted]
    b = [_short_doc(s.document) for s in f.contradicted_by]
    both = list(dict.fromkeys(a + b))
    where = _pages((*f.asserted, *f.contradicted_by))
    t = (f.title or "").lower()
    c = f.flag_class
    if c == "CONTRA-IDENTITY":
        what = (f.title or "Details").split(" mismatch")[0].replace("-", " ").strip()
        return _clip(f"{what.capitalize()} differs between {' and '.join(both[:2]) or 'documents'}")
    if c == "CONTRA-FAMILY":
        n = f" ({merged} members)" if merged > 1 else ""
        return _clip(f"Family details on Annex-A differ from NADRA family certificate{n} — {where}")
    if c == "CONTRA-MONEY":
        if "lpc" in t and "differs" in t or "differ from the lpc" in t:
            return _clip(f"Pay component differs from the LPC — {' and '.join(b[:2]) or where}")
        if t.startswith("no lpc"):
            return _clip("No LPC pay lines read; check pay components against the LPC")
        return _clip(f"Pay figures do not add up on {' and '.join(both[:2]) or 'the form'}")
    if c == "RULE-UNDECLARED":
        amount = re.search(r"rs\.?\s*[\d,]+", t)
        return _clip(f"Recovery {amount.group(0).replace('rs', 'Rs') if amount else ''} on LPC not declared on sanction form".replace("  ", " "))
    if c == "CONTRA-DATE":
        return _clip(f"Dates on Form D-I cannot all be true — {where}")
    if c == "SERVICE-SHORT":
        return _clip(f"{f.title}; reviewer to apply QS-02 — {where}" if where else f.title)
    if c == "CONTRA-SERVICE-DATES":
        return _clip(f"Service dates differ between {' and '.join(both[:2]) or 'documents'}")
    if c == "DECLARED-TYPE-MISMATCH":
        return _clip("Declared case type does not match the sanction form")
    if c == "AUTH-DEFECT":
        return _clip(f"{f.title} — {where}" if where else f.title)
    if c == "DOC-STALE":
        return _clip(f"NADRA family certificate older than six months — {where}")
    if c == "DOC-EXPIRED":
        if t.startswith("check"):
            return _clip(f"CNIC expiry date unclear; check the card — {where}")
        return _clip(f"CNIC has expired — {where}")
    if c == "RELATION-INELIGIBLE":
        return _clip(f"{f.title} — {where}" if where else f.title)
    if c == "RELATIONSHIP-UNPROVED":
        if t.startswith("proof missing") or t.startswith("the claimant's relation"):
            return _clip(f"{f.title} — {where}" if where else f.title)
        return _clip("No document proves the claimant's relationship; no Nikah Nama on file")
    if c == "CNIC-UNCORROBORATED":
        if "misread" in t:
            return _clip(f"CNIC number on the card differs by one digit from the forms — {where}")
        return _clip(f"CNIC copy not matched to anyone in the case — {where}")
    if c == "EXTRACT-LOWCONF":
        return _clip(f"Page could not be read; read it yourself — {where}")
    if c == "EXTRACT-DISAGREE":
        return _clip(f"Two reads of the page disagree; read it yourself — {where}")
    if c == "DATE-AMBIGUOUS":
        return _clip(f"Date written with a two-digit year; confirm the century — {where}")
    if c == "ATTEST-MISSING":
        return _clip(f"Copies not attested by DDO — {where}")
    if c == "RULE-CAP":
        pct = re.search(r"(\d+(?:\.\d+)?)%", f.title or "")
        return _clip(f"Commutation asked above the Punjab limit{f' ({pct.group(1)}%)' if pct else ''} — Annex-A")
    return _clip(f"{f.title} — {where}" if where and "p." not in (f.title or "") else (f.title or ""))


def curate(flags: tuple[Flag, ...], checklist=None, variant: str | None = None) -> tuple[tuple[Flag, ...], list[dict]]:
    """The findings to show and count, in order, and the ones set aside with why."""
    not_required_docs: set[str] = set()
    if checklist is not None:
        for item in checklist.items:
            if item.status in (NOT_REQUIRED, FOUND_NOT_REQUIRED):
                not_required_docs |= _NOT_REQUIRED_DOCS.get(item.id, set())

    kept: list[Flag] = []
    set_aside: list[dict] = []
    for f in flags:
        why = _set_aside_reason(f, not_required_docs)
        if why:
            set_aside.append({**f.to_dict(), "set_aside": why})
        else:
            kept.append(f)

    # One finding per kind and action: the same problem on several pages or people is one line.
    groups: dict[tuple, list[Flag]] = {}
    for f in kept:
        groups.setdefault((f.flag_class, f.severity, f.required_action), []).append(f)
    merged = [(_merge(g), len(g)) for g in groups.values()]

    rank = {c: i for i, c in enumerate(_CLASS_ORDER)}
    merged.sort(key=lambda fm: (_SEVERITY.get(fm[0].severity, 3), rank.get(fm[0].flag_class, len(rank))))
    out = tuple(replace(f, id=f"F-{n}", summary=summary(f, count))
                for n, (f, count) in enumerate(merged, start=1))
    return out, set_aside
