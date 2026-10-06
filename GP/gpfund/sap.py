"""SAP extracts: the data contract, the parser and the connector interface. §6.

R1 reframed the module: the pay slip and the GPF Final Re-calculation Report are ticked off
if they are in the case and PULLED BY THIS SECTION if they are not. A missing extract is
therefore an action for the office (``sap``) and never a defect of the department -- which is
why the status vocabulary has a seventh entry at all.

The MVP is manual upload (§6.1). It sits behind the same interface the connector will
implement (§6.2), so nothing downstream changes when the connector arrives:

    connector = ManualUploadConnector()
    extract = connector.accept_upload("SAP_EXTRACT_90000227.txt", text, facts)

On "SAP BDC"
-----------
The office asked for automatic retrieval "over SAP BDC". §6.3 sets out why that is the wrong
mechanism: Batch Data Communication is how you ENTER data into SAP by replaying recorded
transaction screens, not a retrieval interface. Reading a report through it means recording
the transaction, running it in the background and scraping the spool list -- which works until
a screen layout changes and then fails silently. The recommended route is an RFC-enabled
function module wrapping the two report programs, called under a read-only communication
user, or an OData service over the same function. Open item GPF-O19.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .contracts import Facts
from .engine import digits, num

# -- the data contract, §4.2 ----------------------------------------------------------------

#: Pay slip keys as an SAP list export labels them, mapped to the field names the rules read.
#: Both "Personnel No" and "Pers No" appear on real prints, so both are accepted.
PAYSLIP_KEYS: dict[str, str] = {
    "personnel no": "persNo", "pers no": "persNo", "name": "name",
    "designation": "designation", "cnic": "cnic", "month": "month", "bps": "bps",
    "ddo code": "ddoCode", "gpf no": "gpfNo", "old gpf no": "oldGpfNo",
    "gpf balance": "gpfBalance", "gpf subscription": "gpfSubscription",
    "gpf loan instalment": "loanInstalment", "gpf loan balance": "loanBalance",
    "osd post": "osdPost", "employment status": "status", "bank": "bank",
    "basic pay": "basicPay",
}

#: Fields that are rupee figures. Parsed with :func:`gpfund.engine.num`, which returns None
#: for anything unreadable rather than 0 -- nil and unknown are different facts, and a
#: balance that reads as zero because nobody could read it is how a wrong limit is passed.
PAYSLIP_MONEY = frozenset({
    "gpfBalance", "gpfSubscription", "loanInstalment", "loanBalance", "basicPay",
})

#: The ten columns of the GPF Final Re-calculation Report, in the order it prints them.
RECALC_COLUMNS: tuple[str, ...] = (
    "start", "end", "opening", "subscription", "adjustments", "tempAdvance",
    "recTempAdvance", "permanentAdvance", "interest", "closing",
)


@dataclass(frozen=True)
class SapPayslip:
    """One SAP pay slip. §4.2."""

    fields: Mapping[str, Any]

    @property
    def personnel_no(self) -> str:
        return str(self.fields.get("persNo") or "")

    def to_dict(self) -> dict[str, Any]:
        return dict(self.fields)


@dataclass(frozen=True)
class SapGpfRecalcReport:
    """The GPF Final Re-calculation Report: the ledger §12 reconciles against. §4.2."""

    header: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]

    @property
    def personnel_no(self) -> str:
        return str(self.header.get("persNo") or "")

    def to_dict(self) -> dict[str, Any]:
        return {**dict(self.header), "rows": [dict(r) for r in self.rows]}


@dataclass(frozen=True)
class SapAdvance:
    """One advance and its monthly recovery schedule. §6.2, and R12's missing half.

    The re-calculation report is YEARLY, so it cannot show the month an earlier advance
    reached zero -- and R12 turns on exactly that month. This is what the connector must
    return for ``ADV-ACTIVE`` to answer R12 rather than raise a verification task (§11.4).
    """

    drawn_on: str
    amount: int
    kind: str                                  # "temporary" | "permanent"
    recovered_by_month: Mapping[str, int] = field(default_factory=dict)
    zero_month: str | None = None


@dataclass(frozen=True)
class SapOrgAssignment:
    """DDO, BPS, gazetted flag and OSD post. §6.2.

    The OSD post is what R13 turns on, and open item GPF-O17 asks the office which SAP field
    actually carries it -- so a connector that cannot supply it must say so rather than
    return a falsy default that would read as "no OSD post".
    """

    ddo_code: str | None = None
    bps: str | None = None
    gazetted: str | None = None
    osd_post: str | None = None


@dataclass(frozen=True)
class ConnectorStatus:
    """Whether the SAP link is usable, and what it is. §6.2, §6.4.

    Degradation is visible, never silent (the standing rule the pension build states as its
    rule 7 and this specification repeats throughout): the portal shows what mode is in force
    so an officer knows whether an absent extract means "nobody pulled it" or "SAP is down".
    """

    mode: str
    reachable: bool
    detail: str = ""


@dataclass(frozen=True)
class SapExtract:
    """An accepted extract, with everything §6.1 and §15 require recorded against it."""

    payslip: SapPayslip | None
    recalc: SapGpfRecalcReport | None
    source: str                                # "case" | "upload" | "connector"
    file_name: str | None = None
    sha256: str | None = None
    officer: str | None = None
    at: str | None = None
    sap_user: str | None = None
    pulled_at: str | None = None
    warnings: tuple[str, ...] = ()

    def to_facts_fragment(self) -> dict[str, Any]:
        """The ``sap`` branch of the facts object. §4.3."""
        return {
            "source": self.source,
            "file": self.file_name,
            "sha256": self.sha256,
            "officer": self.officer,
            "at": self.at,
            "sapUser": self.sap_user,
            "pulledAt": self.pulled_at,
            "payslip": self.payslip.to_dict() if self.payslip else None,
            "recalc": self.recalc.to_dict() if self.recalc else None,
        }


class SapExtractRejected(ValueError):
    """The extract was not accepted, and the reason. §6.1.

    Raised rather than returned so an extract for a different employee cannot be merged into
    a case by a caller that forgot to check. The rejection is logged by
    :mod:`gpfund.casefile`.
    """


# -- the parser, §6.1 -----------------------------------------------------------------------

_SECTION = re.compile(r"^SAP EXTRACT:\s*(.+)$", re.I)
_KEY_VALUE = re.compile(r"^([^:]+):\s*(.*)$")


def parse_sap_text(text: str) -> dict[str, Any]:
    """Parse the agreed text layout. No model: it is a list export, so it is parsed. §6.1.

    Tabs or pipes are both accepted, because an SAP list saved as text gives one or the other
    depending on how it was exported, and an officer should not have to know which.

    A line that is not recognised is collected as a WARNING rather than dropped. §6.1 accepts
    a PDF or image of the SAP screen through the reading stage; a text export that has drifted
    from the agreed layout must be visible as drift, not silently half-read.
    """
    out: dict[str, Any] = {"payslip": None, "recalc": None, "warnings": []}
    section: str | None = None
    current: dict[str, Any] | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        header = _SECTION.match(line)
        if header:
            title = header.group(1).upper()
            if "PAY SLIP" in title or "PAYSLIP" in title:
                section, current = "payslip", {}
                out["payslip"] = current
            elif "RE-CALCULATION" in title or "RECALCULATION" in title:
                section, current = "recalc", {"rows": []}
                out["recalc"] = current
            else:
                section, current = None, None
                out["warnings"].append(f"Unrecognised section: {line}")
            continue
        if not section or current is None:
            continue

        cells = [c.strip() for c in re.split(r"\t|\|", line)]
        if section == "recalc" and len(cells) >= len(RECALC_COLUMNS):
            if cells[0].lower().startswith("start"):
                continue                                    # the header row
            row: dict[str, Any] = {}
            for index, column in enumerate(RECALC_COLUMNS):
                row[column] = cells[index] if index < 2 else num(cells[index])
            current["rows"].append(row)
            continue

        match = _KEY_VALUE.match(line)
        if not match:
            out["warnings"].append(f"Ignored line: {line}")
            continue
        key, value = match.group(1).strip().lower(), match.group(2).strip()
        if section == "payslip":
            name = PAYSLIP_KEYS.get(key)
            if not name:
                out["warnings"].append(f"Ignored pay slip line: {line}")
                continue
            current[name] = num(value) if name in PAYSLIP_MONEY else value
        else:
            if key == "personnel no":
                current["persNo"] = value
            elif key == "gpf reference no":
                current["gpfRef"] = value
            elif key == "report date":
                current["reportDate"] = value
            elif key == "name":
                current["name"] = value
            else:
                out["warnings"].append(f"Ignored report header line: {line}")
    return out


def parse_sap_file(name: str, text: str) -> dict[str, Any]:
    """Parse an uploaded extract. JSON or the agreed text layout. §6.1."""
    body = text.strip()
    if body.startswith("{"):
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise SapExtractRejected(
                f"{name} looks like JSON but could not be read ({exc}). Supply the agreed text "
                f"layout, or a JSON object with 'payslip' and 'recalc'.") from exc
        return {"payslip": payload.get("payslip"), "recalc": payload.get("recalc"),
                "warnings": []}
    return parse_sap_text(body)


def check_against_case(parsed: Mapping[str, Any], facts: Facts) -> list[str]:
    """Why this extract does not belong to this case. Empty when it does. §6.1.

    §16.1 records that the refundable case's own CNIC page carries a stray fragment of a
    DIFFERENT employee's SAP report. An extract with no personnel number on it at all is
    refused for the same reason as one with the wrong number: there is then nothing tying the
    figures to this subscriber, and the figures decide a payment.
    """
    want = digits(facts.personnel_no)
    issues: list[str] = []
    for label, part in (("pay slip", parsed.get("payslip")),
                        ("re-calculation report", parsed.get("recalc"))):
        if not part:
            continue
        got = digits(part.get("persNo"))
        if not got:
            issues.append(f"The {label} carries no personnel number.")
        elif want and got != want:
            issues.append(
                f"The {label} is for personnel no. {part.get('persNo')}, not "
                f"{facts.personnel_no}. It belongs to a different employee.")
    return issues


def recalc_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The report's closing position and the advance totals. §12."""
    if not rows:
        return None
    drawn = sum(num(r.get("tempAdvance")) or 0 for r in rows)
    recovered = sum(num(r.get("recTempAdvance")) or 0 for r in rows)
    return {"last": dict(rows[-1]), "tempDrawn": drawn, "tempRecovered": recovered,
            "tempOutstanding": drawn - recovered, "rows": len(rows)}


