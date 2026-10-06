"""Delegation of Authority (DOA) register and lookup.

Faithful port of doa.js + doa_seed.js. The register is PROVISIONAL: built
from the signatories seen in the eight case files, with no specimen on record.
A provisional entry never raises a hard stop on its own; it creates a
verification task. The AG Office will supply the real register (open item
GPF-O14).
"""
from __future__ import annotations

import re
from typing import Optional

# (regex, replacement) — expand common designation abbreviations before matching.
_DOA_ABBR = [
    (re.compile(r"\bs\.?\s?p\b\.?"), "superintendent of police"),
    (re.compile(r"\bd\.?i\.?g\b\.?"), "deputy inspector general"),
    (re.compile(r"\bc\.?e\.?o\b\.?"), "chief executive officer"),
    (re.compile(r"\bd\.?e\.?a\b\.?"), "district education authority"),
    (re.compile(r"\bc\.?t\.?o\b\.?"), "chief traffic officer"),
    (re.compile(r"\bs\.?t\.?o\b\.?"), "senior traffic officer"),
    (re.compile(r"\bd\.?d\.?o\b\.?"), "drawing and disbursing officer"),
    (re.compile(r"\bd\.?a\.?o\b\.?"), "district accounts officer"),
    (re.compile(r"\badmn\b\.?"), "admin"),
    (re.compile(r"\bhq\b|\bheadquarters?\b|\bheadquarter\b"), "headquarters"),
    (re.compile(r"\bf\s*/\s*o\b|\bfor\b|\bon behalf of\b"), " "),
]


def doa_norm(s) -> str:
    t = re.sub(r"[(),.:;]", " ", str(s if s is not None else "").lower())
    for rx, rep in _DOA_ABBR:
        t = rx.sub(rep, t)
    return re.sub(r"\s+", " ", t).strip()


def doa_score(a, b) -> float:
    A = {w for w in doa_norm(a).split(" ") if len(w) > 2}
    B = {w for w in doa_norm(b).split(" ") if len(w) > 2}
    if not A or not B:
        return 0.0
    hit = sum(1 for w in A if w in B)
    return hit / min(len(A), len(B))


def doa_lookup(authority_text, signatory_text) -> dict:
    """Match the authority a document is issued for, then the person who signed.

    Returns what the register says, never a verdict on the ink.
    """
    best, bs = None, 0.0
    for a in DOA.get("authorities", []):
        candidates = [doa_score(authority_text, a["authority"])]
        candidates += [doa_score(authority_text, x) for x in a.get("aliases", [])]
        s = max(candidates)
        if s > bs:
            bs, best = s, a
    if not best or bs < 0.6:
        return {"status": "authority_not_listed", "authority": None, "signatory": None}
    sig, ss = None, 0.0
    for g in best["signatories"]:
        s = doa_score(signatory_text, g["post"] + " " + (g.get("name") or ""))
        if s > ss:
            ss, sig = s, g
    if not sig or ss < 0.6:
        return {"status": "signatory_not_listed", "authority": best, "signatory": None}
    status = "listed_with_specimen" if sig.get("specimen") else "listed_no_specimen"
    return {"status": status, "authority": best, "signatory": sig}


def doa_find_signatory(sig_id: str):
    for a in DOA["authorities"]:
        for g in a["signatories"]:
            if g["id"] == sig_id:
                return a, g
    return None, None


def doa_set_specimen(sig_id: str, image_ref: str, *, by: str = "", at: str = "") -> bool:
    """Record a specimen signature against a signatory (spec §8.2). Register only."""
    _, g = doa_find_signatory(sig_id)
    if not g:
        return False
    g["specimen"] = {"imageRef": image_ref, "capturedBy": by, "capturedAt": at, "active": True}
    return True


def doa_add_signatory(authority_id: str, post: str, *, name: str = "", may_for: bool = False,
                      powers: str = "") -> Optional[dict]:
    a = next((x for x in DOA["authorities"] if x["id"] == authority_id), None)
    if not a:
        return None
    sig = {"id": authority_id + "-" + re.sub(r"[^a-z0-9]", "", post.lower())[:12],
           "post": post, "name": name, "mayFor": may_for, "powers": powers, "specimen": None}
    a["signatories"].append(sig)
    return sig


def doa_finalize(published_by: str = "", published_at: str = "") -> None:
    """Mark the register final. From here, an unlisted signatory is a hard stop (§8.3)."""
    DOA["status"] = "final"
    DOA["publishedBy"] = published_by
    DOA["publishedAt"] = published_at


