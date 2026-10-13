"""Application service: the case lifecycle (spec §7, §8, §13).

Everything the officer can do to a case funnels through here, so the rules that
matter are enforced in one place:

* Facts are versioned; results are ALWAYS recomputed from facts, never edited.
* An upload / SAP extract / verification changes the FACTS; the whole case is
  re-evaluated and diffed (cure by upload, §7).
* Delegation bands gate who may do what (§13.2); disposal gates decide when a
  case may leave the office (§13.3). No case is disposed while an observation is
  undisposed, or while a hard stop / verification / SAP item is open.
* Every action is written to an append-only audit trail (§15).
"""
from __future__ import annotations

import datetime
import functools
import threading
import uuid
from typing import Optional

from . import doa as doa_mod
from .engine import (CaseState, OFFICERS, disposition_in_force, fingerprint, is_issue, lists, may, position, run_case,
                     who_can)
from .fixtures import CASES, all_case_keys, load_case
from .rules_family import CURES, fund_position
from .store import CaseRepository, DocumentStore


class ServiceError(Exception):
    """A business-rule failure (bad request / forbidden), with an HTTP status hint."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.datetime.now().strftime("%d-%m-%Y %H:%M")


#: Long enough to say what was seen and why -- the same bar the pension side sets on a waiver.
MIN_GROUND = 15


def _officer(officer_id: str) -> dict:
    """The acting officer: a band (``ao``), or ``band|Name`` where the pension portal named the
    signed-in officer (G6). The band gives the powers and the designation; the name, where
    given, is the one every record carries -- the placeholder name is recorded only when the
    module is used on its own."""
    band, _, name = (officer_id or "").partition("|")
    o = next((x for x in OFFICERS if x["id"] == band.strip()), None)
    if not o:
        raise ServiceError(f"Unknown officer '{band}'.", 400)
    if name.strip():
        return {**o, "name": name.strip(), "named": True}
    return o


def _per_case(method):
    """Serialise the mutating service methods per case (audit 6 Oct 2026, G7).

    The API serves requests on a thread pool and every mutation here is read-modify-write on one
    CaseState: two officers acting on one case at once interleaved -- a disposition recorded
    on top of a re-run that had not finished, a history row for a version that was never
    saved. One re-entrant lock per case id, taken for the whole method."""
    @functools.wraps(method)
    def wrapped(self, case_id, *args, **kwargs):
        with self._lock_for(case_id):
            return method(self, case_id, *args, **kwargs)
    return wrapped


class CaseService:
    def __init__(self, repo: CaseRepository, docstore: DocumentStore, connector):
        self.repo = repo
        self.docs = docstore
        self.connector = connector
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, case_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(case_id)
            if lock is None:
                lock = self._locks[case_id] = threading.RLock()
            return lock

    # ── intake ────────────────────────────────────────────────────────────────
    def list_templates(self) -> list[dict]:
        out = []
        for k in all_case_keys():
            c = CASES[k]
            out.append({"key": k, "label": c.get("label"), "subject": c.get("subject"),
                        "kind": c.get("kind"), "family": c.get("family"),
                        "personnelNo": c.get("personnelNo"), "pages": c.get("pages"),
                        "hasSap": bool(CASES[k].get("sap"))})
        return out

    def create_case(self, template_key: str, *, without_sap: bool = False, officer_id: str = "ao") -> str:
        if template_key not in CASES:
            raise ServiceError(f"No such case template '{template_key}'.", 404)
        officer = _officer(officer_id)
        F = load_case(template_key, without_sap=without_sap)
        case_id = template_key + "-" + uuid.uuid4().hex[:8]
        s = CaseState(k=template_key, F=F, without_sap=without_sap, officer=officer)
        run_case(s, reason="Initial processing")
        s.log_audit("Case opened", {"template": template_key, "withoutSap": without_sap})
        self.repo.create(case_id, s)
        return case_id

    def create_case_from_facts(self, facts: dict, *, meta: dict, officer_id: str = "ao") -> str:
        """Open a case from an assembled facts object (produced by the reading pipeline)."""
        officer = _officer(officer_id)
        kind = facts.get("kind") or "unknown"
        case_id = kind + "-scan-" + uuid.uuid4().hex[:8]
        s = CaseState(k=case_id, F=facts, officer=officer, meta=meta)
        run_case(s, reason="Initial processing (from scans)")
        s.log_audit("Case opened from scans", {"kind": kind})
        self.repo.create(case_id, s)
        return case_id

    # ── read ────────────────────────────────────────────────────────────────────
    def _require(self, case_id: str) -> CaseState:
        s = self.repo.get(case_id)
        if not s:
            raise ServiceError(f"No such case '{case_id}'.", 404)
        return s

    def _meta(self, s: CaseState) -> dict:
        """Case metadata: the fixture template, or the reading-derived meta for scans."""
        if s.k in CASES:
            return CASES[s.k]
        base = s.meta or {}
        return {"label": base.get("label", "Case (from scans)"), "subject": base.get("subject", ""),
                "dept": base.get("dept", ""), "kind": s.F.get("kind"), "family": base.get("family", ""),
                "sub": base.get("sub", ""), "personnelNo": s.F.get("personnelNo"),
                "gazetted": s.F.get("gazetted"), "pages": base.get("pages"), "diary": base.get("diary"),
                "note": base.get("note"), "record": base.get("record", []), "pageIndex": base.get("pageIndex", [])}

    def list_cases(self) -> list[dict]:
        out = []
        for cid in self.repo.list_ids():
            s = self.repo.get(cid)
            pos = position(s)
            m = self._meta(s)
            out.append({"id": cid, "template": s.k, "label": m.get("label"),
                        "subject": m.get("subject"), "version": s.version,
                        "hard": pos["hard"], "conf": pos["conf"], "sap": pos["sap"],
                        "open": pos["open"], "issued": s.issued, "mayAdvance": pos["mayAdvance"]})
        return sorted(out, key=lambda x: x["id"])

    def view(self, case_id: str, officer_id: str | None = None) -> dict:
        """The examination as one officer sees it.

        ``officer_id`` is the band of the officer ASKING (the portal sends it on every framed
        request). What may be done to each observation, and to the case, is judged against that
        officer. Without it the answer falls back to ``s.officer`` -- whoever acted last -- which
        is what the screen used to show every reader, so a Senior Auditor was offered buttons
        that answered to an Accounts Officer's powers (audit 13 Oct 2026).
        """
        s = self._require(case_id)
        c = self._meta(s)
        try:
            viewer = _officer(officer_id) if officer_id else s.officer
        except ServiceError:
            viewer = s.officer
        L = lists(s.results)
        sap = s.F.get("sap")
        sap_view = None
        if sap:
            ps = sap.get("payslip") or {}
            rc = sap.get("recalc") or {}
            sap_view = {"present": True, "source": sap.get("source"), "file": sap.get("file"),
                        "payslip": {k: ps.get(k) for k in ("persNo", "name", "month", "bps",
                                    "gpfBalance", "loanBalance", "basicPay", "ddoCode")} if ps else None,
                        "recalc": {"reportDate": rc.get("reportDate"), "rows": len(rc.get("rows") or []),
                                   "lastClosing": (rc.get("rows") or [{}])[-1].get("closing")} if rc.get("rows") else None}
        return {
            "id": case_id, "template": s.k, "version": s.version, "issued": s.issued,
            "returns": s.returns, "withoutSap": s.without_sap,
            "caseDisp": getattr(s, "caseDisp", None), "caseNote": getattr(s, "caseNote", ""),
            "officer": s.officer,
            "meta": {k: c.get(k) for k in ("label", "subject", "dept", "kind", "family", "sub",
                     "personnelNo", "gazetted", "pages", "diary", "note", "nameNote")},
            "record": c.get("record") or [],
            "pageIndex": c.get("pageIndex") or [],
            "lists": {name: [self._result_view(r, s, viewer) for r in L[name]]
                      for name in ("hard", "adv", "conf", "sap", "ok")},
            "position": position(s),
            "sap": sap_view or {"present": False, "personnelNo": c.get("personnelNo")},
            # The fund and advance position the rules compute from (rules_family.fund_position).
            "balances": fund_position(s.F),
            "doa": {"status": doa_mod.DOA["status"], "version": doa_mod.DOA.get("version")},
            "history": s.history, "audit": s.audit, "uploads": s.uploads,
            "dispositions": s.disp,
            "disposalOptions": self._disposal_options(s, viewer),
        }

    def _diff_view(self, diff: Optional[dict]) -> dict:
        """Compact 'what changed' banner for the UI after a re-evaluation (§7.1)."""
        if not diff:
            return {"resolved": [], "raised": [], "changed": []}

        def brief(entry):
            r = entry["r"]
            return {"id": r["id"], "title": r.get("title") or r.get("doc"),
                    "status": r["status"], "was": entry.get("was"),
                    "code": r.get("code"), "finding": r.get("finding")}
        return {"resolved": [brief(e) for e in diff["resolved"]],
                "raised": [brief(e) for e in diff["raised"]],
                "changed": [brief(e) for e in diff["changed"]]}

    def _result_view(self, r: dict, s: CaseState, viewer: dict | None = None) -> dict:
        disp = s.disp.get(r["id"])
        keep = ("id", "code", "ref", "title", "doc", "status", "finding", "remedy",
                "evidence", "cure", "calc", "pair", "checklist", "group", "payload")
        v = {k: r.get(k) for k in keep if k in r}
        v["disposition"] = disp
        # What THIS officer may record against this observation, judged by the same rule the
        # service enforces (engine.may). The screen used to offer Uphold / Waive / Refer on
        # every hard or advisory item whatever the officer's band, so a press answered 403 and
        # the button looked broken (audit 13 Oct 2026).
        if viewer is not None and is_issue(r.get("status")):
            v["dispositionOptions"] = [
                {"action": a, "allowed": may(a, r.get("status"), viewer),
                 "reason": "" if may(a, r.get("status"), viewer) else f"Needs {who_can(a, r.get('status'))}."}
                for a in ("uphold", "waive", "correct", "refer")
            ]
        # The case pages the item rests on, beside any evidence the rule cut (reference_pages).
        from .reference_pages import reference_pages
        have = {e.get("page") for e in (v.get("evidence") or []) if isinstance(e, dict)}
        extra = [e for e in reference_pages(r, s.F or {}) if e["page"] not in have]
        if extra:
            v["evidence"] = list(v.get("evidence") or []) + extra
        return v

    # ── SAP extracts (R1, R8) ───────────────────────────────────────────────────
    @_per_case
    def upload_sap(self, case_id: str, filename: str, text: str, *, officer_id: str = "ao") -> dict:
        s = self._require(case_id)
        officer = _officer(officer_id)
        s.officer = officer
        try:
            self.connector.apply_to_case(s.F, filename, text)
        except ValueError as e:
            s.log_audit("SAP extract rejected", {"file": filename, "reason": str(e)})
            self.repo.save(case_id, s)
            raise ServiceError(str(e), 400)
        meta = self.docs.save(case_id, filename, text.encode("utf-8"), content_type="text/plain")
        meta.update({"kind": "sap", "at": _now(), "by": officer["name"]})
        s.uploads.append(meta)
        diff = run_case(s, reason=f"SAP extract uploaded ({filename})")
        s.log_audit("SAP extract accepted", {"file": filename, "hash": meta["hash"]})
        self.repo.save(case_id, s)
        return self._diff_view(diff)

    @_per_case
    def refresh_payslip_balances(self, case_id: str, gpf_balance, loan_balance, *, basis: str,
                                 officer_id: str = "ao") -> dict:
        """Fill the pay slip's fund and advance balances where the first reading left them empty.

        30 Sep 2026: the printed pay slip carries them in its LOAN/FUND block, which the reader
        passed over; they are now read from the page's OCR text (reading.payslip_text). A balance
        already on the case is never overwritten. The rules are run again, as on any change."""
        s = self._require(case_id)
        ps = (s.F.get("sap") or {}).get("payslip")
        if not ps:
            raise ServiceError("There is no SAP pay slip on this case.", 400)
        changed = {}
        if ps.get("gpfBalance") is None and gpf_balance is not None:
            ps["gpfBalance"] = float(gpf_balance); changed["gpfBalance"] = float(gpf_balance)
        if ps.get("loanBalance") is None and loan_balance is not None:
            ps["loanBalance"] = float(loan_balance); changed["loanBalance"] = float(loan_balance)
        if not changed:
            return {"changed": {}}
        s.officer = _officer(officer_id)
        diff = run_case(s, reason="Pay slip balances read from its LOAN/FUND block")
        s.log_audit("Pay slip balances re-read", {**changed, "basis": basis})
        self.repo.save(case_id, s)
        return {"changed": changed, "diff": self._diff_view(diff)}

    # ── cure by upload / verification (R2) ──────────────────────────────────────
    def _find_result(self, s: CaseState, result_id: str) -> dict:
        r = next((x for x in s.results if x["id"] == result_id), None)
        if not r:
            raise ServiceError(f"No open item '{result_id}' on this case.", 404)
        return r

    @_per_case
    def cure(self, case_id: str, result_id: str, values: dict, *,
             filename: Optional[str] = None, content: Optional[bytes] = None,
             officer_id: str = "ao") -> dict:
        s = self._require(case_id)
        officer = _officer(officer_id)
        s.officer = officer
        if not may("upload", None, officer):
            raise ServiceError("Not permitted to upload against this case.", 403)
        r = self._find_result(s, result_id)
        cure = r.get("cure")
        if not cure:
            raise ServiceError(f"Item '{result_id}' does not accept a document.", 400)
        kind = cure.get("kind")
        upload_meta = None
        if content is not None:
            upload_meta = self.docs.save(case_id, filename or "upload", content)
            upload_meta.update({"kind": kind, "against": result_id, "at": _now(), "by": officer["name"]})
            s.uploads.append(upload_meta)
        stored_name = filename or (upload_meta and upload_meta["name"]) or "upload"

        if kind == "sap":
            raise ServiceError("This item is cured on the SAP extracts step; upload the extract there.", 400)
        elif kind == "verify":
            self._apply_verification(s, cure["vid"], bool(values.get("ok", True)), values.get("note", ""), officer)
        elif kind == "qr":
            self._apply_qr_cure(s, cure.get("qid"), values, stored_name)
        elif kind == "doc":
            apply_key = cure.get("apply")
            fn = CURES.get(apply_key)
            if not fn:
                raise ServiceError(f"No cure handler for '{apply_key}'.", 500)
            fn(s.F, values, stored_name)
        else:
            raise ServiceError(f"Unknown cure kind '{kind}'.", 400)

        diff = run_case(s, reason=f"Document supplied against {result_id}")
        s.log_audit("Cure by upload", {"item": result_id, "kind": kind, "file": stored_name})
        self.repo.save(case_id, s)
        return self._diff_view(diff)

    @_per_case
    def verify(self, case_id: str, vid: str, ok: bool, note: str = "", *, officer_id: str = "ao") -> dict:
        s = self._require(case_id)
        officer = _officer(officer_id)
        s.officer = officer
        if not may("verify", None, officer):
            raise ServiceError(f"Recording a verification needs {who_can('verify', None)}.", 403)
        self._apply_verification(s, vid, ok, note, officer)
        diff = run_case(s, reason=f"Verification recorded ({vid})")
        s.log_audit("Verification recorded", {"vid": vid, "ok": ok, "note": note})
        self.repo.save(case_id, s)
        return self._diff_view(diff)

    def _apply_verification(self, s: CaseState, vid: str, ok: bool, note: str, officer: dict) -> None:
        s.F.setdefault("verifications", {})[vid] = {
            "ok": ok, "by": officer["name"], "desig": officer["desig"], "at": _now(), "note": note}

    def _apply_qr_cure(self, s: CaseState, qid: str, values: dict, filename: str) -> None:
        q = next((x for x in (s.F.get("qr") or []) if x["id"] == qid), None)
        if not q:
            raise ServiceError(f"No QR item '{qid}'.", 404)
        q["decoded"] = True
        q["notSupplied"] = None
        q["page"] = q.get("page") or ("upload: " + filename)
        if "payload" in values:
            q["payload"] = values["payload"]
        agrees = values.get("agrees", True)
        q["compare"] = [{"field": "Content", "qrVal": values.get("payload", "(decoded)"),
                         "docVal": "the document", "docLabel": "document", "match": bool(agrees)}]

    # ── dispositions (§13.2) ────────────────────────────────────────────────────
    @_per_case
    def set_disposition(self, case_id: str, result_id: str, action: str, *,
                        ground: str = "", authority: str = "", officer_id: str = "ao") -> dict:
        s = self._require(case_id)
        officer = _officer(officer_id)
        s.officer = officer
        r = self._find_result(s, result_id)
        if not is_issue(r["status"]):
            raise ServiceError("Only observations (hard stops / advisories) take a disposition.", 400)
        sev = r["status"]
        if action not in ("uphold", "waive", "correct", "refer"):
            raise ServiceError(f"Unknown disposition '{action}'.", 400)
        if not may(action, sev, officer):
            raise ServiceError(f"{action.title()} on a {sev} observation needs {who_can(action, sev)}.", 403)
        # Written grounds for every disposition (business decision G1, 7 Oct 2026): upholding,
        # correcting and referring were recorded with nothing said, and a decision with no
        # reason cannot be checked by the next desk.
        if len((ground or "").strip()) < MIN_GROUND:
            raise ServiceError(f"Every disposition needs written grounds of at least {MIN_GROUND} characters "
                               f"(what was seen, and why the item is {action}{'ed' if action != 'refer' else 'red'}).", 400)
        if action == "waive" and not (authority or "").strip():
            raise ServiceError("A waiver needs the authority relied on as well as its ground.", 400)
        s.disp[result_id] = {"action": action, "ground": ground, "authority": authority,
                             "by": officer["name"], "desig": officer["desig"], "at": _now(),
                             # What the officer saw when deciding; a re-run that changes the
                             # observation marks this disposition stale (engine.reconcile_dispositions).
                             "fingerprint": fingerprint(r)}
        s.log_audit("Disposition", {"item": result_id, "action": action, "ground": ground, "authority": authority})
        self.repo.save(case_id, s)
        return {"disposition": s.disp[result_id], "position": position(s)}

    # ── disposal gates (§13.3) ──────────────────────────────────────────────────
    def _disposal_options(self, s: CaseState, viewer: dict | None = None) -> list[dict]:
        # Judged against the officer asking, not against whoever acted last: s.officer is
        # overwritten by every mutation, so the gates a reader saw were another officer's
        # (audit 13 Oct 2026). dispose() re-checks for real on the way in.
        who = viewer or s.officer
        pos = position(s)
        opts = []

        def opt(action, allowed, reason=""):
            opts.append({"action": action, "allowed": allowed, "reason": reason})

        undisposed = pos["open"]
        second_return = s.returns >= 1
        if pos["total"] == 0:
            opt("return", False, "No observation to issue.")
        elif second_return and who["level"] < 3:
            opt("return", False, "A second return needs the DAG (Funds) / DAO I.")
        else:
            opt("return", True)
        pay_ok = pos["hard"] == 0 and pos["conf"] == 0 and pos["sap"] == 0 and undisposed == 0 and who["level"] >= 2
        pay_reason = ""
        if pos["hard"]:
            pay_reason = f"{pos['hard']} hard stop(s) open."
        elif pos["conf"]:
            pay_reason = f"{pos['conf']} verification task(s) open."
        elif pos["sap"]:
            pay_reason = f"{pos['sap']} SAP item(s) open."
        elif undisposed:
            pay_reason = f"{undisposed} observation(s) undisposed."
        elif who["level"] < 2:
            pay_reason = "Needs the Accounts Officer or above."
        opt("pay", pay_ok, pay_reason)
        opt("part", who["level"] >= 2 and pos["hard"] == 0,
            "" if (who["level"] >= 2 and pos["hard"] == 0) else "Needs the Accounts Officer or above and no hard stop.")
        opt("refer", True)
        opt("hold", True)
        return opts

    @_per_case
    def dispose(self, case_id: str, disposal: str, *, note: str = "", officer_id: str = "ao") -> dict:
        s = self._require(case_id)
        officer = _officer(officer_id)
        s.officer = officer
        allowed = {o["action"]: o for o in self._disposal_options(s)}
        if disposal not in allowed:
            raise ServiceError(f"Unknown disposal '{disposal}'.", 400)
        gate = allowed[disposal]
        if not gate["allowed"]:
            raise ServiceError(gate["reason"] or f"Cannot {disposal} this case yet.", 403)
        if disposal == "return":
            s.returns += 1
            s.issued = True
            s.caseDisp = "returned"
        elif disposal in ("pay", "part"):
            s.issued = True
            s.caseDisp = "passed for payment" if disposal == "pay" else "passed for part payment"
        elif disposal == "refer":
            s.caseDisp = "referred to the DAG (Funds)"
        elif disposal == "hold":
            s.caseDisp = "held pending verification"
        s.caseNote = note
        s.log_audit("Disposal", {"disposal": disposal, "note": note, "returns": s.returns})
        self.repo.save(case_id, s)
        return {"disposal": disposal, "caseDisp": getattr(s, "caseDisp", None),
                "returns": s.returns, "issued": s.issued}

    # ── issue pack (§13.4) ──────────────────────────────────────────────────────
    def issue_pack(self, case_id: str) -> dict:
        s = self._require(case_id)
        c = self._meta(s)
        L = lists(s.results)
        rejection = [self._result_view(r, s) for r in L["hard"] if (disposition_in_force(s.disp.get(r["id"])) or {}).get("action") != "waive"]
        advisory = [self._result_view(r, s) for r in L["adv"] if (disposition_in_force(s.disp.get(r["id"])) or {}).get("action") != "waive"]
        waived = [{**self._result_view(r, s)} for r in L["obs"] if (disposition_in_force(s.disp.get(r["id"])) or {}).get("action") == "waive"]
        return {
            "case": {"id": case_id, "label": c.get("label"), "subject": c.get("subject"),
                     "personnelNo": c.get("personnelNo"), "dept": c.get("dept"), "diary": c.get("diary")},
            "generatedAt": _now(), "version": s.version, "caseDisposal": getattr(s, "caseDisp", None),
            "rejectionForm": rejection,
            "advisoryMemo": advisory,
            "waivedAndSettled": waived,
            "verifications": s.F.get("verifications", {}),
            "sapExtracts": [u for u in s.uploads if u.get("kind") == "sap"],
            "uploadedDocuments": [u for u in s.uploads if u.get("kind") != "sap"],
            "caseHistory": s.history,
            "auditTrail": s.audit,
            "paymentRegisterEntry": {  # circular C(i)
                "personnelNo": c.get("personnelNo"), "subscriber": c.get("subject"),
                "caseType": c.get("label"), "disposal": getattr(s, "caseDisp", None), "at": _now()},
            "portalComment": self._portal_comment(rejection, advisory),
        }

    def _portal_comment(self, rejection: list, advisory: list) -> str:
        # Employee Service Portal comment text, single instance (circular para 2).
        items = rejection + advisory
        if not items:
            return "No observations. Case in order for the next stage."
        lines = [f"{r.get('code') or r.get('ref')}: {r.get('finding')}" for r in items]
        return "Observations (single instance):\n" + "\n".join(lines)

    # ── DOA admin (§8) ──────────────────────────────────────────────────────────
    def doa_register(self) -> dict:
        return {"status": doa_mod.DOA["status"], "version": doa_mod.DOA.get("version"),
                "authorities": doa_mod.DOA["authorities"]}

    def doa_add_specimen(self, case_id_for_file: Optional[str], sig_id: str, filename: str,
                         content: bytes, *, officer_id: str = "ao") -> dict:
        officer = _officer(officer_id)
        if officer["level"] < 2:
            raise ServiceError("Uploading a specimen needs the Accounts Officer or above.", 403)
        meta = self.docs.save(case_id_for_file or "doa", filename, content)
        ok = doa_mod.doa_set_specimen(sig_id, meta["storedAs"], by=officer["name"], at=_now())
        if not ok:
            raise ServiceError(f"No signatory '{sig_id}' on the register.", 404)
        return {"ok": True, "signatory": sig_id, "specimen": meta}

    def doa_add_signatory(self, authority_id: str, post: str, *, name: str = "", may_for: bool = False,
                          powers: str = "", officer_id: str = "ao") -> dict:
        officer = _officer(officer_id)
        if officer["level"] < 3:
            raise ServiceError("Adding a signatory needs the DAG (Funds).", 403)
        sig = doa_mod.doa_add_signatory(authority_id, post, name=name, may_for=may_for, powers=powers)
        if not sig:
            raise ServiceError(f"No authority '{authority_id}' on the register.", 404)
        return {"ok": True, "signatory": sig}

    def doa_finalize(self, *, officer_id: str = "ao") -> dict:
        officer = _officer(officer_id)
        if officer["level"] < 3:
            raise ServiceError("Marking the register final needs the DAG (Funds).", 403)
        doa_mod.doa_finalize(published_by=officer["name"], published_at=_now())
        # The shared master store's GP Fund rows become final with it (C1, 9 Oct 2026).
        from .signatories import mark_gpf_final
        made_final = mark_gpf_final(getattr(self.repo, "conn", None))
        return {"ok": True, "status": doa_mod.DOA["status"], "master_rows_made_final": made_final}
