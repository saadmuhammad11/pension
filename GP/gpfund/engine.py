"""The rules engine. Build specification §0, §4.4, §7, §15.

    The language model never decides anything. It reads. The rules decide, from facts.

Nothing in this module or the rule modules it loads reads an image, calls a model, opens a
socket, looks at the clock or draws a random number. A check is a pure function from
:class:`~gpfund.contracts.Facts` to results, so:

* re-evaluating the same facts gives the same results (§0 rule 5, §17);
* swapping the reading model cannot change a case outcome given the same facts (§0 rule 4);
* a case can be re-checked against the rule set in force when it was examined (§15).

The evaluation cycle, from §0 and §7: an uploaded document, an SAP extract or an officer's
verification changes the FACTS; the whole case is then evaluated again from the start and
compared with the previous run. *The same rule that raised an observation closes it.* There
is deliberately no mark-as-resolved path, because one would drift from the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .contracts import (
    ADV,
    CONF,
    HARD,
    NA,
    OK,
    SAP,
    SUB,
    Evidence,
    Facts,
    Lists,
    Result,
    is_open,
)

#: The four versioned parts of the rule set, §15. A case is always re-checked against the
#: rule set in force when it was examined, so a determination carries this whole block and
#: not just a number.
RULE_SET_VERSION: dict[str, str] = {
    "circular": "G.P. Fund-I (Coord)/TR/127 of 21.12.2023",
    "rules": "Punjab General Provident Fund Rules 1978, Compendium 2008",
    "office_clarifications": "R1 to R15, AG Punjab, 15-09-2026",
    "parameters": "gpfund.params, revision 2 (15-09-2026)",
    "module": "gpfund 2.0",
}


# -- the check registry ---------------------------------------------------------------------

@dataclass(frozen=True)
class Check:
    """One rule. §5.

    ``applies`` decides whether the check has anything to say about this case; ``run`` says
    what. ``run`` returns one partial result, a list of them, or ``None`` where another check
    carries the finding instead.

    A partial result is a mapping rather than a :class:`Result` so a check states only what
    it decided -- status, finding, remedy -- and the registry fills in the identity (id, ref,
    code, title, group) from the check itself. That keeps a check from accidentally reporting
    under another check's reference.
    """

    id: str
    title: str
    group: str
    ref: str
    applies: Callable[[Facts], bool]
    run: Callable[[Facts], Any]
    code: str = ""
    checklist: str | Callable[[Facts], str | None] | None = None

    def checklist_item(self, facts: Facts) -> str | None:
        if callable(self.checklist):
            return self.checklist(facts)
        return self.checklist


#: Checks that apply across families and by family (§5.1 to §5.5), in registration order.
CHECKS: list[Check] = []

#: Case-specific checks, attached by the reading stage through ``facts.custom_checks`` (§5).
#: Registered here so each has an id, a ref and a code like any other check, and so §14 rule 2
#: holds: nothing is raised outside the circular, the Rules or the office clarifications
#: without a recorded justification, which such a check carries in its ``ref``.
CUSTOM_CHECKS: dict[str, Check] = {}


def check(**kwargs: Any) -> Check:
    """Register a check that applies across families or to a family."""
    entry = Check(**kwargs)
    if any(existing.id == entry.id for existing in CHECKS):
        raise ValueError(f"check {entry.id!r} is registered twice")
    CHECKS.append(entry)
    return entry


def custom_check(**kwargs: Any) -> Check:
    """Register a case-specific check, referenced by id from the facts."""
    entry = Check(**kwargs)
    if entry.id in CUSTOM_CHECKS:
        raise ValueError(f"custom check {entry.id!r} is registered twice")
    CUSTOM_CHECKS[entry.id] = entry
    return entry


def checks_for(facts: Facts) -> tuple[Check, ...]:
    """Every check that will be evaluated on this case, in order."""
    extra = [CUSTOM_CHECKS[name] for name in facts.custom_checks if name in CUSTOM_CHECKS]
    return tuple(CHECKS) + tuple(extra)


def unknown_custom_checks(facts: Facts) -> tuple[str, ...]:
    """Custom check ids the facts ask for that are not registered.

    Reported rather than ignored. A reading stage that attaches a check this build does not
    have is a case being judged by fewer rules than the office expects, and silence there
    looks exactly like a clean case.
    """
    return tuple(name for name in facts.custom_checks if name not in CUSTOM_CHECKS)


# -- evaluation -----------------------------------------------------------------------------

def _as_results(entry: Check, facts: Facts, produced: Any) -> list[Result]:
    if produced is None:
        return []
    parts = produced if isinstance(produced, (list, tuple)) else [produced]
    out: list[Result] = []
    for part in parts:
        if not part:
            continue
        body = dict(part)
        # `is not None`, not truthiness. A sub of 0 or "" is still a sub, and treating it as
        # absent gave the first of several results the bare check id while its siblings got
        # `CHECK:1`, `CHECK:2` -- so the id of a result depended on where it happened to sit
        # in a list. §4.4 wants an id stable enough to follow a result across re-evaluations
        # and to hang a disposition on, and that was not it.
        sub = body.pop("sub", None)
        evidence = body.pop("evidence", ()) or ()
        out.append(Result(
            id=f"{entry.id}:{sub}" if sub is not None else entry.id,
            status=body.pop("status"),
            title=body.pop("title", entry.title),
            finding=body.pop("finding", ""),
            group=body.pop("group", entry.group),
            ref=body.pop("ref", entry.ref),
            code=body.pop("code", entry.code) or entry.code or entry.ref,
            doc=body.pop("doc", "") or entry.title,
            checklist=body.pop("checklist", entry.checklist_item(facts)),
            remedy=body.pop("remedy", ""),
            evidence=tuple(evidence),
            calc=body.pop("calc", None),
            cure=body.pop("cure", None),
            pair=body.pop("pair", None),
            doa=body.pop("doa", None),
            payload=body.pop("payload", None),
        ))
        if body:
            raise ValueError(f"check {entry.id!r} returned unknown keys {sorted(body)}")
    return out


def evaluate(facts: Facts) -> tuple[Result, ...]:
    """Every applicable check against the facts. Pure.

    A check that raises is reported as a verification task rather than taking the case down:
    an officer can act on "the rule could not be evaluated, check by hand", and cannot act on
    a stack trace. It is never reported as satisfied -- a rule that did not run has not
    passed, which is the same discipline §14 rule 10 applies to a below-threshold field.
    """
    out: list[Result] = []
    for entry in checks_for(facts):
        try:
            applies = bool(entry.applies(facts))
        except Exception:                                   # noqa: BLE001
            applies = True          # judge it rather than skip it; the run below will report
        if not applies:
            continue
        try:
            produced = entry.run(facts)
        except Exception as exc:                            # noqa: BLE001
            out.append(Result(
                id=entry.id, status=CONF, title=entry.title, group=entry.group,
                ref=entry.ref, code=entry.code or entry.ref,
                finding=(f"The rule could not be evaluated on the facts available "
                         f"({type(exc).__name__}: {exc}). Check this item by hand."),
                remedy="Check by hand and record the result; report the defect to the System Administrator.",
            ))
            continue
        out.extend(_as_results(entry, facts, produced))

    for name in unknown_custom_checks(facts):
        out.append(Result(
            id=f"UNREGISTERED:{name}", status=CONF, title="Case-specific check not available",
            group="integrity", ref="§5", code="OFF_LIST",
            finding=(f"The reading stage attached the case-specific check {name!r}, which this "
                     f"build does not carry, so whatever it was to test has not been tested."),
            remedy="Check the item by hand, and have the System Administrator reconcile the build.",
        ))
    return tuple(out)


def lists(results: Sequence[Result]) -> Lists:
    """Sort results into the four lists a case is presented as. §13.1."""
    hard = tuple(r for r in results if r.status == HARD)
    advisory = tuple(r for r in results if r.status == ADV)
    return Lists(
        hard=hard,
        advisory=advisory,
        # Hard stops first: the rejection form leads with what stops the case.
        observations=hard + advisory,
        verifications=tuple(r for r in results if r.status == CONF),
        sap=tuple(r for r in results if r.status == SAP),
        satisfied=tuple(r for r in results if r.status in (OK, SUB)),
        not_applicable=tuple(r for r in results if r.status == NA),
    )


# -- comparing two runs, §7.1 ---------------------------------------------------------------

@dataclass(frozen=True)
class RunDiff:
    """What changed between two evaluations of the same case.

    Drives the banner §7.1 step 6 requires: "what is now satisfied, what is newly raised and
    what changed". ``was`` is the previous status, so the officer sees the transition rather
    than only the destination.
    """

    resolved: tuple[tuple[Result, str], ...]
    raised: tuple[tuple[Result, str | None], ...]
    changed: tuple[tuple[Result, str], ...]
    still_open: tuple[tuple[Result, str | None], ...]

    def summary(self) -> str:
        bits = []
        if self.resolved:
            bits.append(f"{len(self.resolved)} now satisfied")
        if self.raised:
            bits.append(f"{len(self.raised)} newly raised")
        if self.changed:
            bits.append(f"{len(self.changed)} changed")
        if self.still_open:
            bits.append(f"{len(self.still_open)} still open")
        return "; ".join(bits) if bits else "nothing changed"


def diff_runs(previous: Sequence[Result], current: Sequence[Result]) -> RunDiff:
    """Compare two runs of the same case by result id."""
    before = {r.id: r for r in previous}
    resolved: list[tuple[Result, str]] = []
    raised: list[tuple[Result, str | None]] = []
    changed: list[tuple[Result, str]] = []
    still: list[tuple[Result, str | None]] = []

    for now in current:
        was = before.get(now.id)
        was_status = was.status if was else None
        open_before = bool(was_status and is_open(was_status))
        open_now = now.is_open
        if open_before and not open_now:
            resolved.append((now, was_status))                  # type: ignore[arg-type]
        elif not open_before and open_now:
            raised.append((now, was_status))
        elif open_before and open_now and was_status != now.status:
            changed.append((now, was_status))                   # type: ignore[arg-type]
        elif open_now:
            still.append((now, was_status))

    # An item that stopped being raised at all -- the check no longer applies because the
    # facts changed -- is resolved, not silently dropped. §7.3 keeps its disposition and
    # marks it cured, which needs the transition to be visible here.
    now_ids = {r.id for r in current}
    for was in previous:
        if was.id not in now_ids and is_open(was.status):
            resolved.append((Result(
                id=was.id, status=NA, title=was.title, group=was.group, ref=was.ref,
                code=was.code, doc=was.doc, checklist=was.checklist,
                finding="No longer raised: the facts this was raised on have changed.",
            ), was.status))

    return RunDiff(tuple(resolved), tuple(raised), tuple(changed), tuple(still))


# -- shared helpers for the rule modules ----------------------------------------------------

def ev(page: int | str | None, label: str, crop: str | None = None,
       bbox: Sequence[int] | None = None) -> Evidence:
    """One piece of evidence. Short name because the rules cite constantly."""
    return Evidence(page=page, label=label, crop=crop,
                    bbox=tuple(bbox) if bbox else None)       # type: ignore[arg-type]


def digits(value: Any) -> str:
    """Just the digits. Identifiers are compared on digits so punctuation cannot differ them.

    A CNIC is written 00001-0000101-3 on a card, 0000100001013 in SAP and in a QR payload.
    Comparing the printed strings would report a mismatch on three renderings of one number.
    """
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def num(value: Any) -> int | None:
    """A rupee figure from however the papers render it, or ``None``.

    Accepts thousands separators and SAP's trailing minus for a debit. Returns ``None``
    rather than 0 for anything unreadable: nil and unknown are different facts, and a
    balance that reads as zero because nobody could read it is how a wrong limit is passed.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).replace(",", "").replace(" ", "").strip()
    if text.endswith("/-"):
        text = text[:-2]
    negative = text.endswith("-")                # SAP prints a debit with a trailing minus
    if negative:
        text = text[:-1]
    if not text or not text.lstrip("-").isdigit():
        return None
    return -int(text) if negative else int(text)


