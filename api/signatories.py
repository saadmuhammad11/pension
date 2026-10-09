"""Signing authorities and their specimen signatures: one master store for pension and GP Fund.

Scope change C1 of 9 Oct 2026. Until then pension kept one specimen authority in
``rules/specimens/register.json`` (S&GAD's Additional Secretary (Admn), three images, in force from
9 September 2025) and GP Fund a provisional delegation-of-authority register with no specimens
(``GP/backend/gpf/doa.py``). Both are imported into the ``signing_authorities`` and
``signatory_specimens`` tables (migration 0013) and maintained from the administrator's screen.

How the two products read it:

* **Pension** (stage 6b, ``pipeline/signatory.py``; the findings in ``rules.flags.check_psa_specimen``)
  reads the register through ``rules.specimens``, which is standard library and reads a JSON file.
  So the master store is **exported** to ``artifacts/signatories/register.json`` -- in that file's
  shape, with the specimen images beside it -- after every change, and ``rules.specimens.ACTIVE``
  is pointed at the export (``activate()``). The bundled file remains the fallback where the API
  has not run (pipeline tests, a box without a database).
* **GP Fund** (its own process) reads the tables directly through the shared database
  (``GP/backend/gpf/signatories.py``) and shows the specimens on its "Signatories and delegation of
  authority" task.

Rows are never deleted: an authority is closed with an end date; every change is an audit row.
Specimen images are served only to AG-side roles and the administrator, with ``Cache-Control:
no-store``, and every view is audited (``SPECIMEN_VIEWED``). A DDO never receives one.

    python3 -m api.signatories import     # the two legacy registers, idempotent
    python3 -m api.signatories export     # rewrite the JSON export the pipeline reads
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from api import db, workflow
from api.auth import User, current_user, current_user_q, require_roles, get_conn
from rules import specimens as _specimens

ROOT = Path(__file__).resolve().parents[1]
#: Where the specimen and letter images live and where the export is written. Tests patch it.
STORE_DIR = ROOT / "artifacts" / "signatories"
EXPORT_NAME = "register.json"
MAX_SPECIMENS = 5
PRODUCTS = ("PENSION", "GPF", "BOTH")
SOURCES = ("PENSION_REGISTER", "GPF_PROVISIONAL", "ADMIN")
IMAGE_TYPES = {b"\xff\xd8\xff": ("image/jpeg", ".jpg"), b"\x89PNG": ("image/png", ".png")}
LETTER_TYPES = {**IMAGE_TYPES, b"%PDF": ("application/pdf", ".pdf")}
MAX_IMAGE = 8 * 1024 * 1024
#: The date GP Fund's provisional register was drawn up (gpf/doa.py's version line).
GPF_PROVISIONAL_FROM = "2026-09-15"

router = APIRouter(prefix="/api/v2/signatories", tags=["signatories"])


def viewer_roles() -> tuple[str, ...]:
    """Who may see a specimen: the AG's side (the tiers and the Deputy AG), the legacy reviewer role
    (read-only, Q5) and the administrator. Never a DDO (Q6)."""
    return tuple(workflow.AG_SIDE) + tuple(getattr(workflow, "LEGACY_AG_ROLES", ())) + ("ADMIN",)


# -- rows ------------------------------------------------------------------------------------------

def _row(r: db.Row | dict, specimens_: list[dict] | None = None) -> dict:
    d = dict(r)
    d["department_aliases"] = json.loads(d.pop("department_aliases_json") or "[]")
    d["post_aliases"] = json.loads(d.pop("post_aliases_json") or "[]")
    d["provisional"] = bool(d.get("provisional"))
    d["may_sign_for"] = bool(d.get("may_sign_for"))
    d["closed"] = bool(d.get("closed_at")) or bool(d.get("effective_to") and d["effective_to"] < date.today().isoformat())
    d["has_letter"] = bool(d.pop("letter_path", None))
    if specimens_ is not None:
        d["specimens"] = specimens_
    return d


def _specimen_rows(conn: db.Connection, authority_id: str) -> list[dict]:
    return [{"id": s["id"], "name": Path(s["stored_path"]).name, "uploaded_at": s["uploaded_at"],
             "uploaded_by": s["uploaded_by"], "note": s["note"]}
            for s in conn.execute("SELECT * FROM signatory_specimens WHERE authority_id = ? ORDER BY uploaded_at, id",
                                  (authority_id,))]


def list_authorities(conn: db.Connection, *, department: str | None = None, post: str | None = None,
                     product: str | None = None, include_closed: bool = True) -> list[dict]:
    where, args = ["1 = 1"], []
    if product:
        where.append("(product_scope = ? OR product_scope = 'BOTH')"); args.append(product)
    if not include_closed:
        where.append("closed_at IS NULL AND (effective_to IS NULL OR effective_to >= ?)"); args.append(date.today().isoformat())
    rows = conn.execute(f"SELECT * FROM signing_authorities WHERE {' AND '.join(where)} "
                        "ORDER BY department_name, post, effective_from", args).fetchall()
    out = []
    for r in rows:
        d = _row(r, _specimen_rows(conn, r["id"]))
        if department and not (_mentions(department, [d["department_name"], d.get("department_code") or "", *d["department_aliases"]])):
            continue
        if post and not _mentions(post, [d["post"], *d["post_aliases"]]):
            continue
        out.append(d)
    return out


def get_authority(conn: db.Connection, authority_id: str) -> dict:
    r = conn.execute("SELECT * FROM signing_authorities WHERE id = ?", (authority_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such signing authority")
    return _row(r, _specimen_rows(conn, authority_id))


def _mentions(text: str, names: list[str]) -> bool:
    return _specimens._mentions(text, tuple(n for n in names if n))


def _department_code_for(name: str, aliases: list[str]) -> str | None:
    """The api.departments code a department name maps to, by name, alias or the register's own aliases."""
    from api.departments import DEPARTMENTS
    wanted = _specimens._key(name)
    for d in DEPARTMENTS:
        if _specimens._key(d.name) == wanted or _specimens._key(d.name) in (_specimens._key(a) for a in aliases):
            return d.code
    for d in DEPARTMENTS:
        if _mentions(d.name, [name, *aliases]) or _mentions(name, [d.name]):
            return d.code
    return None