def extract_template(facts: Facts) -> str:
    """A text template the section can fill from the SAP screens. §6.1."""
    pers = facts.personnel_no or ""
    return (
        "SAP EXTRACT: PAY SLIP\n"
        f"Personnel No: {pers}\n"
        "Name: \nDesignation: \nCNIC: \nMonth: \nBPS: \nDDO Code: \nGPF No: \nOld GPF No: \n"
        "GPF Balance: \nGPF Subscription: \nGPF Loan Instalment: \nGPF Loan Balance: \n"
        "Basic Pay: \nOSD Post: \n\n"
        "SAP EXTRACT: GPF FINAL RE-CALCULATION REPORT\n"
        f"Personnel No: {pers}\n"
        "GPF Reference No: \nReport Date: \n"
        + "|".join((
            "Start Date", "End Date", "Opening Balance", "Monthly Subscription", "Adjustments",
            "Temp Advance", "Rec of Temp Advance", "Permanent Advance", "Interest Applied",
            "Closing Balance")) + "\n"
    )


# -- the connector interface, §6.2 -----------------------------------------------------------

@runtime_checkable
class SapConnector(Protocol):
    """What the MVP and the real connector both implement. §6.2.

    Build the MVP behind this so nothing downstream changes when the connector arrives. The
    phase-2 implementations named in the specification are ``SapRfcConnector`` (recommended:
    an RFC-enabled function module wrapping the report programs, called with the NetWeaver RFC
    SDK under a read-only user) and ``SapODataConnector`` (an OData service on SAP Gateway
    over the same function).
    """

    def get_payslip(self, pers_no: str, period: str | None = None) -> SapPayslip: ...
    def get_gpf_recalc_report(self, pers_no: str) -> SapGpfRecalcReport: ...
    def get_advance_history(self, pers_no: str) -> list[SapAdvance]: ...
    def get_org_assignment(self, pers_no: str) -> SapOrgAssignment: ...
    def health(self) -> ConnectorStatus: ...


