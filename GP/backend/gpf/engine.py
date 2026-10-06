"""The rules engine.

The reading stage produces FACTS. Plain rules turn facts into results. Nothing
in here reads an image or calls a model. An upload changes the facts; the case
is then re-evaluated from scratch and compared with the previous run, so a
cured observation is closed by the same rule that raised it.

Result status vocabulary
  ok    satisfied
  sub   satisfied by an accepted substitute (e.g. challans for a certificate)
  hard  not satisfied, the case cannot advance      (goes on the rejection form)
  adv   observation, does not block                  (advisory memorandum)
  conf  officer to verify (signature, specimen, thumb impression, QR online)
  sap   awaiting SAP extract, action for this section, not a department defect
  na    not applicable
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .registry import CHECKS, CUSTOM_CHECKS, Check

STLAB = {
    "ok": ("ok", "Satisfied"),
    "sub": ("sub", "Satisfied by substitute"),
    "hard": ("hard", "Not satisfied"),
    "adv": ("adv", "Observation"),
    "conf": ("conf", "Officer to verify"),
    "sap": ("sap", "Awaiting SAP extract"),
    "na": ("pend", "Not applicable"),
}


def is_issue(status: str) -> bool:
    return status in ("hard", "adv")


def clone(o):
    return copy.deepcopy(o)


def _resolve_checklist(cl, F):
    return cl(F) if callable(cl) else cl


def evaluate(F: dict) -> list[dict]:
    """Evaluate every applicable check against the facts."""
    out: list[dict] = []
    all_checks: list[Check] = list(CHECKS) + [
        CUSTOM_CHECKS[c] for c in (F.get("custom") or []) if c in CUSTOM_CHECKS
    ]
    for ch in all_checks:
        try:
            applies = bool(ch.applies(F))
        except Exception:
            applies = False
        if not applies:
            continue
        try:
            r = ch.run(F)
        except Exception as e:  # a rule that cannot evaluate never crashes the engine
            r = {"status": "conf",
                 "finding": "The rule could not be evaluated on the facts available ("
                            + str(e) + "). Check by hand."}
        if not r:
            continue
        items = r if isinstance(r, list) else [r]
        for one in items:
            if not one:
                continue
            base = {
                "id": ch.id, "group": ch.group, "ref": ch.ref,
                "code": ch.code or ch.ref, "title": ch.title,
                "checklist": _resolve_checklist(ch.checklist, F),
                "doc": ch.title, "evidence": [], "cure": None,
            }
            base.update(one)
            # JS truthiness: sub == 0 / "" is falsy, so only a truthy sub adds a suffix.
            base["id"] = (ch.id + ":" + str(one["sub"])) if one.get("sub") else ch.id
            out.append(base)
    return out


def lists(results: list[dict]) -> dict:
    hard = [r for r in results if r["status"] == "hard"]
    adv = [r for r in results if r["status"] == "adv"]
    obs = sorted([r for r in results if is_issue(r["status"])],
                 key=lambda x: 0 if x["status"] == "hard" else 1)
    return {
        "hard": hard,
        "adv": adv,
        "obs": obs,
        "conf": [r for r in results if r["status"] == "conf"],
        "sap": [r for r in results if r["status"] == "sap"],
        "ok": [r for r in results if r["status"] in ("ok", "sub")],
    }


def _open(status) -> bool:
    return status is not None and (is_issue(status) or status in ("conf", "sap"))


def diff_runs(prev: list[dict], nxt: list[dict]) -> dict:
    """Compare two runs of the same case (what resolved / was raised / changed)."""
    pm = {r["id"]: r for r in prev}
    nm = {r["id"]: r for r in nxt}
    d = {"resolved": [], "raised": [], "changed": [], "stillOpen": []}
    for r in nxt:
        p = pm.get(r["id"])
        was = p["status"] if p else None
        open_now = _open(r["status"])
        open_before = _open(was)
        if open_before and not open_now:
            d["resolved"].append({"r": r, "was": was})
        elif not open_before and open_now:
            d["raised"].append({"r": r, "was": was})
        elif open_before and open_now and was != r["status"]:
            d["changed"].append({"r": r, "was": was})
        elif open_now:
            d["stillOpen"].append({"r": r, "was": was})
    for p in prev:
        if p["id"] not in nm and _open(p["status"]):
            d["resolved"].append({"r": {**p, "status": "na"}, "was": p["status"]})
    return d


# ── Delegation of powers INSIDE this office (who may dispose of what) ──────────
OFFICERS = [
    {"id": "da", "name": "Muhammad Adnan", "desig": "Dealing Assistant, GP Fund-I", "grade": "BS-16", "level": 1},
    {"id": "ao", "name": "Sadia Rehman", "desig": "Accounts Officer, GP Fund-I", "grade": "BS-18", "level": 2},
    {"id": "dag", "name": "Fatima Hameed", "desig": "Deputy Accountant General (Funds)", "grade": "BS-20", "level": 3},
]


def may(action: str, sev: Optional[str], officer: dict) -> bool:
    L = officer["level"]
    if action == "uphold":
        return True
    if action == "refer":
        return L <= 2
    if action == "correct":
        return L >= 2
    if action == "waive":
        return L >= 3 if sev == "hard" else L >= 2
    if action == "verify":
        return L >= 2
    if action == "upload":
        return True
    return False


def who_can(action: str, sev: Optional[str]) -> str:
    if action == "correct":
        return "the Accounts Officer or above"
    if action == "verify":
        return "the Accounts Officer or above"
    if action == "waive":
        return ("the Deputy Accountant General (Funds)" if sev == "hard"
                else "the Accounts Officer or above")
    return ""


def _stamp() -> str:
    d = datetime.datetime.now()
    return d.strftime("%d-%m-%Y %H:%M")


@dataclass
class CaseState:
    """Versioned case state: facts + recomputed results + audit trail.

    Results are ALWAYS recomputed from facts (never edited). Re-evaluating an
    earlier facts version reproduces its results exactly.
    """
    k: str
    F: dict
    without_sap: bool = False
    officer: dict = field(default_factory=lambda: OFFICERS[1])
    version: int = 1
    results: list[dict] = field(default_factory=list)
    prev: Optional[list[dict]] = None
    last_diff: Optional[dict] = None
    history: list[dict] = field(default_factory=list)
    disp: dict = field(default_factory=dict)
    audit: list[dict] = field(default_factory=list)
    returns: int = 0
    issued: bool = False
    uploads: list[dict] = field(default_factory=list)
    caseDisp: Optional[str] = None
    caseNote: str = ""
    meta: Optional[dict] = None   # set for cases created from scans (no fixture template)

    def log_audit(self, what: str, detail: Any = None) -> None:
        self.audit.append({"at": _stamp(), "by": self.officer["name"],
                           "desig": self.officer["desig"], "grade": self.officer["grade"],
                           "what": what, "detail": detail})


def new_state(cases: dict, k: str, without_sap: bool = False, officer: dict = None) -> CaseState:
    F = clone(cases[k])
    if without_sap:
        F["sap"] = None
        F["persNos"] = [x for x in (F.get("persNos") or [])
                        if not _re_sap(x.get("doc", ""))]
    return CaseState(k=k, F=F, without_sap=without_sap,
                     officer=officer or OFFICERS[1])


def _re_sap(doc: str) -> bool:
    import re
    return bool(re.search(r"SAP|Re-calculation", doc, re.I))


def run_case(s: CaseState, reason: str = "") -> Optional[dict]:
    """Re-evaluate the case from its current facts, diffing against the last run."""
    nxt = evaluate(s.F)
    if s.results:
        s.prev = s.results
        s.last_diff = diff_runs(s.results, nxt)
        s.version += 1
    s.results = nxt
    L = lists(nxt)
    s.history.append({
        "v": s.version, "at": _stamp(), "by": s.officer["name"], "desig": s.officer["desig"],
        "reason": reason, "hard": len(L["hard"]), "adv": len(L["adv"]),
        "conf": len(L["conf"]), "sap": len(L["sap"]),
        "resolved": len(s.last_diff["resolved"]) if (s.last_diff and s.version > 1) else 0,
        "raised": len(s.last_diff["raised"]) if (s.last_diff and s.version > 1) else 0,
    })
    reconcile_dispositions(s, nxt)
    return s.last_diff


def fingerprint(result: dict) -> str:
    """What a disposition was given against: the observation's severity and wording, which carry
    its figures. A waiver of "Rs 50,000 over the limit" does not cover "Rs 250,000 over the limit"."""
    return hashlib.sha1(json.dumps({"status": result.get("status"), "finding": result.get("finding")},
                                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reconcile_dispositions(s: "CaseState", nxt: list) -> None:
    """Carry the officers' dispositions across a re-run, honestly.

    A disposition on an observation that no longer exists is kept, marked cured. One whose
    observation is still open but now says something else -- the amount changed after a cure or
    a corrected reading -- is kept for the record but marked stale, and counts as open again
    until an officer disposes of the new finding (audit 6 Oct 2026, G2). Before this a waiver
    granted on one figure silently covered any figure the item later showed.
    """
    for rid in list(s.disp.keys()):
        d = s.disp[rid]
        r = next((x for x in nxt if x["id"] == rid), None)
        if not r or not is_issue(r["status"]):
            d["cured"] = True
            continue
        d.pop("cured", None)
        given_against = d.get("fingerprint")
        if given_against and given_against != fingerprint(r):
            d["stale"] = True
            d["staleSince"] = d.get("staleSince") or _stamp()
        else:
            d.pop("stale", None)
            d.pop("staleSince", None)


def disposition_in_force(d: Optional[dict]) -> Optional[dict]:
    """The disposition that applies to an observation now: none if it has gone stale."""
    if d and not d.get("stale"):
        return d
    return None


def position(s: CaseState) -> dict:
    """Live position of the case after dispositions."""
    L = lists(s.results)
    hard = adv = waived = corrected = referred = open_ = 0
    for o in L["obs"]:
        d = disposition_in_force(s.disp.get(o["id"]))
        if d and d.get("action") == "waive":
            waived += 1
            continue
        if d and d.get("action") == "correct":
            corrected += 1
            continue
        if d and d.get("action") == "refer":
            referred += 1
        if o["status"] == "hard":
            hard += 1
        else:
            adv += 1
        if not d:
            open_ += 1
    return {"hard": hard, "adv": adv, "waived": waived, "corrected": corrected,
            "referred": referred, "open": open_, "total": len(L["obs"]),
            "conf": len(L["conf"]), "sap": len(L["sap"]), "mayAdvance": hard == 0}