def _iso_or_422(value: Any, field: str, required: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise HTTPException(422, f"{field} is required (YYYY-MM-DD)")
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise HTTPException(422, f"{field} must be a date, YYYY-MM-DD") from None


def _list_or_422(value: Any, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [v.strip() for v in value.split(";")]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise HTTPException(422, f"{field} must be a list of names")
    return [" ".join(v.split()) for v in value if v.strip()][:20]


def _audit(conn: db.Connection, actor: Any, action: str, authority_id: str, *, before: dict | None,
           after: dict | None, reason: str = "", request: Request | None = None) -> None:
    from api.v2 import _client_address
    workflow.audit(conn, actor=actor, action=action, entity_type="signing_authority", entity_id=authority_id,
                   before=before, after=after, reason=reason, ip=_client_address(request))


def create_authority(conn: db.Connection, actor: Any, body: dict, *, request: Request | None = None,
                     source: str = "ADMIN", authority_id: str | None = None, provisional: bool = False,
                     extra: dict | None = None) -> dict:
    name = " ".join(str(body.get("department_name") or "").split())
    post = " ".join(str(body.get("post") or "").split())
    if len(name) < 3:
        raise HTTPException(422, "department_name is required")
    if len(post) < 3:
        raise HTTPException(422, "post is required")
    product = str(body.get("product_scope") or "BOTH").upper()
    if product not in PRODUCTS:
        raise HTTPException(422, f"product_scope must be one of {list(PRODUCTS)}")
    aliases = _list_or_422(body.get("department_aliases"), "department_aliases")
    post_aliases = _list_or_422(body.get("post_aliases"), "post_aliases")
    code = body.get("department_code") or _department_code_for(name, aliases)
    if code:
        from api.departments import DEPARTMENT_NAMES
        if code not in DEPARTMENT_NAMES:
            raise HTTPException(422, f"unknown department code {code!r}")
    stamp = db.now()
    row = {
        "id": authority_id or db.new_id(), "product_scope": product, "department_code": code,
        "department_name": name, "department_aliases_json": json.dumps(aliases, ensure_ascii=False),
        "post": post, "post_aliases_json": json.dumps(post_aliases, ensure_ascii=False),
        "officer_name": " ".join(str(body.get("officer_name") or "").split()) or None,
        "scope": " ".join(str(body.get("scope") or "").split()) or None,
        "effective_from": _iso_or_422(body.get("effective_from"), "effective_from", required=True),
        "effective_to": _iso_or_422(body.get("effective_to"), "effective_to"),
        "letter_no": " ".join(str(body.get("letter_no") or "").split()) or None,
        "letter_date": _iso_or_422(body.get("letter_date"), "letter_date"),
        "letter_path": None, "provisional": 1 if provisional else 0, "source": source,
        "gpf_authority_id": (extra or {}).get("gpf_authority_id"), "gpf_signatory_id": (extra or {}).get("gpf_signatory_id"),
        "may_sign_for": 1 if body.get("may_sign_for") else 0,
        "stamp_text": " ".join(str(body.get("stamp_text") or "").split()) or None,
        "created_at": stamp, "updated_at": stamp, "closed_at": None, "closed_by": None,
    }
    if row["effective_to"] and row["effective_to"] < row["effective_from"]:
        raise HTTPException(422, "effective_to is before effective_from")
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO signing_authorities({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    _audit(conn, actor, "SIGNATORY_CREATE", row["id"], before=None,
           after={k: row[k] for k in ("department_name", "post", "officer_name", "effective_from", "effective_to", "source")},
           request=request)
    return get_authority(conn, row["id"])


EDITABLE = ("department_name", "department_aliases", "post", "post_aliases", "officer_name", "scope",
            "effective_from", "effective_to", "letter_no", "letter_date", "product_scope", "may_sign_for", "stamp_text",
            "department_code")


def update_authority(conn: db.Connection, actor: Any, authority_id: str, body: dict, *, reason: str = "",
                     request: Request | None = None) -> dict:
    before = get_authority(conn, authority_id)
    if before["closed_at"]:
        raise HTTPException(409, "a closed authority is history; add a new entry instead")
    changes: dict[str, Any] = {}
    for key in EDITABLE:
        if key not in body:
            continue
        value = body[key]
        if key in ("department_aliases", "post_aliases"):
            changes[key + "_json"] = json.dumps(_list_or_422(value, key), ensure_ascii=False)
        elif key in ("effective_from", "effective_to", "letter_date"):
            changes[key] = _iso_or_422(value, key, required=(key == "effective_from"))
        elif key == "product_scope":
            if str(value).upper() not in PRODUCTS:
                raise HTTPException(422, f"product_scope must be one of {list(PRODUCTS)}")
            changes[key] = str(value).upper()
        elif key == "may_sign_for":
            changes[key] = 1 if value else 0
        elif key == "department_code":
            from api.departments import DEPARTMENT_NAMES
            if value and value not in DEPARTMENT_NAMES:
                raise HTTPException(422, f"unknown department code {value!r}")
            changes[key] = value or None
        else:
            text = " ".join(str(value or "").split())
            if key in ("department_name", "post") and len(text) < 3:
                raise HTTPException(422, f"{key} is required")
            changes[key] = text or None
    if not changes:
        raise HTTPException(422, "nothing to change")
    changes["updated_at"] = db.now()
    sets = ", ".join(f"{k} = ?" for k in changes)
    conn.execute(f"UPDATE signing_authorities SET {sets} WHERE id = ?", (*changes.values(), authority_id))
    after = get_authority(conn, authority_id)
    _audit(conn, actor, "SIGNATORY_UPDATE", authority_id,
           before={k: before.get(k) for k in before if k in {c.replace("_json", "") for c in changes}},
           after={k: after.get(k) for k in after if k in {c.replace("_json", "") for c in changes}},
           reason=reason, request=request)
    return after


def close_authority(conn: db.Connection, actor: Any, authority_id: str, *, effective_to: Any, reason: str,
                    request: Request | None = None) -> dict:
    before = get_authority(conn, authority_id)
    if before["closed_at"]:
        raise HTTPException(409, "already closed")
    if len(" ".join(str(reason or "").split())) < 5:
        raise HTTPException(422, "closing an authority needs a reason (the letter that replaced it, the transfer, ...)")
    end = _iso_or_422(effective_to, "effective_to") or date.today().isoformat()
    if end < before["effective_from"]:
        raise HTTPException(422, "effective_to is before effective_from")
    stamp = db.now()
    conn.execute("UPDATE signing_authorities SET effective_to = ?, closed_at = ?, closed_by = ?, updated_at = ? WHERE id = ?",
                 (end, stamp, getattr(actor, "id", None), stamp, authority_id))
    _audit(conn, actor, "SIGNATORY_CLOSE", authority_id, before={"effective_to": before["effective_to"]},
           after={"effective_to": end}, reason=reason, request=request)
    return get_authority(conn, authority_id)


def _sniff(body: bytes, allowed: dict) -> tuple[str, str]:
    for magic, (media, ext) in allowed.items():
        if body.startswith(magic):
            return media, ext
    raise HTTPException(422, "the file is not a " + " / ".join(sorted({m for m, _ in allowed.values()})))


def add_specimen(conn: db.Connection, actor: Any, authority_id: str, filename: str, body: bytes, *,
                 note: str = "", request: Request | None = None) -> dict:
    get_authority(conn, authority_id)
    if len(body) > MAX_IMAGE:
        raise HTTPException(413, f"a specimen image may be at most {MAX_IMAGE // 1048576} MB")
    _, ext = _sniff(body, IMAGE_TYPES)
    have = conn.execute("SELECT COUNT(*) FROM signatory_specimens WHERE authority_id = ?", (authority_id,)).fetchone()[0]
    if have >= MAX_SPECIMENS:
        raise HTTPException(409, f"an authority carries at most {MAX_SPECIMENS} specimens")
    spec_id = db.new_id()
    digest = hashlib.sha256(body).hexdigest()
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = STORE_DIR / f"{authority_id}-{have + 1}-{digest[:8]}{ext}"
    path.write_bytes(body)
    conn.execute("INSERT INTO signatory_specimens(id, authority_id, stored_path, sha256, bytes, uploaded_by, uploaded_at, note) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (spec_id, authority_id, str(path), digest, len(body), getattr(actor, "id", None), db.now(),
                  " ".join(str(note or "").split())[:300] or None))
    conn.execute("UPDATE signing_authorities SET updated_at = ? WHERE id = ?", (db.now(), authority_id))
    _audit(conn, actor, "SPECIMEN_ADD", authority_id, before=None,
           after={"specimen": spec_id, "file": filename, "sha256": digest[:16]}, request=request)
    return get_authority(conn, authority_id)


def add_letter(conn: db.Connection, actor: Any, authority_id: str, filename: str, body: bytes, *,
               request: Request | None = None) -> dict:
    before = get_authority(conn, authority_id)
    if len(body) > 4 * MAX_IMAGE:
        raise HTTPException(413, "the letter scan may be at most 32 MB")
    _, ext = _sniff(body, LETTER_TYPES)
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = STORE_DIR / "letters" / f"{authority_id}-{hashlib.sha256(body).hexdigest()[:8]}{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    conn.execute("UPDATE signing_authorities SET letter_path = ?, updated_at = ? WHERE id = ?", (str(path), db.now(), authority_id))
    _audit(conn, actor, "LETTER_ADD", authority_id, before={"has_letter": before["has_letter"]},
           after={"file": filename}, request=request)
    return get_authority(conn, authority_id)


def finalize_gpf_register(conn: db.Connection, actor: Any, *, request: Request | None = None) -> dict:
    """The GP Fund register is the office's list now: every provisional row becomes final, here and
    in the module (its ``/api/doa/finalize``, so its rules stop saying "provisional")."""
    n = conn.execute("SELECT COUNT(*) FROM signing_authorities WHERE provisional = 1").fetchone()[0]
    conn.execute("UPDATE signing_authorities SET provisional = 0, updated_at = ? WHERE provisional = 1", (db.now(),))
    module: dict | None = None
    try:
        from api import gpf_bridge
        module = gpf_bridge._request("POST", "/api/doa/finalize", body=json.dumps({"officer": "dag"}).encode(),
                                     content_type="application/json", acting_name=getattr(actor, "display_name", None))
    except Exception as exc:                            # noqa: BLE001 -- the master rows are final either way
        module = {"error": str(exc)[:200]}
    _audit(conn, actor, "GPF_REGISTER_FINAL", "gpf-register", before={"provisional_rows": n}, after={"module": module}, request=request)
    return {"ok": True, "rows_made_final": n, "module": module}


# -- lookup ----------------------------------------------------------------------------------------

def register_from_rows(conn: db.Connection, product: str = "PENSION") -> tuple:
    """The master rows as ``rules.specimens.Specimen`` objects (ids, aliases, dates, image paths)."""
    out = []
    for a in list_authorities(conn, product=product):
        images = tuple(Path(s["stored_path"]) for s in conn.execute(
            "SELECT stored_path FROM signatory_specimens WHERE authority_id = ? ORDER BY uploaded_at, id", (a["id"],)))
        out.append(_specimens.Specimen(
            id=a["id"], department=a["department_name"], post=a["post"], officer=a.get("officer_name") or "",
            scope=a.get("scope") or "", effective_from=date.fromisoformat(a["effective_from"]),
            effective_to=date.fromisoformat(a["effective_to"]) if a.get("effective_to") else None,
            stamp_text=a.get("stamp_text") or "", images=images,
            authority={"letter_no": a.get("letter_no") or a["id"], "dated": a.get("letter_date") or a["effective_from"]},
            department_aliases=tuple([a["department_name"], *a["department_aliases"]]),
            post_aliases=tuple([a["post"], *a["post_aliases"]]),
        ))
    return tuple(out)


def lookup(conn: db.Connection, department: str | None, post: str | None, on_date: date | None,
           product: str = "PENSION") -> dict:
    """The authority a signature answers to, with its specimens -- or why there is none.

    ``{"authority": {...} | None, "specimens": [{"id", "name"}], "status": "on file" | reason,
    "message": "No specimen on file for <department>, <post>" where none}``. Closed entries and
    entries not in force on ``on_date`` are not matches.
    """
    spec, why = _specimens.lookup(department, post, on_date, register_from_rows(conn, product))
    if spec is None:
        return {"authority": None, "specimens": [], "status": why,
                "message": f"No specimen on file for {department or 'this department'}, {post or 'this post'}"}
    authority = get_authority(conn, spec.id)
    if not authority["specimens"]:
        return {"authority": authority, "specimens": [], "status": why,
                "message": f"No specimen on file for {authority['department_name']}, {authority['post']}"}
    return {"authority": authority, "specimens": authority["specimens"], "status": why, "message": None}


# -- the export the pipeline reads -------------------------------------------------------------

def export_register(conn: db.Connection | None = None, *, activate_after: bool = True) -> Path:
    """Write the pension view of the store in ``rules/specimens`` shape, images beside it, and
    point ``rules.specimens`` at it. Called after every change and at API start-up."""
    own = conn is None
    conn = conn or db.connect()
    try:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        entries = []
        for a in list_authorities(conn, product="PENSION"):
            names = []
            for s in conn.execute("SELECT stored_path FROM signatory_specimens WHERE authority_id = ? ORDER BY uploaded_at, id", (a["id"],)):
                src = Path(s["stored_path"])
                if not src.exists():
                    continue
                if src.parent != STORE_DIR:
                    dst = STORE_DIR / src.name
                    if not dst.exists():
                        shutil.copy2(src, dst)
                    src = dst
                names.append(src.name)
            entries.append({
                "id": a["id"], "department": a["department_name"], "department_aliases": a["department_aliases"],
                "post": a["post"], "post_aliases": a["post_aliases"], "officer": a.get("officer_name") or "",
                "scope": a.get("scope") or "", "effective_from": a["effective_from"], "effective_to": a.get("effective_to"),
                "stamp_text": a.get("stamp_text") or "", "images": names,
                "authority": {"letter_no": a.get("letter_no") or a["id"], "dated": a.get("letter_date") or a["effective_from"]},
                "provisional": a["provisional"], "closed": a["closed"],
            })
        out = STORE_DIR / EXPORT_NAME
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps({"_about": "Exported from the signing_authorities table by api.signatories; "
                                              "the database is the master copy. Do not edit.",
                                   "specimens": entries}, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(out)
        if activate_after:
            activate()
        return out
    finally:
        if own:
            conn.close()


def activate() -> None:
    """Point ``rules.specimens`` at the export (the pipeline runs in this process)."""
    _specimens.ACTIVE = STORE_DIR / EXPORT_NAME


# -- import of the two legacy registers ------------------------------------------------------------

def _gpf_register() -> dict:
    """GP Fund's register: the saved file where there is one, else the module's built-in provisional list."""
    saved = Path(os.environ.get("GPF_DATA_DIR") or ROOT / "GP" / "backend" / "data") / "doa.json"
    if saved.is_file():
        try:
            data = json.loads(saved.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "authorities" in data:
                return data
        except (OSError, ValueError):
            pass
    spec = importlib.util.spec_from_file_location("_gpf_doa_for_import", ROOT / "GP" / "backend" / "gpf" / "doa.py")
    if spec is None or spec.loader is None:
        return {"status": "provisional", "authorities": []}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DOA


class _System:
    id = None
    display_name = "System (import)"
    role = "SYSTEM"


def import_all(conn: db.Connection | None = None) -> dict[str, int]:
    """Bring the two legacy registers in. Idempotent: an entry already present (by id) is left alone."""
    own = conn is None
    conn = conn or db.connect()
    actor = _System()
    added = {"pension": 0, "gpf": 0}
    try:
        with db.transaction(conn):
            have = {r[0] for r in conn.execute("SELECT id FROM signing_authorities")}
            for s in _specimens.load(_specimens.REGISTER):
                if s.id in have:
                    continue
                create_authority(conn, actor, {
                    "department_name": s.department, "department_aliases": list(s.department_aliases[1:]),
                    "post": s.post, "post_aliases": list(s.post_aliases[1:]), "officer_name": s.officer, "scope": s.scope,
                    "effective_from": s.effective_from.isoformat(),
                    "effective_to": s.effective_to.isoformat() if s.effective_to else None,
                    "letter_no": s.authority.get("letter_no"), "letter_date": s.authority.get("dated"),
                    "product_scope": "PENSION", "stamp_text": s.stamp_text,
                }, source="PENSION_REGISTER", authority_id=s.id)
                STORE_DIR.mkdir(parents=True, exist_ok=True)
                for img in s.images:
                    if not img.exists():
                        continue
                    dst = STORE_DIR / img.name
                    if not dst.exists():
                        shutil.copy2(img, dst)
                    conn.execute("INSERT INTO signatory_specimens(id, authority_id, stored_path, sha256, bytes, uploaded_by, uploaded_at, note) "
                                 "VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
                                 (db.new_id(), s.id, str(dst), hashlib.sha256(dst.read_bytes()).hexdigest(), dst.stat().st_size,
                                  db.now(), f"from {s.cite}"))
                added["pension"] += 1
            gpf = _gpf_register()
            provisional = gpf.get("status") != "final"
            for a in gpf.get("authorities", []):
                for g in a.get("signatories", []):
                    aid = f"gpf-{a['id']}-{g['id']}"
                    if aid in have:
                        continue
                    create_authority(conn, actor, {
                        "department_name": a.get("dept") or a.get("authority"),
                        "department_aliases": list(a.get("aliases") or []) + [a.get("authority") or ""],
                        "post": g["post"], "officer_name": g.get("name") or None, "scope": g.get("powers") or None,
                        "effective_from": GPF_PROVISIONAL_FROM, "product_scope": "GPF", "may_sign_for": bool(g.get("mayFor")),
                    }, source="GPF_PROVISIONAL", authority_id=aid, provisional=provisional,
                        extra={"gpf_authority_id": a["id"], "gpf_signatory_id": g["id"]})
                    added["gpf"] += 1
        return added
    finally:
        if own:
            conn.close()


def start_up(conn: db.Connection | None = None) -> dict[str, int]:
    """At API start-up, after the migrations: import what is missing, export, activate."""
    own = conn is None
    conn = conn or db.connect()
    try:
        if "signing_authorities" not in db.dbcore.table_names(conn):
            return {"pension": 0, "gpf": 0}
        added = import_all(conn)
        export_register(conn)
        return added
    finally:
        if own:
            conn.close()


# -- routes ----------------------------------------------------------------------------------------

def _viewer(user: User = Depends(current_user)) -> User:
    if user.role not in viewer_roles():
        raise HTTPException(403, "specimen signatures are for the Accountant General's desk, not the filing department")
    return user


def _viewer_q(user: User = Depends(current_user_q)) -> User:
    if user.role not in viewer_roles():
        raise HTTPException(403, "specimen signatures are for the Accountant General's desk, not the filing department")
    return user


@router.get("")
def list_route(department: str | None = None, post: str | None = None, product: str | None = None,
               include_closed: bool = True, user: User = Depends(_viewer), conn: db.Connection = Depends(get_conn)) -> dict:
    if product and product.upper() not in PRODUCTS:
        raise HTTPException(422, f"product must be one of {list(PRODUCTS)}")
    return {"authorities": list_authorities(conn, department=department, post=post,
                                            product=product.upper() if product else None, include_closed=include_closed)}


@router.get("/lookup")
def lookup_route(department: str, post: str, on: str | None = None, product: str = "PENSION",
                 user: User = Depends(_viewer), conn: db.Connection = Depends(get_conn)) -> dict:
    when = date.fromisoformat(on) if on else None
    return lookup(conn, department, post, when, product.upper())


@router.post("", status_code=201)
def create_route(request: Request, body: dict = Body(...), user: User = Depends(require_roles("ADMIN")),
                 conn: db.Connection = Depends(get_conn)) -> dict:
    with db.transaction(conn):
        out = create_authority(conn, user, body, request=request)
    export_register(conn)
    return out


@router.post("/gpf-register/finalize")
def finalize_route(request: Request, user: User = Depends(require_roles("ADMIN")), conn: db.Connection = Depends(get_conn)) -> dict:
    with db.transaction(conn):
        out = finalize_gpf_register(conn, user, request=request)
    export_register(conn)
    return out


@router.post("/{authority_id}")
def update_route(authority_id: str, request: Request, body: dict = Body(...), user: User = Depends(require_roles("ADMIN")),
                 conn: db.Connection = Depends(get_conn)) -> dict:
    reason = str(body.pop("reason", "") or "")
    with db.transaction(conn):
        out = update_authority(conn, user, authority_id, body, reason=reason, request=request)
    export_register(conn)
    return out


@router.post("/{authority_id}/close")
def close_route(authority_id: str, request: Request, body: dict = Body(default={}), user: User = Depends(require_roles("ADMIN")),
                conn: db.Connection = Depends(get_conn)) -> dict:
    with db.transaction(conn):
        out = close_authority(conn, user, authority_id, effective_to=body.get("effective_to"), reason=str(body.get("reason") or ""),
                              request=request)
    export_register(conn)
    return out


async def _read_small(file: UploadFile, limit: int) -> bytes:
    body = await file.read(limit + 1)
    if len(body) > limit:
        raise HTTPException(413, f"the file exceeds {limit // 1048576} MB")
    if not body:
        raise HTTPException(422, "the file is empty")
    return body


@router.post("/{authority_id}/specimens", status_code=201)
async def specimen_route(authority_id: str, request: Request, file: UploadFile = File(...), note: str = Form(default=""),
                         user: User = Depends(require_roles("ADMIN")), conn: db.Connection = Depends(get_conn)) -> dict:
    body = await _read_small(file, MAX_IMAGE)
    with db.transaction(conn):
        out = add_specimen(conn, user, authority_id, file.filename or "specimen", body, note=note, request=request)
    export_register(conn)
    return out


@router.post("/{authority_id}/letter", status_code=201)
async def letter_route(authority_id: str, request: Request, file: UploadFile = File(...),
                       user: User = Depends(require_roles("ADMIN")), conn: db.Connection = Depends(get_conn)) -> dict:
    body = await _read_small(file, 4 * MAX_IMAGE)
    with db.transaction(conn):
        out = add_letter(conn, user, authority_id, file.filename or "letter", body, request=request)
    return out


_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


@router.get("/{authority_id}/images/{name}", include_in_schema=False)
def specimen_image_route(authority_id: str, name: str, request: Request, user: User = Depends(_viewer_q),
                         conn: db.Connection = Depends(get_conn)):
    """One specimen image, to the AG's side only, never cached, every view on the audit trail."""
    if not _NAME.match(name):
        raise HTTPException(404, "no such specimen image")
    row = conn.execute("SELECT s.* FROM signatory_specimens s WHERE s.authority_id = ?", (authority_id,)).fetchall()
    hit = next((s for s in row if Path(s["stored_path"]).name == name), None)
    if hit is None or not Path(hit["stored_path"]).is_file():
        raise HTTPException(404, "no such specimen image")
    from api.v2 import _client_address
    workflow.audit(conn, actor=user, action="SPECIMEN_VIEWED", entity_type="signing_authority", entity_id=authority_id,
                   before=None, after={"specimen": hit["id"], "name": name}, ip=_client_address(request))
    media = "image/png" if name.lower().endswith(".png") else "image/jpeg"
    return FileResponse(hit["stored_path"], media_type=media,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{authority_id}/letter", include_in_schema=False)
def letter_image_route(authority_id: str, request: Request, user: User = Depends(_viewer_q),
                       conn: db.Connection = Depends(get_conn)):
    r = conn.execute("SELECT letter_path FROM signing_authorities WHERE id = ?", (authority_id,)).fetchone()
    if r is None or not r["letter_path"] or not Path(r["letter_path"]).is_file():
        raise HTTPException(404, "no letter on file")
    path = Path(r["letter_path"])
    media = {"pdf": "application/pdf", "png": "image/png"}.get(path.suffix.lstrip(".").lower(), "image/jpeg")
    return FileResponse(str(path), media_type=media, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                                              "Content-Security-Policy": "sandbox"})


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "import":
        db.migrate()
        added = import_all()
        export_register()
        print(f"imported {added['pension']} pension and {added['gpf']} GP Fund entries; export at {STORE_DIR / EXPORT_NAME}")
        return 0
    if cmd == "export":
        print(export_register(activate_after=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
