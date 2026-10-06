"""The data contracts between reading and rules. Build specification §4.

Three objects and one vocabulary:

``Facts``   what the reading stage lifted from the case (§4.3). The unit the rules work on.
``Result``  what one check concluded (§4.4), with a stable id so it can be followed across
            re-evaluations.
``Lists``   the four lists a case is presented as (§13.1).

Why the facts are a plain mapping
---------------------------------
The specification is explicit that an uploaded document, an SAP extract or an officer's
verification changes the FACTS, and the whole case is then evaluated again from the start
(§0, §7). Results are never edited -- "the same rule that raised an observation closes it",
and there is no mark-as-resolved path that could drift from the rules. A mapping is therefore
the right shape: it is what the reading stage emits, it is what gets versioned, and it
round-trips to JSON without a schema migration every time a new artefact type is read.

The typed accessors below exist so the rules do not reach into raw dictionaries and so a
missing branch reads as absent rather than raising. ``Facts`` is deliberately read-only: a
check that could mutate the facts it is judging is a check that can disagree with itself.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Iterator, Mapping, Sequence

# -- the status vocabulary, §4.4 -----------------------------------------------------------
#
# Seven statuses, and the difference between them is where the result GOES, not how bad it is.
# `hard` prints on the rejection form; `adv` on the advisory memorandum; `conf` is an officer
# decision; `sap` is an action for this section and never a defect of the department.

OK = "ok"        #: satisfied
SUB = "sub"      #: satisfied by an accepted substitute (challans for a certificate)
HARD = "hard"    #: not satisfied; the case cannot advance
ADV = "adv"      #: observation; does not block
CONF = "conf"    #: officer to verify; blocks payment
SAP = "sap"      #: awaiting an SAP extract; action for this section; blocks payment
NA = "na"        #: not applicable; hidden

STATUSES: tuple[str, ...] = (OK, SUB, HARD, ADV, CONF, SAP, NA)

#: What prints as an observation, in one instance, under para 2 of the circular.
_ISSUES = frozenset({HARD, ADV})

#: What stops a case being passed for payment. §13.3 and §14 rule 9: a verification task or
#: an SAP item open is as much a bar as a hard stop, because neither has been resolved.
_BLOCKS_PAYMENT = frozenset({HARD, CONF, SAP})


def is_issue(status: str) -> bool:
    """Whether the status is an observation to be issued to the department (§13.1)."""
    return status in _ISSUES


def blocks_payment(status: str) -> bool:
    """Whether the status bars passing the case for payment (§13.3)."""
    return status in _BLOCKS_PAYMENT


def is_open(status: str) -> bool:
    """Whether the item is still outstanding in any sense. Used by the run diff (§7.1)."""
    return status in _ISSUES or status in _BLOCKS_PAYMENT


# -- evidence and results ------------------------------------------------------------------

@dataclass(frozen=True)
class Evidence:
    """Where on the papers the finding can be seen. §4.4, §15.

    ``page`` is an int for a case page and a string for an uploaded document, because an
    upload has no page in the original bundle and pretending otherwise would put a citation
    on a page that does not carry it.
    """

    page: int | str | None
    label: str
    crop: str | None = None
    bbox: tuple[int, int, int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page, "label": self.label, "crop": self.crop,
                "bbox": list(self.bbox) if self.bbox else None}


@dataclass(frozen=True)
class Result:
    """What one check concluded about one thing. §4.4.

    ``id`` is stable across re-evaluations, which is what lets a disposition stay attached to
    an item and lets the run diff say what a document actually cured (§7.3). Where one check
    reports on several things -- four CNIC copies, seven proforma particulars -- each carries
    a ``sub`` and the id becomes ``CHECK:sub``.

    ``ref`` names the circular item, the office clarification or the rule. ``code`` is what
    prints on the rejection form, which is not always the same string: the DOA check cites
    R4 but prints B1-ii on a refundable sanction.
    """

    id: str
    status: str
    title: str
    finding: str
    group: str = ""
    ref: str = ""
    code: str = ""
    doc: str = ""
    checklist: str | None = None
    remedy: str = ""
    evidence: tuple[Evidence, ...] = ()
    #: Arithmetic, where the finding turns on a figure. Shown to the officer so the working
    #: is visible rather than asserted (§4.4, §11.2).
    calc: Mapping[str, Any] | None = None
    #: How this item can be cured, §7.2. ``None`` where nothing can cure it.
    cure: Mapping[str, Any] | None = None
    #: Two crops to place side by side, for a signature comparison the officer decides (§8.4).
    pair: Mapping[str, Any] | None = None
    #: The DOA lookup outcome, where this result came from one.
    doa: Mapping[str, Any] | None = None
    payload: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown result status {self.status!r}; expected one of {list(STATUSES)}")

    @property
    def is_issue(self) -> bool:
        return is_issue(self.status)

    @property
    def blocks_payment(self) -> bool:
        return blocks_payment(self.status)

    @property
    def is_open(self) -> bool:
        return is_open(self.status)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id, "status": self.status, "title": self.title, "finding": self.finding,
            "group": self.group, "ref": self.ref, "code": self.code or self.ref,
            "doc": self.doc or self.title, "checklist": self.checklist, "remedy": self.remedy,
            "evidence": [e.to_dict() for e in self.evidence],
        }
        for name in ("calc", "cure", "pair", "doa", "payload"):
            value = getattr(self, name)
            if value is not None:
                out[name] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
        return out


@dataclass(frozen=True)
class Lists:
    """The four lists a case is presented as. §13.1.

    ``observations`` is what issues to the department in ONE instance (circular para 2), hard
    stops first. ``verifications`` and ``sap`` are the office's own work, and both bar payment
    without being defects of the department -- a distinction §6.1 and §14 rule 9 both insist
    on, because putting the office's own pending work on a department's rejection form is how
    a case goes back and forward twice for nothing.
    """

    hard: tuple[Result, ...]
    advisory: tuple[Result, ...]
    observations: tuple[Result, ...]
    verifications: tuple[Result, ...]
    sap: tuple[Result, ...]
    satisfied: tuple[Result, ...]
    not_applicable: tuple[Result, ...]

    def counts(self) -> dict[str, int]:
        """The four acceptance numbers of §16.2, in the order that table prints them."""
        return {"hard": len(self.hard), "adv": len(self.advisory),
                "conf": len(self.verifications), "sap": len(self.sap)}

    @property
    def may_pass_for_payment(self) -> bool:
        """§13.3: no hard stop, no verification task and no SAP item open."""
        return not (self.hard or self.verifications or self.sap)


# -- the case facts, §4.3 ------------------------------------------------------------------

#: The eight case families the module processes, as ``kind`` on the facts (§4.3).
KINDS: tuple[str, ...] = (
    "refundable", "nonrefundable", "final", "death", "dismissal", "residual",
    "missing_credits", "balance_transfer",
)

#: Final payments, for the checks that apply to all of them (§5.3).
FINALS: tuple[str, ...] = ("final", "death", "dismissal", "residual")

#: Advances, refundable and non-refundable (§5.2).
ADVANCES: tuple[str, ...] = ("refundable", "nonrefundable")


@dataclass(frozen=True)
class Facts:
    """What the reading stage lifted from one case. §4.3.

    A thin, read-only view over the mapping the reading stage emits, so the rules read
    ``facts.sap_payslip`` rather than ``F["sap"]["payslip"]`` and an absent branch comes back
    as ``None`` instead of raising three levels down inside a check.

    Never mutated. :meth:`with_changes` returns a new object, which is how a cure produces a
    new facts VERSION rather than editing the one the previous results were computed from
    (§7.3: "Facts are versioned; results are always recomputed from facts, never edited").
    """

    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        kind = self.data.get("kind")
        if kind not in KINDS:
            raise ValueError(
                f"unknown case kind {kind!r}; the module processes {list(KINDS)}. The reading "
                f"stage settles the case type at stage 6 and UNKNOWN escalates to a person "
                f"rather than being guessed at (specification §3, §4.1)."
            )

    # -- identity ---------------------------------------------------------------------------
    @property
    def slug(self) -> str:
        return str(self.data.get("slug") or self.data.get("key") or "")

    @property
    def kind(self) -> str:
        return str(self.data["kind"])

    @property
    def label(self) -> str:
        return str(self.data.get("label") or self.slug)

    @property
    def personnel_no(self) -> str:
        return str(self.data.get("personnelNo") or "")

    @property
    def gazetted(self) -> str:
        """``gazetted``, ``non-gazetted``, ``mixed`` or ``unknown``.

        ``unknown`` is a real answer, not a gap to be filled: on the missing-credits case
        neither BPS nor status is stated anywhere in the papers, and §5.4 has both the DDO
        and the AG certificate checks run and be satisfied by the same challan evidence
        rather than the module picking one.
        """
        return str(self.data.get("gazetted") or "unknown")

    def is_kind(self, *kinds: str) -> bool:
        return self.kind in kinds

    # -- documents --------------------------------------------------------------------------
    @property
    def docs(self) -> Mapping[str, Any]:
        return self.data.get("docs") or {}

    def doc(self, name: str) -> Mapping[str, Any] | None:
        value = self.docs.get(name)
        return value if isinstance(value, Mapping) else None

    @property
    def cnics(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.docs.get("cnics") or ())

    def cnic_of(self, *whose: str) -> Mapping[str, Any] | None:
        """The first CNIC copy belonging to one of ``whose``; ``subscriber`` when unstated."""
        for card in self.cnics:
            if str(card.get("whose") or "subscriber") in whose:
                return card
        return None

    # -- SAP, §6 ----------------------------------------------------------------------------
    @property
    def sap(self) -> Mapping[str, Any] | None:
        value = self.data.get("sap")
        return value if isinstance(value, Mapping) else None

    @property
    def sap_payslip(self) -> Mapping[str, Any] | None:
        sap = self.sap
        value = sap.get("payslip") if sap else None
        return value if isinstance(value, Mapping) else None

    @property
    def sap_recalc(self) -> Mapping[str, Any] | None:
        sap = self.sap
        value = sap.get("recalc") if sap else None
        return value if isinstance(value, Mapping) else None

    @property
    def recalc_rows(self) -> tuple[Mapping[str, Any], ...]:
        recalc = self.sap_recalc
        return tuple(recalc.get("rows") or ()) if recalc else ()

    @property
    def sap_source(self) -> str:
        """``case`` where the extract was in the bundle, ``upload`` where the section pulled it.

        Recorded because §6.1 requires it on every accepted extract and §6.5 turns on it: an
        extract pulled after an advance was posted shows the balance AFTER the advance.
        """
        sap = self.sap
        return str(sap.get("source") or "") if sap else ""

    # -- codes, signatures, thumbs, verifications -------------------------------------------
    @property
    def qr(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.data.get("qr") or ())

    @property
    def signatures(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.data.get("signatures") or ())

    @property
    def thumbs(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.data.get("thumbs") or ())

    @property
    def claim(self) -> Mapping[str, Any] | None:
        value = self.data.get("claim")
        return value if isinstance(value, Mapping) else None

    @property
    def verifications(self) -> Mapping[str, Any]:
        """Officer decisions already recorded, keyed by verification id (§7.2 ``verify``).

        A recorded verification is a FACT, which is why it lives here and not on a result: it
        is an input the rules read, so the rule that raised the task is the rule that closes
        it. A verification that FAILED is equally a fact and makes the item a hard stop
        (§7.3).
        """
        return self.data.get("verifications") or {}

    def verification(self, vid: str) -> Mapping[str, Any] | None:
        value = self.verifications.get(vid)
        return value if isinstance(value, Mapping) else None

    @property
    def custom_checks(self) -> tuple[str, ...]:
        """Case-specific check ids the reading stage attached. §5.

        "Case-specific checks (anomalies that only one case shows, such as a double posting
        in SAP) use the same contract and are attached by the reading stage." They are not a
        back door: each is a registered check with an id, a ref and a code like any other.
        """
        return tuple(self.data.get("custom") or ())

    # -- versioning -------------------------------------------------------------------------
    def with_changes(self, mutate) -> "Facts":
        """A new ``Facts`` with ``mutate`` applied to a deep copy of the mapping.

        The cure functions in :mod:`gpfund.cures` are written as mutations because that is
        how they read on the page ("the form is now signed"), and this is where that stays
        safe: they never see the object the previous results were computed from.
        """
        fresh = copy.deepcopy(dict(self.data))
        mutate(fresh)
        return Facts(fresh)

    def without_sap(self) -> "Facts":
        """The case as it arrives when the department sent no SAP pages. §16.2.

        Every case must also be run this way: the SAP-dependent checks have to WAIT (`sap`)
        rather than pass, and uploading the sample extract must return the case to the
        results above. A build where a missing extract silently passes a limit test is the
        defect the office found in revision 1.
        """
        def strip(data: dict[str, Any]) -> None:
            data["sap"] = None
            data["persNos"] = [
                p for p in (data.get("persNos") or [])
                if "SAP" not in str(p.get("doc", "")) and "Re-calculation" not in str(p.get("doc", ""))
            ]
        return self.with_changes(strip)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.data))
