"""SAP connector interface — the seam where the SAP link plugs in (spec §6.2).

MVP is `ManualUploadConnector`: the section pulls the pay slip and the GPF
Final Re-calculation Report from SAP by personnel number and uploads them, and
this connector reads what was uploaded. Phase 2 replaces it with an RFC or
OData connector against a read-only SAP user — WITHOUT changing anything
downstream, because all three implement the same protocol.

Note (spec §6.3): "SAP BDC" is a data-*entry* technique, not a retrieval
interface. The recommended route is an RFC-enabled function module wrapping the
pay slip and GPF report programs (open item GPF-O19).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from ..sap import check_sap_against_case, parse_sap_file


@dataclass
class ConnectorStatus:
    ok: bool
    mode: str
    note: str = ""


@runtime_checkable
class SapConnector(Protocol):
    def get_payslip(self, pers_no: str, period: Optional[str] = None) -> Optional[dict]: ...
    def get_gpf_recalc_report(self, pers_no: str) -> Optional[dict]: ...
    def get_advance_history(self, pers_no: str) -> list: ...   # drawn, recovered by month, zero month (R12)
    def get_org_assignment(self, pers_no: str) -> Optional[dict]: ...  # DDO, BPS, gazetted flag, OSD post
    def health(self) -> ConnectorStatus: ...


class ManualUploadConnector:
    """MVP: reads the text/JSON extract the section uploaded (spec §6.1).

    An accepted extract is tagged with its source, file name and (in production)
    SHA-256, officer and time; an extract whose personnel number differs from the
    case is rejected with the reason (identity gate).
    """

    mode = "manual-upload"

    def __init__(self):
        self._store: dict[str, dict] = {}  # pers_no -> {"payslip":..., "recalc":...}

    def load_extract(self, F: dict, name: str, text: str) -> dict:
        """Parse, validate against the case, and cache. Returns the accepted extract.

        Raises ValueError with the reason if the extract belongs to another
        employee (this rejection is logged in production, spec §6.1).
        """
        parsed = parse_sap_file(name, text)
        issues = check_sap_against_case(parsed, F)
        if issues:
            raise ValueError("Extract rejected: " + " ".join(issues))
        extract = {"source": "upload", "file": name,
                   "payslip": parsed.get("payslip"), "recalc": parsed.get("recalc")}
        self._store[str(F.get("personnelNo"))] = extract
        return extract

    def apply_to_case(self, F: dict, name: str, text: str) -> dict:
        """Load an extract and merge it into the case facts, ready for re-evaluation."""
        F["sap"] = self.load_extract(F, name, text)
        return F

    def get_payslip(self, pers_no, period=None):
        rec = self._store.get(str(pers_no))
        return rec.get("payslip") if rec else None

    def get_gpf_recalc_report(self, pers_no):
        rec = self._store.get(str(pers_no))
        return rec.get("recalc") if rec else None

    def get_advance_history(self, pers_no):
        return []  # the monthly recovery schedule arrives with the real connector (R12)

    def get_org_assignment(self, pers_no):
        return None

    def health(self) -> ConnectorStatus:
        return ConnectorStatus(ok=True, mode=self.mode,
                               note="Reads section-uploaded extracts. No SAP link in the MVP.")


class SapRfcConnector:  # pragma: no cover - phase 2
    """Phase 2 (recommended): RFC-enabled function module via the NetWeaver RFC SDK."""
    mode = "sap-rfc"

    def __init__(self, **conn):
        self.conn = conn

    def _not_ready(self, *a, **k):
        raise NotImplementedError("Build phase 10: wire PyRFC against the read-only SAP user (GPF-O19).")

    get_payslip = get_gpf_recalc_report = get_advance_history = get_org_assignment = _not_ready

    def health(self) -> ConnectorStatus:
        return ConnectorStatus(ok=False, mode=self.mode, note="Not configured (phase 2).")


class SapODataConnector(SapRfcConnector):  # pragma: no cover - phase 2
    """Phase 2 alternative: OData service on SAP Gateway over the same function."""
    mode = "sap-odata"