def fmt(value: Any) -> str:
    """A rupee figure as the office writes it: ``1,234``. Presentation only."""
    parsed = num(value)
    return "" if parsed is None else f"{parsed:,}"


def name_key(value: Any) -> str:
    """A name reduced to comparable letters, honorifics dropped."""
    text = str(value or "").lower()
    for honorific in ("mr", "mrs", "ms", "mst", "miss", "dr"):
        text = text.replace(f"{honorific}.", " ").replace(f" {honorific} ", " ")
        if text.startswith(f"{honorific} "):
            text = text[len(honorific) + 1:]
    return "".join(ch for ch in text if ch.isalpha())


def same_name(left: Any, right: Any) -> bool | None:
    """Whether two renderings name the same person. ``None`` where one is missing.

    Containment counts as agreement: the papers give "Subscriber F. Test", "Subscribar F. Test" and
    "Mrs. Subscriber G. Test" for people the personnel number already identifies, and a strict
    comparison would raise a defect about a transliteration. ``None`` rather than False when
    a name is absent -- there is nothing to disagree with, and §14 rule 2 keeps the module
    from raising on that.
    """
    left_key, right_key = name_key(left), name_key(right)
    if not left_key or not right_key:
        return None
    return left_key == right_key or left_key in right_key or right_key in left_key


def verified(facts: Facts, vid: str) -> Mapping[str, Any] | None:
    """An officer's recorded verification, or ``None``. §7.2 ``verify``."""
    return facts.verification(vid)


def verified_result(record: Mapping[str, Any], ok_text: str, bad_text: str) -> dict[str, Any]:
    """Turn a recorded verification into a result. §7.3.

    A verification that FAILED is itself a fact and makes the item a hard stop with the
    officer's note -- it does not merely stay open. That is the half that makes the cure loop
    honest: recording "did not verify" has a consequence.
    """
    who = f"{record.get('by', 'the officer')} ({record.get('desig', 'desk not recorded')})"
    when = record.get("at", "date not recorded")
    note = record.get("note")
    tail = f": {note}" if note else "."
    if record.get("ok"):
        return {"status": OK, "finding": f"{ok_text} Verified by {who} on {when}{tail}"}
    return {"status": HARD, "finding": f"{bad_text} Recorded by {who} on {when}{tail}"}