def doa_status_text(m: dict) -> str:
    if m["status"] == "authority_not_listed":
        return "The authority is not yet on the DOA register."
    if m["status"] == "signatory_not_listed":
        return ("The person who signed is not listed as an approved signatory for "
                + m["authority"]["authority"] + ".")
    sig = m["signatory"]
    if sig.get("mayFor"):
        who = (sig["post"] + " is on the register as authorised to sign for "
               + m["authority"]["authority"] + ".")
    else:
        who = (sig["post"] + " is on the register for " + m["authority"]["authority"]
               + ", signing in own name.")
    if m["status"] == "listed_no_specimen":
        return who + " No specimen signature is on the register yet."
    return who + " Compare the signature with the specimen."


# PROVISIONAL register — replace with the office's DOA list (GPF-O14).
DOA = {
    "status": "provisional",
    "version": ("Provisional, built on 15-09-2026 from the signatories in the eight "
                "case files. The office will supply the approved list and specimens."),
    "authorities": [
        {"id": "police-dig-ops", "dept": "Punjab Police",
         "authority": "Deputy Inspector General of Police, Operations, Lahore",
         "aliases": ["DIG Operations Lahore"],
         "signatories": [
             {"id": "dig", "post": "Deputy Inspector General of Police, Operations, Lahore",
              "name": "", "mayFor": False, "powers": "Sanction of GP Fund advances", "specimen": None},
             {"id": "sphq", "post": "SP Headquarters", "name": "", "mayFor": True,
              "powers": "Signs advance sanctions and Form 05 for the DIG", "specimen": None}]},
        {"id": "sed-dea-lahore", "dept": "School Education Department",
         "authority": "Chief Executive Officer, District Education Authority Lahore",
         "aliases": ["CEO (DEA) Lahore"],
         "signatories": [
             {"id": "ceo", "post": "Chief Executive Officer (DEA) Lahore", "name": "",
              "mayFor": False, "powers": "Sanction of GP Fund advances", "specimen": None},
             {"id": "adadmin", "post": "Assistant Director (Admin)", "name": "", "mayFor": True,
              "powers": "Signs advance sanctions for the CEO", "specimen": None}]},
        {"id": "gghs-ra-bazar", "dept": "School Education Department",
         "authority": "Senior Headmistress, Govt. Girls High School R.A. Bazar Lahore",
         "signatories": [
             {"id": "shm", "post": "Senior Headmistress", "name": "", "mayFor": False,
              "powers": "DDO LV6280: change forms", "specimen": None}]},
        {"id": "hmd-lahore", "dept": "Communication and Works",
         "authority": "Executive Engineer, Highway Mechanical Division, Lahore",
         "signatories": [
             {"id": "xen", "post": "Executive Engineer, Highway Mechanical Division", "name": "",
              "mayFor": False, "powers": "DDO LO5361: GPF-10, change forms", "specimen": None}]},
        {"id": "cto-lahore", "dept": "Punjab Police, City Traffic Police",
         "authority": "Chief Traffic Officer, Lahore",
         "signatories": [
             {"id": "cto", "post": "Chief Traffic Officer, Lahore", "name": "", "mayFor": False,
              "powers": "DDO L04087: change forms, forwarding", "specimen": None}]},
        {"id": "pimh", "dept": "Specialized Healthcare and Medical Education",
         "authority": "Executive Director, Punjab Institute of Mental Health, Lahore",
         "signatories": [
             {"id": "ed", "post": "Executive Director, Punjab Institute of Mental Health",
              "name": "", "mayFor": False, "powers": "DDO L04578: change forms", "specimen": None}]},
        {"id": "gac-mustafabad", "dept": "Higher Education Department",
         "authority": "Principal, Govt. Associate College (W) Mustafabad, Lahore",
         "signatories": [
             {"id": "principal", "post": "Principal, Govt. Associate College (W) Mustafabad",
              "name": "", "mayFor": False,
              "powers": "DDO: GPF-10, change forms, attestation", "specimen": None}]},
        {"id": "treasury-lahore", "dept": "Finance Department, Treasury",
         "authority": "Treasury Office, Lahore",
         "signatories": [
             {"id": "dto", "post": "Deputy Treasury Officer, Lahore", "name": "", "mayFor": False,
              "powers": "Verification of challans", "specimen": None}]},
        {"id": "dpr-fsd", "dept": "Directorate General Public Relations",
         "authority": "Director Public Relations, Faisalabad",
         "signatories": [
             {"id": "dpr", "post": "Director Public Relations, Faisalabad (DDO)", "name": "",
              "mayFor": False, "powers": "Balance transfer proforma", "specimen": None}]},
        {"id": "dao-fsd", "dept": "Finance Department, District Accounts",
         "authority": "District Accounts Office, Faisalabad",
         "aliases": ["District Accounts Officer Faisalabad"],
         "signatories": [
             {"id": "dao", "post": "District Accounts Officer, Faisalabad", "name": "",
              "mayFor": False, "powers": "Confirms GP Fund account, forwards to AG", "specimen": None}]},
    ],
}
