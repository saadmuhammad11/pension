"""The case file: fact versions, the cure loop, dispositions and the audit trail. §7, §13, §15.

One object, :class:`CaseFile`, holds everything that happens to a case after the reading
stage. It is the only mutable thing in this package, and the rules never see it -- they see a
:class:`~gpfund.contracts.Facts` version.

The three properties §7.3 requires, and how they are kept here:

* **Facts are versioned; results are always recomputed from facts, never edited.** Every
  version is retained in :attr:`CaseFile.versions`, and :meth:`CaseFile.results_at` recomputes
  an earlier version's results from that version's facts.
* **Re-evaluating an earlier version must reproduce its results exactly.** It does, because
  evaluation is pure -- ``tests/test_determinism.py`` pins it.
* **A disposition stays attached to the result id.** If a later version no longer raises the
  item, the disposition is kept and marked cured.

No clock. ``at`` is passed in on every call that records one, so a replay of the same actions
reproduces the same case file byte for byte -- the same discipline the rules layer keeps, for
the same reason (§15 reproducibility).
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .contracts import Facts, Lists, Result, is_issue
from .cures import apply_cure
from .engine import RULE_SET_VERSION, RunDiff, diff_runs, evaluate, lists
from .params import MIN_JUSTIFICATION, may, who_may
from .sap import SapExtract, SapExtractRejected


class NotPermitted(PermissionError):
    """The desk may not take that action. §13.2."""


class DispositionRefused(ValueError):
    """The disposition was not recordable, and the reason. §13.2, §8.3 of the circular."""


@dataclass(frozen=True)
class Version:
    """One version of the facts, and why it exists. §7.1 step 7."""

    number: int
    facts: Facts
    reason: str
    by: str
    desk: str
    at: str
    counts: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.number, "reason": self.reason, "by": self.by,
                "desk": self.desk, "at": self.at, "counts": dict(self.counts)}


@dataclass(frozen=True)
class Disposition:
    """What the officer decided about one observation. §13.2."""

    result_id: str
    action: str                  # uphold | waive | settle | refer
    by: str
    desk: str
    at: str
    ground: str = ""
    authority: str = ""
    cured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"result_id": self.result_id, "action": self.action, "by": self.by,
                "desk": self.desk, "at": self.at, "ground": self.ground,
                "authority": self.authority, "cured": self.cured}


@dataclass(frozen=True)
class Upload:
    """A document uploaded against an item. §7.1 step 2."""

    result_id: str
    file_name: str
    sha256: str
    size: int
    content_type: str
    by: str
    desk: str
    at: str
    confirmed: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"result_id": self.result_id, "file_name": self.file_name,
                "sha256": self.sha256, "size": self.size, "content_type": self.content_type,
                "by": self.by, "desk": self.desk, "at": self.at,
                "confirmed": dict(self.confirmed)}


@dataclass(frozen=True)
class AuditEntry:
    """One line of the append-only log. §15."""

    at: str
    by: str
    desk: str
    grade: str
    action: str
    detail: str
    case_version: int
    rule_set: Mapping[str, str]
    before: Any = None
    after: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"at": self.at, "by": self.by, "desk": self.desk, "grade": self.grade,
                "action": self.action, "detail": self.detail,
                "case_version": self.case_version, "rule_set": dict(self.rule_set),
                "before": self.before, "after": self.after}


class CaseFile:
    """One case, from the first evaluation to the issue pack. §7, §13, §15."""

    def __init__(self, facts: Facts, *, case_ref: str = "", by: str = "system",
                 desk: str = "AO", at: str = "") -> None:
        self.case_ref = case_ref or facts.slug
        self.versions: list[Version] = []
        self.results: tuple[Result, ...] = ()
        self.last_diff: RunDiff | None = None
        self.dispositions: dict[str, Disposition] = {}
        self.uploads: list[Upload] = []
        self.sap_extracts: list[SapExtract] = []
        self.returns = 0
        self.case_decision: str | None = None
        self.case_note: str = ""
        self._audit: list[AuditEntry] = []
        self._evaluate(facts, reason="Initial processing", by=by, desk=desk, at=at)

    # -- state ------------------------------------------------------------------------------
    @property
    def facts(self) -> Facts:
        return self.versions[-1].facts

    @property
    def version(self) -> int:
        return self.versions[-1].number

    @property
    def lists(self) -> Lists:
        return lists(self.results)

    @property
    def audit(self) -> tuple[AuditEntry, ...]:
        """The log. A tuple, so a caller cannot amend or remove an entry. §15, §8.2.5.

        Append-only is a property of this object, not a convention: there is no method that
        edits or deletes, and the accessor hands out an immutable copy.
        """
        return tuple(self._audit)

    def results_at(self, version: int) -> tuple[Result, ...]:
        """Recompute an earlier version's results from that version's facts. §7.3."""
        for entry in self.versions:
            if entry.number == version:
                return evaluate(entry.facts)
        raise KeyError(f"case {self.case_ref} has no version {version}")

    # -- the audit log ----------------------------------------------------------------------
    def log(self, action: str, detail: str, *, by: str, desk: str, at: str,
            before: Any = None, after: Any = None) -> AuditEntry:
        entry = AuditEntry(
            at=at, by=by, desk=desk,
            grade=str(_desk_grade(desk)), action=action, detail=detail,
            case_version=self.version if self.versions else 0,
            rule_set=dict(RULE_SET_VERSION), before=before, after=after)
        self._audit.append(entry)
        return entry

    # -- evaluation -------------------------------------------------------------------------
    def _evaluate(self, facts: Facts, *, reason: str, by: str, desk: str, at: str) -> RunDiff | None:
        previous = self.results
        current = evaluate(facts)
        diff = diff_runs(previous, current) if previous else None
        self.results = current
        counts = lists(current).counts()
        self.versions.append(Version(
            number=len(self.versions) + 1, facts=facts, reason=reason, by=by, desk=desk,
            at=at, counts=counts))
        self.last_diff = diff
        # A disposition on an observation that is no longer raised is KEPT and marked cured.
        # §7.3: the officer's decision is part of the record even once the item has gone.
        for result_id, disposition in list(self.dispositions.items()):
            still = next((r for r in current if r.id == result_id), None)
            cured = not (still and is_issue(still.status))
            if cured != disposition.cured:
                self.dispositions[result_id] = Disposition(
                    **{**disposition.to_dict(), "cured": cured})
        self.log("evaluate", f"{reason} — {counts}", by=by, desk=desk, at=at,
                 before=dict(self.versions[-2].counts) if len(self.versions) > 1 else None,
                 after=dict(counts))
        return diff

    def reevaluate(self, facts: Facts, *, reason: str, by: str, desk: str, at: str) -> RunDiff | None:
        """Install a new facts version and re-check the WHOLE case. §0, §7.1 step 6."""
        return self._evaluate(facts, reason=reason, by=by, desk=desk, at=at)

    # -- the cure loop, §7 -------------------------------------------------------------------
    def result(self, result_id: str) -> Result:
        for entry in self.results:
            if entry.id == result_id:
                return entry
        raise KeyError(f"case {self.case_ref} has no open result {result_id!r}")

    def upload_against(self, result_id: str, *, file_name: str, content: bytes,
                       confirmed: Mapping[str, Any], by: str, desk: str, at: str,
                       content_type: str = "application/octet-stream") -> RunDiff | None:
        """Cure an item by uploading a document against it. §7.1.

        Runs the whole flow bar the reading: store with a hash, merge the CONFIRMED fields
        (never the raw read -- §7.1 step 4 has below-threshold fields confirmed by a person,
        and §14 rule 10 forbids accepting one silently), then re-evaluate the case.
        """
        if not may(desk, "upload_document"):
            raise NotPermitted(f"{who_may('upload_document')} or above may upload a document.")
        target = self.result(result_id)
        cure = target.cure or {}
        if cure.get("kind") != "doc":
            raise DispositionRefused(
                f"{result_id} is not cured by a document; its cure is "
                f"{cure.get('kind') or 'none'}. Use record_verification or the SAP extracts step.")
        record = Upload(
            result_id=result_id, file_name=file_name,
            sha256=hashlib.sha256(content).hexdigest(), size=len(content),
            content_type=content_type, by=by, desk=desk, at=at, confirmed=dict(confirmed))
        self.uploads.append(record)

        def merge(data: dict[str, Any]) -> None:
            apply_cure(data, str(cure["apply"]), confirmed, file_name)

        self.log("upload", f"{file_name} against {result_id} (sha256 {record.sha256[:16]}…)",
                 by=by, desk=desk, at=at, after=record.to_dict())
        return self.reevaluate(self.facts.with_changes(merge),
                               reason=f"Document uploaded against {result_id}",
                               by=by, desk=desk, at=at)

    def record_verification(self, vid: str, *, ok: bool, note: str, by: str, desk: str,
                            at: str, designation: str = "") -> RunDiff | None:
        """Record an officer decision. It becomes a FACT. §7.2 ``verify``, §7.3.

        A verification that FAILED is as much a fact as one that succeeded, and the rule that
        raised the task turns it into a hard stop with the officer's note. That is what keeps
        the loop honest: recording "did not verify" has a consequence.
        """
        if not may(desk, "record_verification"):
            raise NotPermitted(f"{who_may('record_verification')} or above may record a verification.")

        def merge(data: dict[str, Any]) -> None:
            data.setdefault("verifications", {})[vid] = {
                "ok": bool(ok), "by": by, "desig": designation or str(_desk_label(desk)),
                "at": at, "note": note}

        self.log("verify", f"{vid}: {'verified' if ok else 'did not verify'} — {note}",
                 by=by, desk=desk, at=at)
        return self.reevaluate(self.facts.with_changes(merge),
                               reason=f"Verification recorded for {vid}", by=by, desk=desk, at=at)

    def accept_sap_extract(self, extract: SapExtract, *, by: str, desk: str,
                           at: str) -> RunDiff | None:
        """Accept an SAP extract and re-evaluate. §6.1.

        The identity check belongs to :mod:`gpfund.sap` and has already run by the time an
        extract reaches here; a rejection is logged through :meth:`log_sap_rejection` so the
        attempt is on the record either way.
        """
        if not may(desk, "record_verification"):
            raise NotPermitted(f"{who_may('record_verification')} or above may accept an SAP extract.")
        self.sap_extracts.append(extract)
        fragment = extract.to_facts_fragment()

        def merge(data: dict[str, Any]) -> None:
            data["sap"] = fragment

        self.log("sap-extract",
                 f"accepted {extract.file_name or extract.source} "
                 f"(sha256 {(extract.sha256 or '')[:16]}…)",
                 by=by, desk=desk, at=at, after={k: v for k, v in fragment.items()
                                                 if k not in ("payslip", "recalc")})
        return self.reevaluate(Facts({**self.facts.to_dict(), "sap": fragment}),
                               reason="SAP extract accepted", by=by, desk=desk, at=at)

    def log_sap_rejection(self, file_name: str, reason: str, *, by: str, desk: str,
                          at: str) -> AuditEntry:
        """§6.1: the rejection is logged."""
        return self.log("sap-rejected", f"{file_name}: {reason}", by=by, desk=desk, at=at)

    # -- dispositions, §13.2 -----------------------------------------------------------------
    def dispose_of(self, result_id: str, action: str, *, by: str, desk: str, at: str,
                   ground: str = "", authority: str = "") -> Disposition:
        """Record a disposition against one observation. §13.2.

        ``waive`` requires a ground AND an authority -- both mandatory, and a hard stop can
        only be waived by the DAG (Funds). The length floor is this office's guard against a
        one-word reason standing in for a decision.
        """
        target = self.result(result_id)
        if action not in ("uphold", "waive", "settle", "refer"):
            raise DispositionRefused(
                f"unknown disposition {action!r}; expected uphold, waive, settle or refer.")
        permission = {"uphold": "uphold", "settle": "settle_in_office", "refer": "refer_upward",
                      "waive": "waive_hard" if target.status == "hard" else "waive_advisory"}[action]
        if not may(desk, permission):
            raise NotPermitted(
                f"{who_may(permission)} or above may {action.replace('_', ' ')} "
                f"{'a hard stop' if target.status == 'hard' else 'this item'}.")
        if action == "waive":
            if len(ground.strip()) < MIN_JUSTIFICATION:
                raise DispositionRefused(
                    f"waiving {result_id} needs a written ground of at least "
                    f"{MIN_JUSTIFICATION} characters, stating what stood against the case.")
            if not authority.strip():
                raise DispositionRefused(
                    f"waiving {result_id} needs the authority relied on to be recorded.")
        disposition = Disposition(result_id=result_id, action=action, by=by, desk=desk, at=at,
                                  ground=ground, authority=authority)
        self.dispositions[result_id] = disposition
        self.log("dispose", f"{result_id}: {action}" + (f" — {ground}" if ground else ""),
                 by=by, desk=desk, at=at, after=disposition.to_dict())
        return disposition

    # -- position ----------------------------------------------------------------------------
    def position(self) -> dict[str, Any]:
        """Where the case stands after dispositions. Drives the disposal gates, §13.3."""
        current = self.lists
        hard = advisory = waived = settled = referred = undisposed = 0
        for observation in current.observations:
            disposition = self.dispositions.get(observation.id)
            if disposition and disposition.action == "waive":
                waived += 1
                continue
            if disposition and disposition.action == "settle":
                settled += 1
                continue
            if disposition and disposition.action == "refer":
                referred += 1
            if observation.status == "hard":
                hard += 1
            else:
                advisory += 1
            if not disposition:
                undisposed += 1
        return {
            "hard": hard, "advisory": advisory, "waived": waived, "settled": settled,
            "referred": referred, "undisposed": undisposed,
            "observations": len(current.observations),
            "verifications": len(current.verifications), "sap": len(current.sap),
            "returns": self.returns,
        }

    def to_dict(self) -> dict[str, Any]:
        """The case record §8.1 and §15 require retained."""
        return {
            "case_ref": self.case_ref,
            "version": self.version,
            "rule_set": dict(RULE_SET_VERSION),
            "counts": self.lists.counts(),
            "position": self.position(),
            "results": [r.to_dict() for r in self.results],
            "versions": [v.to_dict() for v in self.versions],
            "dispositions": [d.to_dict() for d in self.dispositions.values()],
            "uploads": [u.to_dict() for u in self.uploads],
            "sap_extracts": [{k: v for k, v in e.to_facts_fragment().items()
                              if k not in ("payslip", "recalc")} for e in self.sap_extracts],
            "audit": [e.to_dict() for e in self._audit],
            "decision": self.case_decision,
            "note": self.case_note,
        }


def _desk_grade(desk_id: str) -> str:
    from .params import DESKS
    for entry in DESKS:
        if entry["id"] == desk_id:
            return str(entry["grade"])
    return ""


def _desk_label(desk_id: str) -> str:
    from .params import DESKS
    for entry in DESKS:
        if entry["id"] == desk_id:
            return str(entry["label"])
    return desk_id