class SapConnectorUnavailable(RuntimeError):
    """This route cannot fetch from SAP. Raised, never defaulted around.

    §6.1 and §14 rule 9: a check waiting on SAP waits (``sap``). It must not receive an empty
    pay slip that reads as "no balance" and pass a limit test on it.
    """


class ManualUploadConnector:
    """The MVP: the section pulls from SAP and uploads what it pulled. §6.1.

    Read-only by construction -- it fetches nothing and therefore cannot write back, which is
    the v1 posture §6.4 requires of the real connector too.
    """

    mode = "manual-upload"

    def health(self) -> ConnectorStatus:
        return ConnectorStatus(
            mode=self.mode, reachable=True,
            detail=("Manual upload. The section pulls the pay slip and the GPF Final "
                    "Re-calculation Report from SAP by personnel number and uploads them on the "
                    "SAP extracts step. Automatic retrieval is phase 2 (GPF-O19)."))

    # The fetch half of the interface is not available on this route, and says so rather than
    # returning something empty that a check would read as a figure.
    def _unavailable(self, what: str) -> SapConnectorUnavailable:
        return SapConnectorUnavailable(
            f"{what} cannot be fetched on the manual-upload route. Pull it from SAP and upload "
            f"it on the SAP extracts step, or configure the SAP connector (GPF-O19).")

    def get_payslip(self, pers_no: str, period: str | None = None) -> SapPayslip:
        raise self._unavailable("A pay slip")

    def get_gpf_recalc_report(self, pers_no: str) -> SapGpfRecalcReport:
        raise self._unavailable("The GPF Final Re-calculation Report")

    def get_advance_history(self, pers_no: str) -> list[SapAdvance]:
        raise self._unavailable("The monthly advance history (needed for R12)")

    def get_org_assignment(self, pers_no: str) -> SapOrgAssignment:
        raise self._unavailable("The organisational assignment")

    # -- what this route does do -------------------------------------------------------------
    def accept_upload(self, file_name: str, text: str, facts: Facts, *,
                      officer: str | None = None, at: str | None = None) -> SapExtract:
        """Parse, check the identity, and return an accepted extract. §6.1.

        Refuses on identity rather than warning: the figures in an extract decide a limit and
        a payment, and merging another employee's ledger into a case is not something a
        warning can undo. The refusal carries the reason so the log can record it.
        """
        parsed = parse_sap_file(file_name, text)
        if not parsed.get("payslip") and not parsed.get("recalc"):
            raise SapExtractRejected(
                f"{file_name} carries neither a pay slip nor a GPF Final Re-calculation Report. "
                f"Expected a section headed 'SAP EXTRACT: PAY SLIP' or 'SAP EXTRACT: GPF FINAL "
                f"RE-CALCULATION REPORT'.")
        issues = check_against_case(parsed, facts)
        if issues:
            raise SapExtractRejected(" ".join(issues))
        payslip = SapPayslip(parsed["payslip"]) if parsed.get("payslip") else None
        recalc = None
        if parsed.get("recalc"):
            body = dict(parsed["recalc"])
            rows = tuple(body.pop("rows", ()) or ())
            recalc = SapGpfRecalcReport(header=body, rows=rows)
        return SapExtract(
            payslip=payslip, recalc=recalc, source="upload", file_name=file_name,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            officer=officer, at=at,
            sap_user=(recalc.header.get("sapUser") if recalc else None),
            pulled_at=(recalc.header.get("reportDate") if recalc else None),
            warnings=tuple(parsed.get("warnings") or ()),
        )
