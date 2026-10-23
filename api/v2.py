"""The multi-department case system's API: ``/api/v2``.

Five portals (Punjab Police, School Education, AG Review, AG Upload, Admin) share this one
backend and one database (``api.db``). Every route names the roles it admits and checks the
caller's department where the case has one; the UI hides what a role cannot do, this refuses
it. The old portal's ``/api/*`` routes are untouched and unauthenticated by design until it
is retired.

    401  no or invalid token           403  not this role's or department's to do
    409  not from this case status     422  a missing remark or a bad value
"""
from __future__ import annotations

import hashlib
import json
import csv
import io
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Request, UploadFile, Response
from fastapi.responses import JSONResponse

from api import case_runs, db, gpf_bridge, inventory, settings, workflow
from api.db import SHARED_LOGINS
from api.artefacts import bundle as run_bundle
from api.artefacts import event_stream, get_run, page_image, report, signature_image, status
from api.auth import (MEDIA_SCOPE, MEDIA_TOKEN_TTL, AuthError, User, authenticate, current_user, current_user_q, get_conn,
                      issue_scoped_token,
                      hash_password, issue_token, password_problem, require_roles)
from api.departments import (AG_PORTAL_PORT, AG_PORTAL_SLUG, DEPARTMENTS, DEPARTMENT_NAMES,
                             PENSION_SECTION_ORDER, LEGACY_DEPARTMENT, ROLES, CREATABLE_ROLES, TIER_ROLES,
                             SINGLE_PORTAL, portal_for)
from api.themes import theme_for
from rules.case_type import (OFFICE_CASE_TYPES, canonical_office_type, case_type_label, load_case_types,
                             variants_for_case_type)

router = APIRouter(prefix="/api/v2")

MAX_FILES = 40                                  # files in one upload
MAX_UPLOAD_TOTAL = 512 * 1024 * 1024            # bytes in one upload, all files together
MAX_UPLOAD = 256 * 1024 * 1024
MIN_RESET_REASON = 10                           # characters an administrator's password reset must explain itself in (N25)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ ()\-]+")


def _raise(exc: workflow.WorkflowError | AuthError) -> None:
    raise HTTPException(exc.status, exc.detail)


# -- auth --------------------------------------------------------------------------------------

MAX_NAME = 120


def _clean_name(value: str | None) -> str | None:
    """A claimant's name as typed, minus control characters, at most MAX_NAME characters."""
    text = "".join(ch for ch in (value or "") if ch.isprintable()).strip()
    if len(text) > MAX_NAME:
        raise HTTPException(422, f"the claimant's name may be at most {MAX_NAME} characters")
    return text or None


def _client_address(request: Request | None) -> str | None:
    """The caller's address: what the portal server put in X-Forwarded-For (it overwrites any the
    client sent), else the socket's peer. Used for the login lockout and the audit log."""
    if request is None:
        return None
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded and request.client and request.client.host in ("127.0.0.1", "::1"):
        return forwarded
    return request.client.host if request.client else None


@router.post("/auth/login")
def login(request: Request, body: dict = Body(...), x_portal: str | None = Header(default=None),
          conn: db.Connection = Depends(get_conn)) -> dict:
    """Sign in at a portal. The portal is the one the request came through (``X-Portal``, set by
    the portal server), else the one the body names (the development server)."""
    portal = (x_portal or body.get("portal") or "").strip() or None
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0] or None
    address = _client_address(request)
    typed = str(body.get("username", "")).strip()[:64]
    try:
        user = authenticate(typed, str(body.get("password", "")), portal, conn, host=host, address=address)
    except AuthError as exc:
        # Every refused sign-in is on the audit trail with the name typed and the address, so a
        # guessing run shows up there (docs/DEPLOYMENT.md F6). The password never is.
        action = {429: "LOGIN_LOCKED", 401: "LOGIN_FAILED"}.get(exc.status, "LOGIN_REFUSED")
        workflow.audit(conn, actor=None, action=action, entity_type="user", entity_id=_audit_login_name(conn, typed),
                       before=None, after={"portal": portal, "status": exc.status}, reason=exc.detail, ip=address)
        _raise(exc)
    after = {"portal": portal, "must_change_password": user.must_change_password}
    if _follows_admin_reset(conn, user.id):
        # The administrator's reset is the one way to act as another officer (audit 7 Oct 2026,
        # N25): the first sign-in after one is marked, so the trail shows it.
        after["after_admin_reset"] = True
    workflow.audit(conn, actor=user, action="LOGIN", entity_type="user", entity_id=user.id,
                   before=None, after=after, ip=address)
    return {"token": issue_token(user), "user": user.to_dict(),
            "capabilities": capabilities(user), "password_min_length": settings.min_password_length()}


def _audit_login_name(conn: db.Connection, typed: str) -> str:
    """What a refused sign-in records as the account: the name typed when it is an account, else a
    hash of it. A password typed into the username box must not become a plaintext audit row
    (audit 7 Oct 2026, N27)."""
    if not typed:
        return "(blank)"
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (typed.lower(),)).fetchone():
        return typed.lower()
    return "(unknown) sha256:" + hashlib.sha256(typed.encode("utf-8")).hexdigest()[:16]


def _follows_admin_reset(conn: db.Connection, user_id: str) -> bool:
    """True when the administrator reset this account's password after its last sign-in."""
    last_login = conn.execute("SELECT MAX(at) FROM audit_log WHERE action = 'LOGIN' AND entity_id = ?", (user_id,)).fetchone()[0]
    row = conn.execute("SELECT 1 FROM audit_log WHERE action = 'USER_RESET_PASSWORD' AND entity_id = ? AND at > ? LIMIT 1",
                       (user_id, last_login or "")).fetchone()
    return row is not None


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    # The password rule is the server's; the screens read it here instead of carrying their own
    # number (frontend review F14, 9 Oct 2026).
    return {"user": user.to_dict(), "capabilities": capabilities(user), "password_min_length": settings.min_password_length()}


@router.get("/auth/media-token")
def media_token(request: Request, user: User = Depends(current_user)) -> dict:
    """A 15-minute GET-only token for the URLs a browser cannot send a header with: page images,
    signature crops, the event stream and document downloads (frontend review F10). The session
    token stays out of image URLs and the browser's disk cache; the client refreshes this one."""
    return {"token": issue_scoped_token(user, MEDIA_SCOPE, MEDIA_TOKEN_TTL, parent_jti=_claims_of_request(request).get("jti")),
            "expires_in": int(MEDIA_TOKEN_TTL.total_seconds())}


@router.post("/auth/change-password")
def change_password(body: dict = Body(...), request: Request = None, user: User = Depends(current_user),
                    conn: db.Connection = Depends(get_conn)) -> dict:
    from api.auth import _attempt_key, _locked, _note_failure, verify_password
    key = _attempt_key(f"change:{user.username}", _client_address(request))
    if _locked(conn, key):
        raise HTTPException(429, "too many wrong attempts; try again in a minute")
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    if not verify_password(str(body.get("current", "")), row["password_hash"]):
        _note_failure(conn, key); conn.commit()
        raise HTTPException(403, "the current password is wrong")
    new = str(body.get("new", ""))
    problem = password_problem(new, user.username)
    if problem:
        raise HTTPException(422, problem)
    if new == str(body.get("current", "")):
        raise HTTPException(422, "the new password must differ from the current one")
    with db.transaction(conn):
        conn.execute("UPDATE users SET password_hash = ?, token_version = token_version + 1, "
                     "must_change_password = 0, updated_at = ? WHERE id = ?", (hash_password(new), db.now(), user.id))
        workflow.audit(conn, actor=user, action="PASSWORD_CHANGE", entity_type="user", entity_id=user.id,
                       before=None, after=None, ip=_client_address(request))
    fresh = conn.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
    from api.auth import user_from_row
    changed = user_from_row(fresh)
    return {"token": issue_token(changed), "user": changed.to_dict(), "capabilities": capabilities(changed)}


#: The cookie the GP Fund frame signs in with. Path /gpf only, so it travels with the frame's
#: requests and with nothing else; HttpOnly, so the module's page cannot read it; SameSite=Strict,
#: so another site cannot make a browser send it.
GPF_COOKIE = "pension_gpf"


def _claims_of_request(request: Request | None) -> dict:
    """The verified claims of the bearer token on this request, or {}."""
    from api.auth import _bearer, claims_of
    return claims_of(_bearer(request.headers.get("authorization"))) if request is not None else {}


@router.post("/auth/gpf-session")
def gpf_session(request: Request, user: User = Depends(require_roles(*workflow.AG_SIDE))):
    """Sign the GP Fund frame in. The AG's case screen shows the module's own page in a frame,
    and a frame cannot carry the Authorization header; this sets a cookie the portal server
    checks on every /gpf/ request (docs/DEPLOYMENT.md F10). AG and administrator only: the
    module's findings are the Accountant General's, and a department sees no AI output."""
    from fastapi.responses import JSONResponse
    from api.auth import GPF_SCOPE, GPF_TOKEN_TTL, issue_scoped_token
    response = JSONResponse({"ok": True, "expires_in": int(GPF_TOKEN_TTL.total_seconds())})
    # Secure whenever the request came over HTTPS, and wherever the deployment is behind TLS,
    # so a browser never sends the cookie over plain HTTP whatever a proxy header says
    # (audit 6 Oct 2026, L2). settings.behind_tls() and not production() directly: production
    # is MEANT to be nginx in front, but a box where it is not yet issues a Secure cookie the
    # browser silently discards, and the frame then refuses an officer who did everything
    # right. The flag states what is true rather than what is intended.
    https = (request.headers.get("x-forwarded-proto") or request.url.scheme) == "https"
    parent = _claims_of_request(request).get("jti")      # the session this frame belongs to: its sign-out ends the frame too
    response.set_cookie(GPF_COOKIE, issue_scoped_token(user, GPF_SCOPE, GPF_TOKEN_TTL, parent_jti=parent),
                        max_age=int(GPF_TOKEN_TTL.total_seconds()), path="/gpf", httponly=True,
                        samesite="strict", secure=https or settings.behind_tls())
    return response


@router.post("/auth/logout")
def logout(request: Request, authorization: str | None = Header(default=None),
           conn: db.Connection = Depends(get_conn)) -> Any:
    """Sign-out's server half: end the session token, and clear the GP Fund frame cookie.

    The token lives in the tab, but dropping it there did not end it: a copy taken from the tab
    (or the frame cookie's token) stayed valid until its 12-hour expiry (audit 6 Oct 2026, later
    report 6b). Signing out records the token's jti in ``revoked_tokens`` until the token's own
    expiry (migration 0015), which every request checks, so this token -- and the frame and media
    tokens derived from it -- is refused from here on. The account's other sessions go on: the
    senior officers share one login (ag.reviewer, decision S10), and until 9 Oct 2026 the sign-out
    bumped ``token_version`` and threw every one of them out mid-case.

    The frame cookie is HttpOnly, path /gpf and lives two hours: on a shared office PC the next
    person could open /gpf/ as the officer who had just signed out or been timed out. Needs no
    session, because the idle timeout and a refused token call it after the session is gone; an
    absent, expired or already-ended token is not an error here.
    """
    from datetime import datetime
    from fastapi.responses import JSONResponse
    from api.auth import _bearer, claims_of, user_for_token
    token = _bearer(authorization)
    if token:
        try:
            user = user_for_token(token, conn)
        except AuthError:
            user = None                      # nothing left to end
        if user is not None:
            claims = claims_of(token)
            jti = claims.get("jti")
            # The same clock the sweep below compares against. db.now() is naive LOCAL time, so
            # a UTC stamp here read five hours early in Asia/Karachi: the revocation row was swept
            # away while the token it revoked was still valid, and a signed-out session worked
            # again (audit 13 Oct 2026). Both sides are now local, as every other *_at column is.
            expires = datetime.fromtimestamp(int(claims.get("exp", 0))).isoformat(timespec="seconds")
            with db.transaction(conn):
                if jti:
                    conn.execute("INSERT OR IGNORE INTO revoked_tokens(jti, user_id, expires_at, revoked_at) VALUES (?, ?, ?, ?)",
                                 (jti, user.id, expires, db.now()))
                    conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (db.now(),))
                else:
                    # A token from before 0015 carries no jti: only the account-wide switch can end it.
                    conn.execute("UPDATE users SET token_version = token_version + 1, updated_at = ? WHERE id = ?", (db.now(), user.id))
                workflow.audit(conn, actor=user, action="SIGN_OUT", entity_type="user", entity_id=user.id,
                               before=None, after=None, ip=_client_address(request))
    response = JSONResponse({"ok": True})
    response.delete_cookie(GPF_COOKIE, path="/gpf", httponly=True, samesite="strict")
    return response


@router.get("/auth/gpf-check")
def gpf_check(x_gpf_session: str | None = Header(default=None),
              conn: db.Connection = Depends(get_conn)) -> dict:
    """The portal server's question for each /gpf/ request: is this frame cookie a live sign-in
    of an AG or administrator account? 401/403 otherwise."""
    user = _gpf_frame_user(x_gpf_session, conn)
    # The officer band the module records this account's actions under; the portal server passes
    # it on as X-GPF-Officer, and the module takes it over whatever the page claims.
    # ... and the officer's own name, which the module records every action under (G6).
    return {"ok": True, "user": user.username, "name": user.display_name,
            "officer": gpf_bridge.OFFICER_FOR_ROLE.get(user.role, "ao")}


def _gpf_frame_user(token: str | None, conn: db.Connection) -> User:
    from api.auth import GPF_SCOPE, user_for_token
    if not token:
        raise HTTPException(401, "sign in at the portal first")
    try:
        user = user_for_token(token, conn, scope=GPF_SCOPE)
    except AuthError as exc:
        _raise(exc)
    if user.role not in workflow.AG_SIDE or user.must_change_password:
        raise HTTPException(403, "this account may not open the GP Fund module")
    return user


@router.get("/auth/gpf-act-check")
def gpf_act_check(x_gpf_session: str | None = Header(default=None),
                  x_gpf_path: str = Header(default=""),
                  x_gpf_method: str = Header(default="POST"),
                  conn: db.Connection = Depends(get_conn)) -> dict:
    """The portal server's question before passing a request to the module from the frame: may
    this signed-in officer read, or act on, what that path names?

    Until 12 Oct 2026 the frame cookie opened the whole module: any AG-side account could list
    every GP Fund claim across the wings and read its scans, act on a case another wing or
    another tier held, file cases and start reading jobs through the frame, and add to or
    finalise the signing register the module verifies sanctions against (audit of 12 Oct 2026).
    Now:
      - the register of cases and the intake routes are the portal's (403 through the frame);
      - the signing register is read here and managed by the administrator in the portal;
      - a case route is judged on the portal case it belongs to: not filed by the portal -> 403;
        the wing and tier visibility of the case system (may_see); and for a change, under
        review (_gpf_may_act), held by this officer's tier, and the one-tier rule;
      - any other read passes; any other change does not.
    """
    user = _gpf_frame_user(x_gpf_session, conn)
    path = x_gpf_path or ""
    reading = (x_gpf_method or "POST").upper() in ("GET", "HEAD", "OPTIONS")
    if path == "/api/cases" or path.startswith("/api/cases/from-scans"):
        raise HTTPException(403, "GP Fund cases are filed and listed in the portal, not through the module's frame")
    if path.startswith("/api/doa") and not reading:
        raise HTTPException(403, "the signing register is managed by the administrator in the portal")
    match = _GPF_CASE_ROUTE.match(path)
    if match:
        row = conn.execute("SELECT * FROM cases WHERE gpf_case_id = ?", (match.group(1),)).fetchone()
        if row is None:
            raise HTTPException(403, "this examination was not filed through the portal; it is not yours to open here")
        if not workflow.may_see_user(user, row):
            if user.role in TIER_ROLES and workflow.wing_of_case(row) == user.pension_wing:
                raise HTTPException(403, "this case has not been sent to your desk")
            raise HTTPException(403, "this case belongs to another pension wing")
        if not reading:
            _gpf_may_act(row)
            try:
                workflow.check_holder(user, row, "DISPOSE")
                workflow.check_one_tier_per_case(conn, user, row)
            except workflow.WorkflowError as exc:
                _raise(exc)
        return {"ok": True}
    if not reading:
        raise HTTPException(403, "not an action the module's frame may take")
    return {"ok": True}


def capabilities(user: User) -> dict:
    """What the screens may offer this user. The server re-checks every one of them."""
    # The administrator manages users and reads; it takes no case action (business decision G6,
    # 7 Oct 2026). The override is the Deputy AG's and the AG desk's. The tiers (C3, 9 Oct 2026): the
    # Senior Auditor verifies and talks to the department; the Accounts Officer decides; the AG's
    # desk (AG_REVIEWER, shared by the office's senior officers) acts at every tier in every wing.
    dept_side = user.role == "DEPT_OFFICER"
    ag_side = user.role in workflow.AG_SIDE
    reads_ag = user.role in workflow.AG_READERS
    tier = workflow.tier_of(user.role)
    return {
        "create_case": dept_side, "add_documents": dept_side,
        "run_check": user.role in ("AG_SENIOR_AUDITOR",) + workflow.ANY_TIER,
        "forward": dept_side, "pick_department": False,
        "intake_choices": ag_side,
        # The declared case type (29 Sep 2026): the AG may correct it, with a remark.
        "correct_case_type": ag_side,
        "review": reads_ag and user.role != "ADMIN", "dispose": ag_side, "override": user.role in workflow.ANY_TIER,
        "decide": user.role in ("AG_AO",) + workflow.ANY_TIER, "return_to_department": user.role in ("AG_SENIOR_AUDITOR",) + workflow.ANY_TIER,
        "tier": tier, "tier_label": workflow.TIER_LABELS.get(tier or "", None), "pension_wing": user.pension_wing,
        "manage_users": user.role == "ADMIN", "audit_log": user.role == "ADMIN",
        "all_departments": user.role in ("AG_DAG", "ADMIN", "AG_REVIEWER"),
    }


# -- departments -------------------------------------------------------------------------------

@router.get("/departments")
def departments(user: User = Depends(current_user), conn: db.Connection = Depends(get_conn)) -> list[dict]:
    """The departments a case can be filed for: the active ones, without the legacy bucket. A
    wing officer is given their own wing's departments only."""
    rows = inventory.visible_departments(conn, user, "code, name, digital, slug, port, pension_section, active")
    return [{k: v for k, v in dict(r).items() if k != "active"} for r in rows if r["active"] and r["code"] != LEGACY_DEPARTMENT[0]]


@router.get("/portals")
def portals() -> dict:
    """Every portal and its theme: what the portal server injects per port, and what the
    development server reads. Public -- it holds nothing but names, ports and colours."""
    return {
        "single_portal": SINGLE_PORTAL,
        "ag": {"kind": "ag", "slug": AG_PORTAL_SLUG, "code": None, "name": "Office of the Accountant General Punjab",
               "port": AG_PORTAL_PORT, "theme": theme_for("ag", title="SERVE PUNJAB")},
        "departments": [
            {"kind": "department", "slug": d.slug, "code": d.code, "name": d.name, "port": d.port,
             "is_police": d.is_police, "theme": theme_for(d.theme, title=f"{d.name} — Pension Portal")}
            for d in DEPARTMENTS
        ],
    }


PRODUCTS = ("PENSION", "GPF")


def _product_or_422(product: str | None) -> str | None:
    if product and product not in PRODUCTS:
        raise HTTPException(422, f"unknown product {product!r}; one of {', '.join(PRODUCTS)}")
    return product or None


@router.get("/departments/counts")
def department_counts(product: str | None = None, user: User = Depends(require_roles(*workflow.AG_READERS)),
                      conn: db.Connection = Depends(get_conn)) -> list[dict]:
    """Every department with its case counts by status -- the AG Review sidebar.

    Counted from the same rows the register lists (api.inventory), so the sidebar and the list
    cannot disagree. Cases the AG Upload portal created are counted under their own department.
    """
    from api import inventory
    case_runs.sync_run_states(conn)
    rows = _inventory_rows(conn, user, product=product)
    depts = inventory.visible_departments(conn, user)       # a wing officer's own departments only
    return [{k: v for k, v in d.items() if k != "active"} for d in inventory.counts_of(rows, depts)["by_department"]]


# -- statistics for the dashboards -------------------------------------------------------------

AGE_BUCKETS = (("0-3", 3), ("4-7", 7), ("8-14", 14), ("15+", None))


#: Who is shown where the office's cases are standing, desk by desk (23 Oct 2026). The two
#: roles that supervise the tiers rather than sit at one -- the Deputy Accountant General and
#: the AG's own desk -- and the administrator, who already reads every register.
#:
#: Not a tier officer. A Senior Auditor, an Assistant Accounts Officer and an Accounts Officer
#: each hold one desk; a chart of how long the OTHER desks are taking is a view of colleagues'
#: workload, not of their own work, and they have "Pending decisions by age" for that. Not a
#: department either, which is told the case is with the Office of the Accountant General and
#: never which desk holds it (holder_tier is nulled for a DDO for the same reason).
#:
#: The same three roles as capabilities.all_departments: the ones that see across the office.
OVERSIGHT_ROLES = ("AG_DAG", "AG_REVIEWER", "ADMIN")

#: The desks a case stands on inside the office, in the order it passes them. "Received" is the
#: case submitted and not yet taken up -- no tier holds it, which is a desk in its own right and
#: the one where a case is most easily forgotten.
_DESKS = (("RECEIVED", "Received"), ("SENIOR_AUDITOR", "Senior Auditor"),
          ("ASSISTANT_AO", "Assistant Accounts Officer"), ("AO", "Accounts Officer"))


def _by_desk(conn: db.Connection, where: str, args: list) -> list[dict]:
    """Where the office's pending cases are standing, desk by desk, and for how long.

    The same clock _ageing uses -- the last event that CHANGED the status, falling back to when
    the case was filed -- so "14 days" means fourteen days on that desk, not fourteen days in
    the building. Each desk carries its oldest case by number, because "three cases stuck at the
    AAO" is a fact an officer can do nothing with until they know which three.

    Not for a department. api/v2.py nulls holder_tier for a DDO on purpose -- it sees "with the
    Office of the Accountant General", not which desk -- and this would say it in a chart.
    """
    from datetime import datetime
    marks = ",".join("?" * len(workflow.AG_HOLDS))
    rows = conn.execute(
        f"SELECT c.case_no, c.holder_tier, COALESCE((SELECT MAX(e.at) FROM case_events e "
        f"WHERE e.case_id = c.id AND e.to_status = c.status "
        f"AND (e.from_status IS NULL OR e.from_status != e.to_status)), c.created_at) AS since "
        f"FROM cases c WHERE {where} AND c.status IN ({marks})", args + sorted(workflow.AG_HOLDS)).fetchall()
    now = datetime.now()
    tally: dict[str, dict] = {k: {"desk": k, "label": label, "total": 0, "waiting_over_a_week": 0,
                                  "oldest_days": 0, "oldest_case": None} for k, label in _DESKS}
    for r in rows:
        desk = r["holder_tier"] or "RECEIVED"
        if desk not in tally:
            continue
        try:
            days = max(0.0, (now - datetime.fromisoformat(r["since"])).total_seconds() / 86400)
        except ValueError:
            continue
        cell = tally[desk]
        cell["total"] += 1
        if days > 7:
            cell["waiting_over_a_week"] += 1
        if days >= cell["oldest_days"]:
            cell["oldest_days"], cell["oldest_case"] = round(days, 1), r["case_no"]
    return [tally[k] for k, _ in _DESKS]


def _ageing(conn: db.Connection, where: str, args: list, statuses) -> dict:
    """Pending cases by days at their present stage: bucket counts, the oldest, and its case number."""
    from datetime import datetime
    marks = ",".join("?" * len(statuses))
    buckets = {k: 0 for k, _ in AGE_BUCKETS}
    oldest_days, oldest_case = 0.0, None
    now = datetime.now()
    for r in conn.execute(
            f"SELECT c.case_no, COALESCE((SELECT MAX(e.at) FROM case_events e WHERE e.case_id = c.id "
            f"AND e.to_status = c.status AND (e.from_status IS NULL OR e.from_status != e.to_status)), c.created_at) AS since "
            f"FROM cases c WHERE {where} AND c.status IN ({marks})", args + sorted(statuses)):
        try:
            days = max(0.0, (now - datetime.fromisoformat(r["since"])).total_seconds() / 86400)
        except ValueError:
            continue
        for key, limit in AGE_BUCKETS:
            if limit is None or days <= limit:
                buckets[key] += 1
                break
        if days > oldest_days:
            oldest_days, oldest_case = days, r["case_no"]
    return {"buckets": buckets, "total": sum(buckets.values()), "oldest_days": round(oldest_days, 1), "oldest_case": oldest_case}


_REPORT_CACHE: dict[str, tuple[int, dict | None]] = {}


def _deficiencies(conn: db.Connection, where: str, args: list, top: int = 6) -> dict:
    """The checklist items most often missing or defective on the latest verification of each case
    in scope -- what the office should attach before filing. Reports never change once a run is
    done, so they are read once per run id."""
    from api.artefacts import report_dict
    from api.runs import ARTIFACTS
    counts: dict[str, dict] = {}
    verified = 0
    for r in conn.execute(
            f"SELECT cr.run_id FROM case_runs cr JOIN cases c ON c.id = cr.case_id WHERE {where} AND cr.state = 'done' "
            f"AND cr.id IN (SELECT id FROM case_runs x WHERE x.case_id = cr.case_id ORDER BY started_at DESC LIMIT 1)", args):
        run_id = r["run_id"]
        path = ARTIFACTS / f"run-{run_id}" / "case_report.json"
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            stamp = 0
        cached = _REPORT_CACHE.get(run_id)
        if cached is None or cached[0] != stamp:      # a recompute rewrites the file: read it again
            cached = _REPORT_CACHE[run_id] = (stamp, report_dict(ARTIFACTS / f"run-{run_id}"))
        rep = cached[1]
        if not rep:
            continue
        verified += 1
        for item in (rep.get("checklist") or {}).get("items") or []:
            status = item.get("status")
            if status not in ("MISSING", "DEFECTIVE"):
                continue
            entry = counts.setdefault(item.get("id") or "?", {"id": item.get("id"), "requirement": item.get("requirement") or item.get("id"),
                                                               "missing": 0, "defective": 0})
            entry["missing" if status == "MISSING" else "defective"] += 1
    items = sorted(counts.values(), key=lambda e: (-(e["missing"] + e["defective"]), e["id"] or ""))[:top]
    return {"verified_cases": verified, "items": items}


# Days from filing to the Accountant General's decision that count as on time (dashboard gauge).
DECISION_TARGET_DAYS = 7


#: Columns of the monthly register, in the order the office reads them.
_MONTHLY_COLUMNS = (
    ("case_no", "Case"), ("department_name", "Department"), ("pension_section", "Pension section"),
    ("claimant_name", "Claimant"), ("case_type_label", "Case type"), ("status_label", "Status"),
    ("where", "Where it is"), ("filed", "Filed"), ("decided", "Decided"),
    ("days_to_decision", "Days to decision"), ("submissions", "Submissions"), ("verifications", "Verifications"),
)


@router.get("/reports/monthly.csv")
def monthly_register(month: str, product: str | None = None, department: str | None = None,
                     pension_section: str | None = None, user: User = Depends(current_user),
                     conn: db.Connection = Depends(get_conn)):
    """The month's cases as a spreadsheet, for whoever is signed in (23 Oct 2026).

    A month is the month a case was FILED in, which is the month its case number belongs to and
    the only reading of "this month's cases" that does not change as the office works. A case
    filed in March and decided in April appears in March, and its decision date says April.

    Scoped exactly as the register is -- api.inventory.scope -- so a DDO downloads their own
    department and an officer their wing. No new sight of anything: the same redaction the
    register applies is applied here, which is what keeps the AI's reading out of a
    department's copy.
    """
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(422, "month: YYYY-MM")
    rows = _inventory_rows(conn, user, product=product, department=department, pension_section=pension_section)
    wanted = [r for r in rows if str(r.get("created_at") or "").startswith(month)]

    def decided_at(case: dict) -> str:
        for e in reversed(case.get("events") or []):
            if e.get("action") in ("APPROVE", "REJECT"):
                return str(e.get("at") or "")[:19].replace("T", " ")
        return ""

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([title for _, title in _MONTHLY_COLUMNS])
    for r in sorted(wanted, key=lambda x: str(x.get("case_no") or "")):
        filed = str(r.get("created_at") or "")[:19].replace("T", " ")
        done = decided_at(r)
        days = ""
        if filed and done:
            try:
                days = str(round((datetime.fromisoformat(done) - datetime.fromisoformat(filed)).total_seconds() / 86400, 1))
            except ValueError:
                days = ""
        values = {
            "case_no": r.get("case_no") or "", "department_name": r.get("department_name") or "",
            "pension_section": r.get("pension_section") or "", "claimant_name": r.get("claimant_name") or "",
            "case_type_label": r.get("case_type") or "", "status_label": r.get("status") or "",
            # holder_label is already None for a department (it must not learn which desk).
            "where": r.get("holder_label") or "", "filed": filed, "decided": done,
            "days_to_decision": days, "submissions": r.get("submission_no") or "",
            "verifications": len(r.get("runs") or []),
        }
        writer.writerow([values[key] for key, _ in _MONTHLY_COLUMNS])
    name = f"cases-{month}.csv"
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"',
                             "Cache-Control": "no-store"})


@router.get("/stats")
def stats(department: str | None = None, product: str | None = None, pension_section: str | None = None,
          user: User = Depends(current_user),
          conn: db.Connection = Depends(get_conn)) -> dict:
    """The numbers behind the dashboards, computed over the cases this user may see.

    Everything is counted server-side from the same tables the register reads, so the
    charts and the lists always agree. ``department`` narrows an AG reviewer's or admin's
    view to one department.
    """
    from datetime import date, datetime, timedelta
    from api import inventory
    case_runs.sync_run_states(conn)
    product = _product_or_422(product)
    if pension_section:
        _section_codes_or_422(pension_section)
    agd = user.role in workflow.AG_READERS
    # The same scope as the register and the sidebar (api.inventory).
    where, args = inventory.scope(conn, user, product=product, department=department if agd else None,
                                  section=pension_section if agd else None)

    by_status = {s: 0 for s in workflow.STATUSES}
    for r in conn.execute(f"SELECT c.status, COUNT(*) n FROM cases c WHERE {where} GROUP BY c.status", args):
        by_status[r["status"]] = r["n"]

    # Twelve weeks of filings and decisions, oldest first, week starting Monday.
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    weeks = [monday - timedelta(weeks=i) for i in range(11, -1, -1)]
    filed = {w.isoformat(): 0 for w in weeks}
    decided = {w.isoformat(): 0 for w in weeks}
    since = weeks[0].isoformat()
    for r in conn.execute(f"SELECT c.created_at FROM cases c WHERE {where} AND c.created_at >= ?", args + [since]):
        d = date.fromisoformat(r["created_at"][:10]); k = (d - timedelta(days=d.weekday())).isoformat()
        if k in filed: filed[k] += 1
    # One decision per case: the latest decision event of each case that stands decided now. A
    # rejection later overridden to approval is one decision, not two.
    decided_sql = ("(e.action IN ('APPROVE', 'REJECT') OR (e.action = 'OVERRIDE' AND e.to_status IN ('APPROVED', 'REJECTED'))) "
                   "AND c.status IN ('APPROVED', 'REJECTED') "
                   "AND e.at = (SELECT MAX(x.at) FROM case_events x WHERE x.case_id = c.id AND "
                   "(x.action IN ('APPROVE', 'REJECT') OR (x.action = 'OVERRIDE' AND x.to_status IN ('APPROVED', 'REJECTED'))))")
    for r in conn.execute(
            f"SELECT e.at FROM case_events e JOIN cases c ON c.id = e.case_id WHERE {where} "
            f"AND {decided_sql} AND e.at >= ?", args + [since]):
        d = date.fromisoformat(r["at"][:10]); k = (d - timedelta(days=d.weekday())).isoformat()
        if k in decided: decided[k] += 1

    by_department = [dict(r) for r in conn.execute(
        f"SELECT d.code, d.name, COUNT(c.id) AS total, "
        f"SUM(CASE WHEN c.status IN ('FORWARDED','UNDER_REVIEW') THEN 1 ELSE 0 END) AS awaiting, "
        f"SUM(CASE WHEN c.status = 'APPROVED' THEN 1 ELSE 0 END) AS approved, "
        f"SUM(CASE WHEN c.status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected, "
        f"SUM(CASE WHEN c.status IN ('RETURNED','DOCS_REQUESTED','REJECTED') THEN 1 ELSE 0 END) AS sent_back "
        f"FROM cases c JOIN departments d ON d.code = c.department_code WHERE {where} "
        f"GROUP BY d.code ORDER BY total DESC", args)]

    # What the AI concluded on the latest completed check of each case.
    verdicts = {"FORWARD": 0, "RETURN_FOR_CORRECTION": 0, "HOLD": 0, "NONE": 0}
    high_hist = {"0": 0, "1": 0, "2": 0, "3+": 0}
    minutes: list[float] = []
    for r in conn.execute(
            f"SELECT cr.verdict, cr.high_flags, cr.started_at, cr.finished_at FROM case_runs cr "
            f"JOIN cases c ON c.id = cr.case_id WHERE {where} AND cr.state = 'done' "
            f"AND cr.id IN (SELECT id FROM case_runs x WHERE x.case_id = cr.case_id ORDER BY started_at DESC LIMIT 1)", args):
        verdicts[r["verdict"] if r["verdict"] in verdicts else "NONE"] += 1
        h = r["high_flags"] or 0
        high_hist["3+" if h >= 3 else str(h)] += 1
        if r["started_at"] and r["finished_at"] and r["started_at"] != r["finished_at"]:
            try:
                minutes.append((datetime.fromisoformat(r["finished_at"]) - datetime.fromisoformat(r["started_at"])).total_seconds() / 60)
            except ValueError:
                pass

    # Filing to decision, in days, over decided cases.
    days: list[float] = []
    for r in conn.execute(
            f"SELECT c.created_at, e.at FROM case_events e JOIN cases c ON c.id = e.case_id "
            f"WHERE {where} AND {decided_sql}", args):
        try:
            span = (datetime.fromisoformat(r["at"]) - datetime.fromisoformat(r["created_at"])).total_seconds() / 86400
        except ValueError:
            continue
        # Imported legacy cases carry their import date as created_at, which can postdate
        # the decision taken on the old portal; such spans say nothing and are left out.
        if span >= 0:
            days.append(span)

    # How long the pending cases have been waiting at their present stage (since the last status
    # change), in the buckets an office watches: up to 3 days, a week, a fortnight, longer.
    ageing = {"with_department": _ageing(conn, where, args, workflow.DEPARTMENT_HOLDS),
              "with_ag": _ageing(conn, where, args, workflow.AG_HOLDS)}

    out = {
        "scope": {"role": user.role, "department": user.department_code if user.role == "DEPT_OFFICER" else department,
                  "product": product},
        "ageing": ageing,
        "deficiencies": _deficiencies(conn, where, args),
        "total": sum(by_status.values()),
        "by_status": by_status,
        "weeks": [{"week": w.isoformat(), "filed": filed[w.isoformat()], "decided": decided[w.isoformat()]} for w in weeks],
        "by_department": by_department,
        "verdicts": verdicts,
        "high_flags": high_hist,
        "checks_total": conn.execute(f"SELECT COUNT(*) FROM case_runs cr JOIN cases c ON c.id = cr.case_id WHERE {where}", args).fetchone()[0],
        "avg_verification_minutes": round(sum(minutes) / len(minutes), 1) if minutes else None,
        "avg_days_to_decision": round(sum(days) / len(days), 1) if days else None,
        "decided_total": len(days),
        # The office's target from filing to decision, and how many decided cases met it.
        "decision_target_days": DECISION_TARGET_DAYS,
        "decided_within_target": sum(1 for d in days if d <= DECISION_TARGET_DAYS),
    }
    if user.role in OVERSIGHT_ROLES:
        out["by_desk"] = _by_desk(conn, where, args)
    if user.role == "DEPT_OFFICER":
        # The engine's verdicts, its findings histogram and the papers it found missing across the
        # department's cases are AI output; a department sees none of it (28 Sep 2026).
        for key in ("verdicts", "high_flags", "deficiencies"):
            out.pop(key, None)
    if user.role == "ADMIN":
        out["users_by_role"] = {r["role"]: r["n"] for r in conn.execute("SELECT role, COUNT(*) n FROM users WHERE active = 1 GROUP BY role")}
        out["audit_by_day"] = [dict(r) for r in conn.execute(
            "SELECT substr(at, 1, 10) AS day, COUNT(*) n FROM audit_log WHERE at >= ? GROUP BY day ORDER BY day",
            ((today - timedelta(days=13)).isoformat(),))]
    return out


# -- cases -------------------------------------------------------------------------------------

_DEPT_NAMES: dict[str, str] = {}


def _dept_name(conn: db.Connection, code: str) -> str:
    if code not in _DEPT_NAMES:
        row = conn.execute("SELECT name FROM departments WHERE code = ?", (code,)).fetchone()
        _DEPT_NAMES[code] = row["name"] if row else DEPARTMENT_NAMES.get(code, code)
    return _DEPT_NAMES[code]


def _case_or_404(conn: db.Connection, case_id: str, user: User) -> db.Row:
    row = conn.execute("SELECT * FROM cases WHERE id = ? OR case_no = ?", (case_id, case_id)).fetchone()
    if row is None:
        raise HTTPException(404, f"no case {case_id}")
    if not workflow.may_see_user(user, row):
        if user.role in TIER_ROLES and workflow.wing_of_case(row) == user.pension_wing:
            raise HTTPException(403, "this case has not been sent to your desk")
        raise HTTPException(403, "this case belongs to another department")
    return row


def _own_side_or_403(user: User, case: db.Row) -> None:
    if not workflow.owns_side(user.role, user.department_code, case):
        raise HTTPException(403, "only the department that holds this case may do this")


#: Run fields a department may see: that a verification ran, and when. Its findings, verdict and
#: flag counts are the Accountant General's (decision of 28 Sep 2026).
_RUN_PUBLIC = ("id", "case_id", "run_id", "submission_no", "started_at", "finished_at", "state", "auto_forward")


#: What a department reads in place of the verification's own summary line, which states the engine's
#: verdict and its count of findings (28 Sep 2026: departments see no AI output).
_DEPT_REMARKS = {
    "CHECK_DONE": "The verification is complete; the case is with the Office of the Accountant General.",
}


def _redact_event(e: dict) -> None:
    action = e.get("action")
    if action in _DEPT_REMARKS:
        e["remark"] = _DEPT_REMARKS[action]
    if "payload" not in e:
        return
    if action in ("CHECK_DONE", "AUTO_APPROVE"):
        e["payload"] = {k: v for k, v in e["payload"].items() if k in ("auto",)}
    elif action == "SET_CASE_TYPE":
        e["payload"] = {k: v for k, v in e["payload"].items() if k != "detected_case_type"}
    elif action in ("AUTO_RETURN", "RETURN") and e["payload"].get("auto"):
        # The GP Fund module's automatic return carried its whole examination; the department
        # gets what it must act on (audit 6 Oct 2026).
        e["payload"] = {k: v for k, v in e["payload"].items() if k in ("auto", "missing_checklist", "items")}


def _redact(d: dict, user: User) -> dict:
    """The case as a department officer may see it: no verdicts, flag counts or forwarded issues."""
    if user.role != "DEPT_OFFICER":
        return d
    d["detected_case_type"] = None
    d["detected_case_type_confidence"] = None
    if d.get("case_type_source") == "DETECTED":
        d["case_type_source"] = None                      # an undeclared case's type came from the engine (N29)
    if d.get("latest_run"):
        d["latest_run"] = {k: d["latest_run"].get(k) for k in _RUN_PUBLIC}
    if "runs" in d:
        d["runs"] = [{k: r.get(k) for k in _RUN_PUBLIC} for r in d["runs"]]
    # The moves between tiers are the AG's own business (C3): a DDO's history has no such rows,
    # and its "last event" is the last row the DDO may see.
    if "events" in d:
        d["events"] = [e for e in d["events"] if e.get("action") not in workflow.INTERNAL_ACTIONS]
    if d.get("last_event") and d["last_event"].get("action") in workflow.INTERNAL_ACTIONS:
        visible = d.get("events") or []
        d["last_event"] = visible[-1] if visible else None
    d["holder_tier"] = None                               # the DDO sees "with the Office of the Accountant General", not which desk
    d["holder_label"] = "With the Office of the Accountant General" if d.get("status") in workflow.AG_HOLDS else None
    for e in d.get("events") or []:
        _redact_event(e)
    if d.get("last_event"):
        _redact_event(d["last_event"])
    return d


def _case_dict(conn: db.Connection, row: db.Row, *, full: bool = False) -> dict:
    d = dict(row)
    d["department_name"] = _dept_name(conn, row["department_code"])
    from api.inventory import LEGACY, section_of
    sec = section_of(row["department_code"])
    d["pension_section"] = None if sec == LEGACY else sec     # the register shows "Legacy" for None
    d["status_label"] = workflow.STATUS_LABELS.get(row["status"], row["status"])
    # Who holds the case inside the AG (C3): the tier, and the wing the department belongs to.
    d["pension_wing"] = workflow.wing_of_case(row)
    d["holder_tier"] = row["holder_tier"] if "holder_tier" in row.keys() else None
    d["holder_label"] = workflow.holder_label(row)
    d["intake"] = json.loads(row["intake_json"] or "{}")
    del d["intake_json"]
    # Two rows of one case can share started_at: it was written at second precision until
    # 13 Oct 2026, and the rows from before then still are. submission_no is the real sequence
    # and breaks that tie correctly; id, a uuid4, only makes what is left stable rather than
    # arbitrary (audit of 13 Oct 2026, H-08).
    latest = conn.execute("SELECT * FROM case_runs WHERE case_id = ? ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1",
                          (row["id"],)).fetchone()
    d["latest_run"] = dict(latest) if latest else None
    if d["latest_run"]:
        d["latest_run"]["blocking_flags"] = json.loads(d["latest_run"].pop("blocking_flags_json") or "[]")
    if not full:
        last_event = conn.execute(
            "SELECT action, remark, actor_name, actor_role, at FROM case_events WHERE case_id = ? "
            "ORDER BY seq DESC LIMIT 1", (row["id"],)).fetchone()
        d["last_event"] = dict(last_event) if last_event else None
        d["documents"] = conn.execute("SELECT COUNT(*) FROM case_documents WHERE case_id = ? "
                                      "AND superseded_in_submission IS NULL", (row["id"],)).fetchone()[0]
        return d
    d["documents"] = [dict(r) for r in conn.execute(
        "SELECT id, submission_no, seq, filename, sha256, bytes, uploaded_by, uploaded_at, "
        "replaces_document_id, superseded_in_submission "
        "FROM case_documents WHERE case_id = ? ORDER BY submission_no, seq", (row["id"],))]
    d["runs"] = []
    for r in conn.execute("SELECT * FROM case_runs WHERE case_id = ? ORDER BY started_at", (row["id"],)):
        rr = dict(r)
        rr["blocking_flags"] = json.loads(rr.pop("blocking_flags_json") or "[]")
        d["runs"].append(rr)
    d["events"] = []
    for r in conn.execute("SELECT * FROM case_events WHERE case_id = ? ORDER BY seq", (row["id"],)):
        e = dict(r)
        e["payload"] = json.loads(e.pop("payload_json") or "{}")
        d["events"].append(e)
    fwd = next((e for e in reversed(d["events"]) if e["action"] == "FORWARD"), None)
    d["forwarded_with"] = fwd["payload"] if fwd else None
    d["officer_remark"] = fwd["remark"] if fwd else None
    return d


@router.get("/cases")
def list_cases(status_filter: str | None = None, department: str | None = None, product: str | None = None,
               case_type: str | None = None, pension_section: str | None = None,
               user: User = Depends(current_user), conn: db.Connection = Depends(get_conn)) -> list[dict]:
    """The cases this user may see, narrowed by the filters -- the same scope every count and
    chart uses (api.inventory), so a list and its counts cannot disagree."""
    case_runs.sync_run_states(conn)
    return _inventory_rows(conn, user, status_filter=status_filter, department=department, product=product,
                           case_type=case_type, pension_section=pension_section)


def _inventory_rows(conn: db.Connection, user: User, *, status_filter: str | None = None,
                    department: str | None = None, product: str | None = None, case_type: str | None = None,
                    pension_section: str | None = None) -> list[dict]:
    from api import inventory
    product = _product_or_422(product)
    if department and user.role == "DEPT_OFFICER" and department != user.department_code:
        raise HTTPException(403, "you may list only your own department's cases")
    if pension_section:
        _section_codes_or_422(pension_section)
    where, args = inventory.scope(conn, user, product=product, department=department, section=pension_section)
    if case_type:
        where += " AND c.case_type = ?"; args.append(_case_type_or_422(case_type))
    if status_filter:
        statuses = [s for s in status_filter.split(",") if s]
        unknown = [s for s in statuses if s not in workflow.STATUSES]
        if unknown:
            raise HTTPException(422, f"unknown status: {', '.join(unknown)}")
        if statuses:
            where += f" AND c.status IN ({','.join('?' * len(statuses))})"; args.extend(statuses)
    sql = f"SELECT c.* FROM cases c WHERE {where} ORDER BY c.updated_at DESC"
    return [_redact(_case_dict(conn, r), user) for r in conn.execute(sql, args)]


@router.get("/inventory")
def case_inventory(product: str | None = None, department: str | None = None, pension_section: str | None = None,
                   user: User = Depends(current_user), conn: db.Connection = Depends(get_conn)) -> dict:
    """One product's case inventory as this user sees it: the rows, and every count computed from
    those same rows (api.inventory). ``sidebar`` is the product-wide count per department and
    section, from the same query without the department/section narrowing, so the sidebar, the
    tabs, the KPI cards and the table all agree -- and ``version`` says which state they show."""
    from api import inventory
    case_runs.sync_run_states(conn)
    ver = inventory.version(conn)
    everything = _inventory_rows(conn, user, product=product)
    if department or pension_section:
        codes = set(inventory.section_codes(conn, pension_section)) if pension_section else None
        if pension_section:
            _section_codes_or_422(pension_section)
        rows = [r for r in everything if (not department or r["department_code"] == department)
                and (codes is None or r["department_code"] in codes)]
    else:
        rows = everything
    depts = inventory.visible_departments(conn, user)       # a wing officer's own departments only
    out = {"version": ver, "product": product, "rows": rows, "counts": inventory.counts_of(rows, [])}
    if user.role in workflow.AG_READERS:
        side = inventory.counts_of(everything, depts)
        out["sidebar"] = {"total": side["total"], "by_department": side["by_department"], "by_section": side["by_section"]}
    return out


@router.get("/inventory/version")
def inventory_version(user: User = Depends(current_user), conn: db.Connection = Depends(get_conn)) -> dict:
    """A token that changes whenever any case moves; every open view refetches when it does."""
    from api import inventory
    case_runs.sync_run_states(conn)
    return {"version": inventory.version(conn)}


def _next_case_no(conn: db.Connection) -> str:
    """The next case number. Call inside the insert's transaction (BEGIN IMMEDIATE holds the
    write lock), so two cases filed at once cannot draw the same number."""
    year = date.today().year
    row = conn.execute("SELECT MAX(CAST(substr(case_no, 9) AS INTEGER)) FROM cases WHERE case_no LIKE ?",
                       (f"PC-{year}-%",)).fetchone()
    return f"PC-{year}-{(row[0] or 0) + 1:06d}"


_TEXT_EXT = (".txt", ".csv", ".rtf")
_MAGIC = {b"%PDF": "pdf", b"PK\x03\x04": "zip", b"\x89PNG": "image", b"\xff\xd8\xff": "image", b"GIF8": "image",
          b"II*\x00": "image", b"MM\x00*": "image", b"BM": "image", b"RIFF": "image", b"\xd0\xcf\x11\xe0": "office"}


#: The names a file of each kind may carry. A PDF's magic bytes in front of HTML, saved as
#: notice.html, passed the magic check and was then served -- and opened by the portal -- as a web
#: page on the portal's own address (audit 6 Oct 2026). No extension at all is allowed: a scanner's
#: "scan001" is still a PDF, and such a file is only ever served as a download.
_KIND_EXT = {
    "pdf": {".pdf"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp", ".webp"},
    "office": {".doc", ".xls", ".ppt"},
    "zip": {".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"},
}
#: What a stored document is served as, by its extension; everything else is a download.
_SERVE_AS = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".gif": "image/gif", ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff",
             ".bmp": "image/bmp"}


class _Staged:
    """An upload already on disk (``_read_uploads``): its name, path, first bytes, size and hash."""
    __slots__ = ("name", "path", "head", "size", "sha256")

    def __init__(self, name: str, path: Path, head: bytes, size: int, sha256: str) -> None:
        self.name, self.path, self.head, self.size, self.sha256 = name, path, head, size, sha256


def _document_problem(name: str, body: "bytes | _Staged") -> str | None:
    """Why this upload is not a document the verification can read, or None. Checked at upload
    so the officer hears it now, by filename, rather than from a failed verification later.

    The file's first bytes decide, never its name alone. The two short signatures that other
    formats share are pinned down: RIFF is also WAV and AVI, so only RIFF....WEBP passes; "BM"
    is two letters many files can start with, so it passes only on a .bmp. A text file must be
    text. A PDF is refused past the page limit (api.settings.max_case_pages); an image past the
    pixel limits of pipeline.bundle, read from its headers."""
    staged = body if isinstance(body, _Staged) else None
    head = staged.head if staged else body
    full = (lambda: staged.path.read_bytes()) if staged else (lambda: body)
    body = head                                   # the checks below need only the first 64 KB
    kind = next((k for magic, k in _MAGIC.items() if body.startswith(magic)), None)
    lower = name.lower()
    if kind == "image" and body.startswith(b"RIFF") and body[8:12] != b"WEBP":
        kind = None
    if kind == "image" and body.startswith(b"BM") and not lower.endswith(".bmp"):
        kind = None
    ext = os.path.splitext(lower)[1]
    if kind is not None and ext and ext not in _KIND_EXT[kind]:
        return (f"is a {'PDF' if kind == 'pdf' else kind} file but is named {ext}; save it with its proper "
                f"extension ({', '.join(sorted(_KIND_EXT[kind]))})")
    from pipeline.bundle import OFFICE_EXT, office_problem
    if ext in OFFICE_EXT and (kind in ("office", "zip") or lower.endswith(_TEXT_EXT)):
        # Contents that match the name, and nothing loaded from outside (audit 6 Oct 2026, item 6).
        problem = office_problem(full(), ext)
        if problem:
            return problem
    if kind is None:
        if lower.endswith(_TEXT_EXT) and _is_text(body):
            return None
        return "not a PDF, image, Office file or zip archive"
    if kind == "pdf":
        pages = pdf_page_count(staged.path if staged else full())
        if pages is not None and pages > settings.max_case_pages():
            return f"has {pages} pages; the most one file may have is {settings.max_case_pages()}"
    if kind == "image":
        # Measured from its headers, before anything is decoded (audit 6 Oct 2026, item 5).
        import io
        from pipeline.bundle import image_problem
        return image_problem(staged.path if staged else io.BytesIO(full()))
    return None                                   # a PDF with no readable pages is the verification's finding


def _is_text(body: bytes) -> bool:
    head = body[:65536]
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        return exc.start >= len(head) - 4         # a character cut at the 64 KB boundary
    return True


def pdf_page_count(body: "bytes | Path") -> int | None:
    """Pages in this PDF, from poppler's pdfinfo; None where it cannot say (the verification
    then reports the file as it finds it -- an unreadable PDF is not refused here)."""
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("pdfinfo"):
        return None
    if isinstance(body, Path):
        try:
            out = subprocess.run(["pdfinfo", str(body)], capture_output=True, text=True, errors="replace", timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        m = re.search(r"^Pages:\s+(\d+)", out, re.M)
        return int(m.group(1)) if m else None
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
        fh.write(body)
        fh.flush()
        try:
            out = subprocess.run(["pdfinfo", fh.name], capture_output=True, text=True, errors="replace", timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else None


def _staging_dir() -> Path:
    """Where uploads land while they are checked: beside the case files, so filing one is a rename."""
    path = case_runs.CASE_FILES / ".incoming"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_uploads(files: list[UploadFile]) -> list[_Staged]:
    """Stream every upload to a staging file and check it, BEFORE any database transaction.

    Streamed, not read into memory: a request may carry 512 MB, and holding each one whole in the
    API process let a few concurrent uploads exhaust the box (audit 6 Oct 2026). The hash is taken
    on the way through. On any refusal every staged file is removed; the caller removes the rest
    (``_discard_staged``) once they have been filed or the filing failed.
    """
    import tempfile
    from api.runs import disk_shortfall
    if not files:
        raise HTTPException(422, "attach at least one document")
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"at most {MAX_FILES} files in one upload")
    short = disk_shortfall(case_runs.CASE_FILES)
    if short:
        raise HTTPException(507, short)                      # Insufficient Storage (audit 6 Oct 2026, R8)
    out: list[_Staged] = []
    total = 0
    try:
        for f in files:
            name = (f.filename or "document").split("/")[-1]
            digest, size, head = hashlib.sha256(), 0, b""
            with tempfile.NamedTemporaryFile(dir=_staging_dir(), prefix="up-", delete=False) as fh:
                staged = _Staged(name, Path(fh.name), b"", 0, "")
                out.append(staged)
                while True:                           # in pieces: the limit stops the read, not the other way round
                    piece = f.file.read(1 << 20)
                    if not piece:
                        break
                    size += len(piece); total += len(piece)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, f"{f.filename} exceeds {MAX_UPLOAD // 1048576} MB")
                    if total > MAX_UPLOAD_TOTAL:
                        raise HTTPException(413, f"the upload exceeds {MAX_UPLOAD_TOTAL // 1048576} MB in all")
                    if len(head) < 65536:
                        head += piece[:65536 - len(head)]
                    digest.update(piece)
                    fh.write(piece)
            staged.head, staged.size, staged.sha256 = head, size, digest.hexdigest()
            if not size:
                out.pop()
                staged.path.unlink(missing_ok=True)
                continue
            problem = _document_problem(name, staged)
            if problem:
                raise HTTPException(422, f"{name}: {problem}")
    except BaseException:
        _discard_staged(out)
        raise
    if not out:
        raise HTTPException(422, "every attached file was empty")
    return out


def _discard_staged(uploads: list[_Staged]) -> None:
    for u in uploads:
        try:
            u.path.unlink(missing_ok=True)
        except OSError:
            pass


def _store_files(conn: db.Connection, case: db.Row | dict, files: list[_Staged],
                 user: User) -> list[dict]:
    """Record each upload under the case's current submission. Caller holds the transaction. The
    bytes are already on disk (``_read_uploads``), so under the write lock each file is only
    renamed into place; ``_discard_files`` removes them if the transaction does not go through."""
    entries = _write_files(conn, case, files, user)
    for entry in entries:
        conn.execute(
            "INSERT INTO case_documents(id, case_id, submission_no, seq, filename, sha256, bytes, "
            "stored_path, uploaded_by, uploaded_at) VALUES (:id, :case_id, :submission_no, :seq, "
            ":filename, :sha256, :bytes, :stored_path, :uploaded_by, :uploaded_at)", entry)
    return entries


def _write_files(conn: db.Connection, case: db.Row | dict, files: list[_Staged],
                 user: User) -> list[dict]:
    """The staged files into the case's folder, numbered after the documents already on this
    submission. A rename on the same filesystem: nothing is copied while the lock is held."""
    from pipeline.bundle import looks_like_pdf, looks_like_zip
    target = case_runs.document_dir(case["id"], case["submission_no"])
    target.mkdir(parents=True, exist_ok=True)
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM case_documents WHERE case_id = ? AND submission_no = ?",
                       (case["id"], case["submission_no"])).fetchone()[0]
    stored: list[dict] = []
    for upload in files:
        seq += 1
        name = _SAFE_NAME.sub("_", upload.name) or "document"
        path = target / f"{seq:02d}-{name}"
        os.replace(upload.path, path)
        stored.append({"id": db.new_id(), "case_id": case["id"], "submission_no": case["submission_no"],
                       "seq": seq, "filename": name, "sha256": upload.sha256,
                       "bytes": upload.size, "stored_path": str(path), "uploaded_by": user.id,
                       "uploaded_at": db.now(),
                       "kind": "pdf" if looks_like_pdf(upload.head) else "zip" if looks_like_zip(upload.head) else "other"})
    return stored


def _discard_files(entries: list[dict]) -> None:
    for e in entries:
        try:
            Path(e["stored_path"]).unlink(missing_ok=True)
        except OSError:
            pass


@router.post("/cases", status_code=201)
def create_case(
    files: list[UploadFile] = File(default=[]),
    department_code: str | None = Form(default=None),
    claimant_name: str | None = Form(default=None),
    variant: str | None = Form(default=None),
    annual_pay: str | None = Form(default=None),
    commutation_percent: str | None = Form(default=None),
    retirement_date: str | None = Form(default=None),
    pension_in_payment: str | None = Form(default=None),
    date_of_death: str | None = Form(default=None),
    product: str = Form(default="PENSION"),
    gpf_kind: str | None = Form(default=None),
    gazetted: str | None = Form(default=None),
    case_type: str | None = Form(default=None),
    user: User = Depends(require_roles("DEPT_OFFICER")),
    conn: db.Connection = Depends(get_conn),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    """A new case with its documents, submitted to the Accountant General at once (decision of
    28 Sep 2026: filing is submission; the AI verification runs on the AG's desk).

    ``product`` is PENSION or GPF (a GP Fund claim, examined by the GP Fund module; it needs the
    kind of claim). A DDO (role DEPT_OFFICER) files for their own department, always; only the
    administrator picks.
    """
    replay = _idempotent_replay(conn, user, idempotency_key)
    if replay is not None:
        return replay
    if product not in PRODUCTS:
        raise HTTPException(422, f"unknown product {product!r}; one of {', '.join(PRODUCTS)}")
    if product == "GPF" and gpf_kind not in gpf_bridge.KINDS:
        raise HTTPException(422, "choose the kind of GP Fund claim: " + ", ".join(gpf_bridge.KINDS))
    # A pension case is filed under a declared case type (29 Sep 2026): mandatory, from the
    # shared list. It selects the checklist and the rules; the papers are checked against it.
    declared: str | None = None
    if product == "PENSION":
        if not (case_type or "").strip():
            raise HTTPException(422, "select the case type before submitting the case")
        declared = _case_type_or_422(case_type)
        # The office checklist column follows the type. A department may name the claimant's
        # column where the type has several (a widow, an unmarried daughter ...); anything
        # else it sends as a variant is refused rather than quietly accepted.
        columns = variants_for_case_type(declared)
        if variant and variant not in columns:
            raise HTTPException(422, f"{variant!r} is not a kind of {case_type_label(declared)}; "
                                     f"choose one of {list(columns)}" if columns else
                                     f"{case_type_label(declared)} has no checklist column to choose")
        if not variant and len(columns) == 1:
            variant = columns[0]
    if user.role == "DEPT_OFFICER":
        department_code = user.department_code           # forced: not chosen, not overridable
    if not department_code or department_code == LEGACY_DEPARTMENT[0] or not conn.execute(
            "SELECT 1 FROM departments WHERE code = ? AND active = 1", (department_code,)).fetchone():
        raise HTTPException(422, "choose the department the case belongs to")
    uploads = _read_uploads(files)
    try:
        result = _create_case(conn, user, uploads, department_code, claimant_name, variant, annual_pay,
                              commutation_percent, retirement_date, pension_in_payment, date_of_death,
                              product, gpf_kind, gazetted, declared)
    finally:
        _discard_staged(uploads)                      # whatever was not filed
    _idempotent_remember(conn, user, idempotency_key, 201, result)
    return result


def _create_case(conn, user, uploads, department_code, claimant_name, variant, annual_pay, commutation_percent,
                 retirement_date, pension_in_payment, date_of_death, product, gpf_kind, gazetted, declared) -> dict:
    # The same validation the old intake applies (desk permissions aside: the role decides here).
    from api.server import _intake_choices
    if product == "GPF":
        choices = {"variant": None, "gpf_kind": gpf_kind, "gazetted": gazetted if gazetted in gpf_bridge.GAZETTED else "unknown"}
    else:
        # The variant that follows from the declared type is the department's to give; the
        # AG-only intake figures (pay, commutation, dates) keep their desk rule.
        choices = _intake_choices(None if user.role == "DEPT_OFFICER" else variant,
                                  annual_pay, commutation_percent, retirement_date,
                                  pension_in_payment, date_of_death,
                                  "AG_REVIEWER" if capabilities(user)["intake_choices"] else "AD_SUBMITTER")   # the desk name api.desks knows
        choices["variant"] = variant or None
    now = db.now()
    case = {"id": db.new_id(), "case_no": "", "department_code": department_code,
            "created_via": "DEPARTMENT", "product": product,
            "created_by": user.id, "status": workflow.DRAFT,
            "claimant_name": _clean_name(claimant_name), "variant": choices["variant"],
            "case_type": declared, "case_type_source": "DECLARED" if declared else None,
            "intake_json": json.dumps({k: v for k, v in choices.items() if k != "variant"}),
            "submission_no": 1, "current_run_id": None, "created_at": now, "updated_at": now}
    stored: list[dict] = []
    try:
        with db.transaction(conn):
            case["case_no"] = _next_case_no(conn)
            conn.execute(
                "INSERT INTO cases(id, case_no, department_code, created_via, product, created_by, status, "
                "claimant_name, variant, case_type, case_type_source, intake_json, submission_no, current_run_id, "
                "created_at, updated_at) "
                "VALUES (:id, :case_no, :department_code, :created_via, :product, :created_by, :status, :claimant_name, "
                ":variant, :case_type, :case_type_source, :intake_json, :submission_no, :current_run_id, "
                ":created_at, :updated_at)", case)
            stored = _store_files(conn, case, uploads, user)
            workflow.record_event(conn, case["id"], action="CREATE", from_status=None,
                                  to_status=workflow.DRAFT, actor=user,
                                  payload={"documents": [s["filename"] for s in stored],
                                           "department": department_code, "product": product,
                                           "case_type": declared, "variant": choices["variant"]})
    except Exception:
        _discard_files(stored)                        # the rows rolled back; the bytes must not stay behind
        raise
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case["id"],)).fetchone()
    if not stored:
        raise HTTPException(422, "attach at least one document")
    workflow.transition(conn, row, "FORWARD", user, payload={"documents": len(stored), "submission_no": 1})
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case["id"],)).fetchone()
    result: dict[str, Any] = {"case": _redact(_case_dict(conn, row, full=True), user)}
    return result


def _idempotent_replay(conn: db.Connection, user: User, key: str | None):
    """The first answer again, for a request the client is repeating (frontend review F8, 9 Oct
    2026): a browser on slow Wi-Fi retries a filing whose answer never arrived, and without this
    the retry filed the case twice. Keys are the client's (a UUID per attempt), per user, kept a day."""
    key = (key or "").strip()[:80]
    if not key:
        return None
    row = conn.execute("SELECT status_code, response_json FROM idempotency_keys WHERE user_id = ? AND key = ?",
                       (user.id, key)).fetchone()
    if row is None:
        return None
    return JSONResponse(json.loads(row["response_json"]), status_code=int(row["status_code"]),
                        headers={"Idempotent-Replayed": "true"})


def _idempotent_remember(conn: db.Connection, user: User, key: str | None, status_code: int, result: dict) -> None:
    key = (key or "").strip()[:80]
    if not key:
        return
    from datetime import datetime, timedelta
    conn.execute("DELETE FROM idempotency_keys WHERE created_at < ?",
                 ((datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"),))
    conn.execute("INSERT OR IGNORE INTO idempotency_keys(user_id, key, created_at, status_code, response_json) "
                 "VALUES (?, ?, ?, ?, ?)", (user.id, key, db.now(), status_code, json.dumps(result, default=str)))


@router.get("/cases/{case_id}")
def get_case(case_id: str, user: User = Depends(current_user),
             conn: db.Connection = Depends(get_conn)) -> dict:
    case_runs.sync_run_states(conn)
    row = _case_or_404(conn, case_id, user)
    if row["product"] == "GPF" and case_runs.sync_gpf_case(conn, row):
        row = _case_or_404(conn, case_id, user)
    d = _redact(_case_dict(conn, row, full=True), user)
    d["allowed_actions"] = _allowed_actions(conn, user, row)
    d["may_dispose"] = _may_dispose(conn, user, row)
    return d


def _allowed_actions(conn: db.Connection, user: User, row: db.Row) -> list[str]:
    """The moves this user may make on this case now: by role and status (workflow.TRANSITIONS),
    by side, by wing and holder tier (C3), by verification, and by maker-checker."""
    out = []
    for a in workflow.allowed_actions(user.role, row["status"]):
        if a == "OVERRIDE":
            continue
        if a in ("ADD_DOCS", "REPLACE_DOC", "FORWARD") and not workflow.owns_side(user.role, user.department_code, row):
            continue
        if a in DECISIONS_NEED_VERIFICATION and not _verified(conn, row):
            continue
        try:
            workflow.check_holder(user, row, a)
            if a in workflow.INTERNAL_ACTIONS:
                workflow.next_holder(a, row, row["status"])       # a last tier cannot forward, a first cannot return down
        except workflow.WorkflowError:
            continue
        out.append(a)
    if user.role in workflow.ANY_TIER:
        out.append("OVERRIDE")                                # the Deputy AG's and the AG desk's, not the administrator's (G6)
    if "APPROVE" in out and user.id in _submitters(conn, row):
        out.remove("APPROVE")                                 # maker-checker (C1): the submitter does not approve
    return out


def _may_dispose(conn: db.Connection, user: User, row: db.Row) -> bool:
    """Whether this officer may act on the findings of the case's current examination.

    The same conditions ``_run_for(acting=True)`` enforces, answered once for the screen so the
    waive and uphold controls are offered only where they will work. The screen decided it from
    the role capability alone, so every AG account was shown them and all but the holding tier
    got a 409 on the press (audit 13 Oct 2026, M-12). Kept out of ``allowed_actions``: that list
    is the workflow moves the action panel draws buttons for, and this is not one of them.
    """
    if user.role not in workflow.AG_SIDE or row["status"] != workflow.UNDER_REVIEW:
        return False
    try:
        workflow.check_holder(user, row, "DISPOSE")
        workflow.check_one_tier_per_case(conn, user, row)
    except workflow.WorkflowError:
        return False
    return True


#: What the old register (api.cases) records as the deciding desk for each portal role.
MIRROR_ROLE_LABELS = {"AG_SENIOR_AUDITOR": "Senior Auditor, Pension wing (AG)", "AG_ASSISTANT_AO": "Assistant Accounts Officer, Pension wing (AG)",
                      "AG_AO": "Accounts Officer, Pension wing (AG)", "AG_REVIEWER": "AG / Additional AG and senior officers (all wings)",
                      "AG_DAG": "Deputy Accountant General (Pension)"}

#: Acting on a case (29 Sep 2026) needs a completed AI examination of the papers as they stand:
#: the AG approves, rejects, returns or asks for documents on what the machine has read, never
#: on a file nobody has opened. Only the examination itself, and the administrator's audited
#: override, come before it.
DECISIONS_NEED_VERIFICATION = frozenset({"APPROVE", "REJECT", "RETURN", "REQUEST_DOCS", "FORWARD_TIER"})


def _verified(conn: db.Connection, row: db.Row) -> bool:
    """A verification that completed on the current round of papers, and on the case's CURRENT run.

    A decision rests on the examination the case is on, not on an earlier one that happened to
    finish on the same papers. After a failed re-verification (AI_FAILED) the current run is the
    failed one, so until it is verified again nobody approves, rejects or returns on findings
    that predate it (audit of 12 Oct 2026)."""
    if not row["current_run_id"]:
        return False
    return conn.execute("SELECT 1 FROM case_runs WHERE case_id = ? AND submission_no = ? AND run_id = ? "
                        "AND state = 'done' LIMIT 1",
                        (row["id"], row["submission_no"], row["current_run_id"])).fetchone() is not None


def _section_codes_or_422(section: str) -> list[str]:
    """The department codes of one Pension section; LEGACY is the legacy bucket and every
    department with no section of its own (api.inventory.section_of)."""
    from api import inventory
    conn = db.connect()
    try:
        return inventory.section_codes(conn, section)
    except KeyError:
        raise HTTPException(422, f"unknown pension section {section!r}; one of {', '.join(PENSION_SECTION_ORDER)}") from None
    finally:
        conn.close()


# -- the case type ---------------------------------------------------------------------------------

def _case_type_or_422(value: str | None) -> str:
    key = canonical_office_type((value or "").strip() or None)
    if not key:
        raise HTTPException(422, f"unknown case type {value!r}; one of {', '.join(OFFICE_CASE_TYPES)}")
    return key


@router.get("/case-types")
def case_types(user: User = Depends(current_user)) -> dict:
    """The case types a DDO files under: the columns of the AG office's document sheet
    (config/case_types.json, shared with the portal), each with the documents the sheet ticks for
    it -- so the department knows what to attach before it attaches anything."""
    from rules.checklist import ALL_VARIANTS, requirements_for
    out = []
    for info in load_case_types()["case_types"]:
        reqs = requirements_for(info["id"]) if info["id"] in ALL_VARIANTS else ()
        out.append({"id": info["id"], "label": info["label"], "family": info["family"],
                    "hint": info.get("hint", ""), "prescribed_form": info.get("prescribed_form"),
                    "pipeline_types": info.get("pipeline_types", []), "variants": [],
                    "documents": [{"id": r.id, "requirement": r.requirement} for r in reqs]})
    return {"case_types": out}


@router.post("/cases/{case_id}/case-type")
def set_case_type(case_id: str, body: dict = Body(...), request: Request = None,
                  user: User = Depends(require_roles("DEPT_OFFICER", *workflow.AG_SIDE)),
                  conn: db.Connection = Depends(get_conn)) -> dict:
    """Change the case type. A department may change its declaration while the case is on its
    side (not yet forwarded, or sent back); the Accountant General and the administrator may
    correct it at any point, with a remark, and the correction is audited. The AI's own reading
    is never overwritten. A corrected type takes effect at the next verification."""
    case_runs.sync_run_states(conn)
    row = _case_or_404(conn, case_id, user)
    if row["product"] != "PENSION":
        raise HTTPException(422, "only a pension case has a case type")
    if user.role in workflow.AG_SIDE and row["status"] in workflow.AG_HOLDS:
        # The type decides the checklist column the next verification runs on, so while the AG
        # holds the case only the holding tier corrects it (audit of 12 Oct 2026).
        try:
            workflow.check_holder(user, row, "SET_CASE_TYPE")
        except workflow.WorkflowError as exc:
            _raise(exc)
    new_type = _case_type_or_422(body.get("case_type"))
    variant = (body.get("variant") or "").strip() or None
    columns = variants_for_case_type(new_type)
    if variant and variant not in columns:
        raise HTTPException(422, f"{variant!r} is not a kind of {case_type_label(new_type)}")
    if not variant and len(columns) == 1:
        variant = columns[0]
    remark = (body.get("remark") or "").strip()
    if user.role == "DEPT_OFFICER":
        _own_side_or_403(user, row)
        if row["status"] not in workflow.CASE_TYPE_EDITABLE_BY_DEPARTMENT:
            raise HTTPException(409, "the case is with the Office of the Accountant General; the case type can no longer "
                                     "be changed by the department")
        source = "DECLARED"
    else:
        if len(remark) < 5:
            raise HTTPException(422, "a correction of the case type needs a remark")
        source = "CORRECTED"
    if new_type == row["case_type"] and (variant or None) == (row["variant"] or None):
        raise HTTPException(409, f"the case is already filed as {case_type_label(new_type)}")
    before = {"case_type": row["case_type"], "case_type_source": row["case_type_source"], "variant": row["variant"]}
    with db.transaction(conn):
        conn.execute("UPDATE cases SET case_type = ?, case_type_source = ?, variant = ?, updated_at = ? WHERE id = ?",
                     (new_type, source, variant, db.now(), row["id"]))
        workflow.record_event(conn, row["id"], action="SET_CASE_TYPE", from_status=row["status"],
                              to_status=row["status"], actor=user, remark=remark,
                              payload={"from": row["case_type"], "to": new_type, "source": source,
                                       "variant": variant, "detected_case_type": row["detected_case_type"]})
        if source == "CORRECTED":
            workflow.audit(conn, actor=user, action="CASE_TYPE_CORRECTED", entity_type="case", entity_id=row["id"],
                           before=before, after={"case_type": new_type, "case_type_source": source, "variant": variant},
                           reason=remark, ip=_client_address(request))
    fresh = conn.execute("SELECT * FROM cases WHERE id = ?", (row["id"],)).fetchone()
    return _redact(_case_dict(conn, fresh, full=True), user)


@router.post("/cases/{case_id}/documents", status_code=201)
def add_documents(case_id: str, files: list[UploadFile] = File(default=[]),
                        user: User = Depends(require_roles("DEPT_OFFICER")),
                        conn: db.Connection = Depends(get_conn),
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> Any:
    """More papers on the case. After an AG return this opens the next round of submission, and the
    case goes to DRAFT ("not yet resubmitted"), so the next document added does not open yet
    another round; the officer then resubmits it to the Accountant General."""
    replay = _idempotent_replay(conn, user, idempotency_key)
    if replay is not None:
        return replay
    uploads = _read_uploads(files)
    try:
        result = _add_documents(conn, user, case_id, uploads)
    finally:
        _discard_staged(uploads)
    _idempotent_remember(conn, user, idempotency_key, 201, result)
    return result


def _add_documents(conn: db.Connection, user: User, case_id: str, uploads: list[_Staged]) -> dict:
    case_runs.sync_run_states(conn)
    row = _case_or_404(conn, case_id, user)
    _own_side_or_403(user, row)
    try:
        workflow.check(user.role, row["status"], "ADD_DOCS")
    except workflow.WorkflowError as exc:
        _raise(exc)
    submission = row["submission_no"] + (1 if row["status"] in workflow.SENT_BACK else 0)
    stored: list[dict] = []
    try:
        with db.transaction(conn):
            if submission != row["submission_no"]:
                conn.execute("UPDATE cases SET submission_no = ?, updated_at = ? WHERE id = ?",
                             (submission, db.now(), row["id"]))
            case = dict(row); case["submission_no"] = submission
            stored = _store_files(conn, case, uploads, user)
            new_status = workflow.DRAFT if row["status"] in (workflow.AI_CHECKED, *workflow.SENT_BACK) else row["status"]
            cur = conn.execute("UPDATE cases SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                               (new_status, db.now(), row["id"], row["status"]))
            if cur.rowcount != 1:
                raise HTTPException(409, "the case changed while the documents were uploading; reload and try again")
            workflow.record_event(conn, row["id"], action="ADD_DOCS", from_status=row["status"],
                                  to_status=new_status, actor=user,
                                  payload={"documents": [s["filename"] for s in stored], "submission_no": submission})
    except Exception:
        _discard_files(stored)                        # the rows rolled back; the bytes must not stay behind
        raise
    fresh = conn.execute("SELECT * FROM cases WHERE id = ?", (row["id"],)).fetchone()
    return _redact(_case_dict(conn, fresh, full=True), user)


def _request_items_or_422(conn: db.Connection, row: db.Row, items: Any) -> list[dict]:
    """The items of a return or document request, checked against the case's own checklist."""
    if items in (None, ""):
        return []
    if not isinstance(items, list):
        raise HTTPException(422, "items must be a list")
    checklist: dict[str, dict] = {}
    from api.runs import ARTIFACTS
    from api.artefacts import report_dict
    rep = report_dict(ARTIFACTS / f"run-{row['current_run_id']}") if row["current_run_id"] else None
    for i in ((rep or {}).get("checklist") or {}).get("items") or []:
        checklist[i["id"]] = i
    out: list[dict] = []
    for it in items[:60]:
        if not isinstance(it, dict):
            raise HTTPException(422, "each item is an object")
        note = " ".join(str(it.get("note") or "").split())[:500]
        if it.get("id"):
            item = checklist.get(str(it["id"]))
            if item is None:
                raise HTTPException(422, f"this case's checklist has no item {it['id']!r}")
            out.append({"id": item["id"], "requirement": item.get("requirement") or "",
                        "status": item.get("status") or "", "note": note})
            continue
        label = " ".join(str(it.get("label") or "").split())[:200]
        pages = it.get("pages") or []
        if not isinstance(pages, list) or not all(str(p).isdigit() and int(p) > 0 for p in pages):
            raise HTTPException(422, "pages must be a list of page numbers")
        if len(label) < 3 and not pages:
            raise HTTPException(422, "name the document asked for, or the pages concerned")
        out.append({"label": label, "pages": sorted({int(p) for p in pages}), "note": note})
    return out


@router.post("/cases/{case_id}/documents/{doc_id}/replace", status_code=201)
def replace_document(case_id: str, doc_id: str, files: list[UploadFile] = File(default=[]),
                           user: User = Depends(require_roles("DEPT_OFFICER")),
                           conn: db.Connection = Depends(get_conn)) -> dict:
    """Put a corrected paper in place of one already filed (30 Sep 2026).

    The old document stays on file, marked superseded in this round, and drops out of the
    bundle from here on; the replacement is filed in this round like any added paper, so the
    round's verification reads the replacement and reuses everything else. Opens the next round
    after a return, exactly as adding a paper does.
    """
    uploads = _read_uploads(files)
    try:
        return _replace_document(conn, user, case_id, doc_id, uploads)
    finally:
        _discard_staged(uploads)


def _replace_document(conn: db.Connection, user: User, case_id: str, doc_id: str,
                      uploads: list[_Staged]) -> dict:
    if len(uploads) != 1:
        raise HTTPException(422, "attach exactly one file to put in place of the document")
    case_runs.sync_run_states(conn)
    row = _case_or_404(conn, case_id, user)
    _own_side_or_403(user, row)
    try:
        workflow.check(user.role, row["status"], "REPLACE_DOC")
    except workflow.WorkflowError as exc:
        _raise(exc)
    old = conn.execute("SELECT * FROM case_documents WHERE id = ? AND case_id = ?", (doc_id, row["id"])).fetchone()
    if old is None:
        raise HTTPException(404, "no such document on this case")
    if old["superseded_in_submission"] is not None:
        raise HTTPException(409, f"{old['filename']} has already been replaced")
    submission = row["submission_no"] + (1 if row["status"] in workflow.SENT_BACK else 0)
    stored: list[dict] = []
    try:
        with db.transaction(conn):
            if submission != row["submission_no"]:
                conn.execute("UPDATE cases SET submission_no = ?, updated_at = ? WHERE id = ?",
                             (submission, db.now(), row["id"]))
            case = dict(row); case["submission_no"] = submission
            stored = _store_files(conn, case, uploads, user)
            conn.execute("UPDATE case_documents SET replaces_document_id = ? WHERE id = ?", (old["id"], stored[0]["id"]))
            cur = conn.execute("UPDATE case_documents SET superseded_in_submission = ? WHERE id = ? "
                               "AND superseded_in_submission IS NULL", (submission, old["id"]))
            if cur.rowcount != 1:
                raise HTTPException(409, "the document changed while the replacement was uploading; reload and try again")
            new_status = workflow.DRAFT if row["status"] in (workflow.AI_CHECKED, *workflow.SENT_BACK) else row["status"]
            cur = conn.execute("UPDATE cases SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                               (new_status, db.now(), row["id"], row["status"]))
            if cur.rowcount != 1:
                raise HTTPException(409, "the case changed while the document was uploading; reload and try again")
            workflow.record_event(conn, row["id"], action="REPLACE_DOC", from_status=row["status"],
                                  to_status=new_status, actor=user,
                                  payload={"documents": [stored[0]["filename"]], "replaced": old["filename"],
                                           "replaced_document_id": old["id"], "submission_no": submission})
    except Exception:
        _discard_files(stored)
        raise
    fresh = conn.execute("SELECT * FROM cases WHERE id = ?", (row["id"],)).fetchone()
    return _redact(_case_dict(conn, fresh, full=True), user)


@router.get("/cases/{case_id}/rounds")
def case_rounds(case_id: str, user: User = Depends(current_user),
                conn: db.Connection = Depends(get_conn)) -> dict:
    """Every submission round of the case: what the AG asked for, the papers that answered it and,
    for the AG, what each round's verification ran, reused and found (api.rounds)."""
    from api import rounds
    case_runs.sync_run_states(conn)
    row = _case_or_404(conn, case_id, user)
    return {"case_id": row["id"], "submission_no": row["submission_no"],
            "rounds": rounds.history(conn, row["id"], for_department=user.role == "DEPT_OFFICER")}


@router.get("/cases/{case_id}/documents/{doc_id}")
def download_document(case_id: str, doc_id: str, user: User = Depends(current_user_q),
                      conn: db.Connection = Depends(get_conn)):
    from fastapi.responses import FileResponse
    row = _case_or_404(conn, case_id, user)
    doc = conn.execute("SELECT * FROM case_documents WHERE id = ? AND case_id = ?", (doc_id, row["id"])).fetchone()
    if doc is None:
        raise HTTPException(404, "no such document on this case")
    from pathlib import Path
    if not Path(doc["stored_path"]).is_file():
        raise HTTPException(410, f"{doc['filename']} is no longer on the server")
    # The type from a fixed list, never guessed from the name, and nothing the browser could run:
    # a stored file is a PDF, an image or a download (audit 6 Oct 2026).
    media = _SERVE_AS.get(os.path.splitext(doc["filename"].lower())[1], "application/octet-stream")
    return FileResponse(doc["stored_path"], filename=doc["filename"], media_type=media,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.post("/cases/{case_id}/check", status_code=202)
def run_check(case_id: str, user: User = Depends(require_roles("AG_SENIOR_AUDITOR", *workflow.ANY_TIER)),
              conn: db.Connection = Depends(get_conn)) -> dict:
    """"Verify case with AI": the Accountant General's button. The outcome moves the case by
    itself (api.case_runs): returned with the missing documents, approved, or under review."""
    case_runs.sync_run_states(conn)
    row = _case_or_404(conn, case_id, user)
    try:
        workflow.check(user.role, row["status"], "RUN_CHECK")
        return case_runs.start_check(conn, row, user)
    except workflow.WorkflowError as exc:
        _raise(exc)


def _submitters(conn: db.Connection, row: db.Row) -> set[str]:
    """The accounts that made this case: whoever created it and whoever submitted (FORWARD) it, in
    any round. Maker-checker (business decision C1, 7 Oct 2026): none of them may approve it."""
    ids = {row["created_by"]} if row["created_by"] else set()
    for e in conn.execute("SELECT actor_id FROM case_events WHERE case_id = ? AND action IN ('FORWARD', 'CREATE') "
                          "AND actor_id IS NOT NULL", (row["id"],)):
        ids.add(e["actor_id"])
    return ids


def _act(conn: db.Connection, user: User, case_id: str, action: str, body: dict,
         request: Request | None = None) -> dict:
    case_runs.sync_run_states(conn)
    row = _case_or_404(conn, case_id, user)
    remark = str(body.get("remark") or "").strip()
    if (action == "APPROVE" or (action == "OVERRIDE" and body.get("to_status") == workflow.APPROVED)) \
            and user.id in _submitters(conn, row):
        raise HTTPException(403, "maker-checker: the user who submitted this case cannot approve it; a second "
                                 "officer decides (decision C1, 7 Oct 2026)")
    if action == "OVERRIDE":
        # The Deputy AG's override is the one move that skips the workflow; it is held to the same
        # bar as approving against the findings (audit 7 Oct 2026): a written reason, and no
        # approval of a case the AI examination has not been run on.
        if len(remark) < workflow.MIN_OVERRIDE_REMARK:
            raise HTTPException(422, f"an override needs a reason of at least {workflow.MIN_OVERRIDE_REMARK} characters")
        if body.get("to_status") == workflow.APPROVED and not _verified(conn, row):
            raise HTTPException(409, "verify the case with AI before overriding it to approved: an approval rests on a "
                                     "completed examination of the papers")
    payload: dict = {}
    mirror: str | None = None
    if action == "OVERRIDE" and body.get("to_status") == row["status"]:
        raise HTTPException(409, f"the case is already {workflow.label(row['status']) if hasattr(workflow, 'label') else row['status']}; an override must change its status")
    if action == "FORWARD":
        _own_side_or_403(user, row)
        docs = conn.execute("SELECT COUNT(*) FROM case_documents WHERE case_id = ? AND superseded_in_submission IS NULL",
                            (row["id"],)).fetchone()[0]
        if not docs:
            raise HTTPException(422, "attach at least one document before submitting the case")
        payload = {"documents": docs, "submission_no": row["submission_no"]}
        run_id = None
    else:
        run_id = row["current_run_id"]
        if action in DECISIONS_NEED_VERIFICATION and not _verified(conn, row):
            raise HTTPException(409, "verify the case with AI first: every action on the case rests on a completed "
                                     "examination of the papers as submitted")
        if action == "APPROVE":
            # Against the engine's reading, an approval is an override and needs a real reason.
            # Ordered, because the table can hold more than one row for a run id and this
            # decides whether an approval must carry a written justification; an arbitrary row
            # made that non-deterministic (audit of 13 Oct 2026, H-08). Same order everywhere
            # the column is read, so every one of them sees the same row.
            latest = conn.execute("SELECT * FROM case_runs WHERE run_id = ? "
                                  "ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1", (run_id or "",)).fetchone()
            against = latest is None or (latest["verdict"] or "") != "FORWARD" or (latest["high_flags"] or 0) > 0
            if against and len(remark) < workflow.MIN_OVERRIDE_REMARK:
                raise HTTPException(422, f"approving against the AI findings needs a remark of at least "
                                         f"{workflow.MIN_OVERRIDE_REMARK} characters")
            mirror = "FORWARD"
        elif action == "FORWARD_TIER" and workflow.tier_of(user.role) == workflow.SENIOR_AUDITOR:
            # The Senior Auditor forwards nothing with a paper still missing or defective: the
            # line must have been named on its pages or waived with grounds (C3).
            _forward_gate_or_422(conn, row)
        elif action in ("RETURN", "REQUEST_DOCS"):
            mirror = "RETURN_FOR_CORRECTION"
            # What exactly the department is asked for (30 Sep 2026): checklist items by id, or a
            # document and pages in the officer's words. Kept item by item (api.rounds), so the
            # next round's verification can say which are now on file.
            payload = {"items": _request_items_or_422(conn, row, body.get("items"))}
        elif action == "REJECT":
            mirror = "RETURN_FOR_CORRECTION"
    try:
        # Everything that can be refused is refused BEFORE the automatic take-up, so a refused
        # decision does not leave the case taken up with an extra history row.
        workflow.check(user.role, workflow.UNDER_REVIEW if row["status"] == workflow.FORWARDED
                       and action in ("APPROVE", "REJECT", "RETURN", "REQUEST_DOCS") else row["status"], action)
        if action in workflow.REMARK_REQUIRED and not remark:
            raise workflow.WorkflowError(422, f"{action.replace('_', ' ').title()} needs a remark")
        if action in ("APPROVE", "REJECT", "RETURN", "REQUEST_DOCS") and row["status"] == workflow.FORWARDED:
            workflow.check_holder(user, row, action)
            take_up_by = user if workflow.tier_of(user.role) == workflow.SENIOR_AUDITOR or user.role in workflow.ANY_TIER else None
            if take_up_by is None:
                raise workflow.WorkflowError(409, "a newly submitted case is with the Senior Auditor")
            workflow.transition(conn, row, "TAKE_UP", take_up_by, remark="", run_id=run_id)
            row = conn.execute("SELECT * FROM cases WHERE id = ?", (row["id"],)).fetchone()
        within = None
        if action == "OVERRIDE":
            # The audit row is written in the override's own transaction: a crash or a refused
            # insert between the two left an override with no audit line (audit 6 Oct 2026, C2).
            def within(c: db.Connection, entry: dict, *, _row=row) -> None:
                workflow.audit(c, actor=user, action="CASE_OVERRIDE", entity_type="case", entity_id=_row["id"],
                               before={"status": _row["status"]}, after={"status": entry["to_status"]},
                               reason=remark, ip=_client_address(request))
        entry = workflow.transition(conn, row, action, user, remark=remark, payload=payload, run_id=run_id,
                                    to_status=body.get("to_status"), within=within)
    except workflow.WorkflowError as exc:
        _raise(exc)
    if mirror and run_id:
        # Keep the old register (api.cases) in agreement with what the AG decided here.
        case_runs.mirror_decision(run_id, mirror, user.display_name,
                                  MIRROR_ROLE_LABELS.get(user.role, "System administrator"),
                                  remark)
    fresh = conn.execute("SELECT * FROM cases WHERE id = ?", (row["id"],)).fetchone()
    # The answer is the case as the screen will show it next, moves included: the screen puts it up
    # before its own reload, and a case without allowed_actions blanked the page (9 Oct 2026).
    answer = _redact(_case_dict(conn, fresh, full=True), user)
    answer["allowed_actions"] = _allowed_actions(conn, user, fresh)
    return {"event": entry, "case": answer}


def _forward_gate_or_422(conn: db.Connection, row: db.Row) -> None:
    """Refuse the Senior Auditor's forward while the current run's checklist has a line MISSING or
    DEFECTIVE that the officer has neither named on its pages nor waived (api.checklist_actions)."""
    from api.artefacts import report_dict
    from api.checklist_actions import current
    from api.runs import ARTIFACTS
    if not row["current_run_id"] or row["current_run_id"].startswith(case_runs.GPF_RUN_PREFIX):
        return                                            # a GP Fund examination has no pension checklist
    run_dir = ARTIFACTS / f"run-{row['current_run_id']}"
    rep = report_dict(run_dir)
    if rep is None:
        return
    items = ((rep.get("checklist") or {}).get("items")) or []
    # The officer's actions in force on the run: a WAIVE or an IDENTIFY on the line, or a document
    # named on its pages for it (the same reading api.checklist_actions.apply lays over the report).
    actions = current(run_dir)
    settled = {k for k, a in actions.items() if a.get("action") in ("WAIVE", "IDENTIFY")}
    settled |= {a.get("item_id") for k, a in actions.items() if k.startswith("name:") and a.get("item_id")}
    open_lines = [i["id"] for i in items if i.get("status") in ("MISSING", "DEFECTIVE") and i["id"] not in settled]
    if open_lines:
        raise HTTPException(422, "the checklist still has a document missing or defective: " + ", ".join(open_lines)
                            + ". Return the case to the department, name the document on its pages, or waive the line with grounds")


@router.post("/cases/{case_id}/forward-tier")
def forward_tier(case_id: str, body: dict = Body(default={}),
                 user: User = Depends(require_roles("AG_SENIOR_AUDITOR", "AG_ASSISTANT_AO", *workflow.ANY_TIER)),
                 conn: db.Connection = Depends(get_conn)) -> dict:
    """Up one tier: Senior Auditor -> Assistant AO -> Accounts Officer (C3). Internal to the AG."""
    return _act(conn, user, case_id, "FORWARD_TIER", body)


@router.post("/cases/{case_id}/return-tier")
def return_tier(case_id: str, body: dict = Body(default={}),
                user: User = Depends(require_roles("AG_ASSISTANT_AO", "AG_AO", *workflow.ANY_TIER)),
                conn: db.Connection = Depends(get_conn)) -> dict:
    """Down one tier, with a remark: AO -> Assistant AO -> Senior Auditor (C3). Internal to the AG."""
    return _act(conn, user, case_id, "RETURN_TIER", body)


@router.post("/cases/{case_id}/forward")
def forward(case_id: str, body: dict = Body(default={}),
            user: User = Depends(require_roles("DEPT_OFFICER")),
            conn: db.Connection = Depends(get_conn)) -> dict:
    return _act(conn, user, case_id, "FORWARD", body)


@router.post("/cases/{case_id}/take-up")
def take_up(case_id: str, body: dict = Body(default={}),
            user: User = Depends(require_roles(*workflow.AG_SIDE)),
            conn: db.Connection = Depends(get_conn)) -> dict:
    return _act(conn, user, case_id, "TAKE_UP", body)


@router.post("/cases/{case_id}/approve")
def approve(case_id: str, body: dict = Body(default={}),
            user: User = Depends(require_roles(*workflow.AG_SIDE)),
            conn: db.Connection = Depends(get_conn)) -> dict:
    return _act(conn, user, case_id, "APPROVE", body)


@router.post("/cases/{case_id}/reject")
def reject(case_id: str, body: dict = Body(default={}),
           user: User = Depends(require_roles(*workflow.AG_SIDE)),
           conn: db.Connection = Depends(get_conn)) -> dict:
    return _act(conn, user, case_id, "REJECT", body)


@router.post("/cases/{case_id}/return")
def return_case(case_id: str, body: dict = Body(default={}),
                user: User = Depends(require_roles(*workflow.AG_SIDE)),
                conn: db.Connection = Depends(get_conn)) -> dict:
    return _act(conn, user, case_id, "RETURN", body)


@router.post("/cases/{case_id}/request-docs")
def request_docs(case_id: str, body: dict = Body(default={}),
                 user: User = Depends(require_roles(*workflow.AG_SIDE)),
                 conn: db.Connection = Depends(get_conn)) -> dict:
    return _act(conn, user, case_id, "REQUEST_DOCS", body)


@router.post("/cases/{case_id}/override")
def override(case_id: str, request: Request, body: dict = Body(...),
             user: User = Depends(require_roles(*workflow.ANY_TIER)),
             conn: db.Connection = Depends(get_conn)) -> dict:
    body = {**body, "remark": body.get("reason") or body.get("remark")}
    return _act(conn, user, case_id, "OVERRIDE", body, request)


# -- the GP Fund module, behind the case's ownership check -------------------------------------

def _gpf_case_or_404(conn: db.Connection, case_id: str, user: User, *, acting: bool = False) -> db.Row:
    row = _case_or_404(conn, case_id, user)
    if row["product"] != "GPF" or not row["gpf_case_id"]:
        raise HTTPException(404, "this GP Fund claim has not been examined yet")
    if acting:
        _gpf_may_act(row)
        # The tier that holds the case acts in the examination; another tier reads it. The AAO
        # and the AO share the module's "ao" band, so without this an Assistant AO could pass a
        # claim for payment while the AO held the case (audit of 12 Oct 2026).
        try:
            workflow.check_holder(user, row, "DISPOSE")
            workflow.check_one_tier_per_case(conn, user, row)
        except workflow.WorkflowError as exc:
            _raise(exc)
    return row


def _gpf_may_act(row: db.Row) -> None:
    """An officer acts on a GP Fund examination only while its case is with the AG for review.

    The portal moves a case on the module's position only from UNDER_REVIEW (case_runs.
    sync_gpf_case), so an action taken in any other status -- "pass for payment" on a case already
    rejected or returned, or on the previous examination while a new one is running -- left the
    module and the portal disagreeing about the same claim (audit 6 Oct 2026).
    """
    if row["status"] != workflow.UNDER_REVIEW:
        raise HTTPException(409, f"case {row['case_no']} is {row['status']}; the GP Fund examination can be "
                                 f"acted on only while the case is under the AG's review")


#: A module route about one examination: /api/cases/<module case id>[/<action or artefact>].
_GPF_CASE_ROUTE = re.compile(r"^/api/cases/([^/]+)(?:/|$)")


def _gpf_after(conn: db.Connection, row: db.Row, user: User, what: str, detail: dict) -> dict:
    """After an officer's action in the examination: the audit line, and the case moved by it
    (passed for payment or nothing open -> approved; returned -> back to the department), exactly
    as when the action was taken in the module's own screen."""
    workflow.audit(conn, actor=user, action=f"GPF_{what.upper()}", entity_type="case", entity_id=row["id"],
                   before=None, after=detail, reason=str(detail.get("ground") or detail.get("note") or ""))
    fresh = _case_or_404(conn, row["id"], user)
    case_runs.sync_gpf_case(conn, fresh)
    fresh = _case_or_404(conn, row["id"], user)
    return {"status": fresh["status"]}


@router.post("/cases/{case_id}/gpf/{action}")
def case_gpf_action(case_id: str, action: str, body: dict = Body(default={}),
                    user: User = Depends(require_roles(*workflow.AG_SIDE)),
                    conn: db.Connection = Depends(get_conn)) -> dict:
    """An officer's action on the GP Fund examination, drawn by the portal (30 Sep 2026):
    verify (a verification task), dispositions (uphold / waive / correct / refer an observation),
    dispose (return / pay / part / refer / hold), sap (an extract pasted as text). Sent to the
    module under the officer's GP Fund identity; the module decides who may do what."""
    row = _gpf_case_or_404(conn, case_id, user, acting=True)
    officer = gpf_bridge.OFFICER_FOR_ROLE.get(user.role, "ao")
    allowed = {"verify": ("vid", "ok", "note"), "dispositions": ("resultId", "action", "ground", "authority"),
               "dispose": ("disposal", "note"), "sap": ("filename", "text")}
    if action not in allowed:
        raise HTTPException(404, f"no GP Fund action {action!r}")
    payload = {k: body[k] for k in allowed[action] if k in body}
    payload["officer"] = officer
    try:
        res = gpf_bridge.act(row["gpf_case_id"], action, payload, acting_name=user.display_name)
    except gpf_bridge.GpfError as exc:
        raise HTTPException(exc.status if 400 <= exc.status < 600 else 502, exc.detail) from None
    return {**res, **_gpf_after(conn, row, user, action, {k: v for k, v in payload.items() if k != "text"})}


@router.post("/cases/{case_id}/gpf-cure")
def case_gpf_cure(case_id: str, resultId: str = Form(...), values: str = Form("{}"),
                        file: UploadFile | None = File(default=None),
                        user: User = Depends(require_roles(*workflow.AG_SIDE)),
                        conn: db.Connection = Depends(get_conn)) -> dict:
    """Cure an examination item by a document or by values, through the module."""
    row = _gpf_case_or_404(conn, case_id, user, acting=True)
    try:
        parsed = json.loads(values or "{}")
    except ValueError:
        raise HTTPException(422, "values must be JSON") from None
    content = None
    if file is not None:
        # Staged to disk with the size limit enforced on the way (N26), as the document routes do,
        # rather than read whole into memory first; the module takes the bytes afterwards.
        staged = _read_uploads([file])
        try:
            content = (staged[0].name, staged[0].path.read_bytes())
        finally:
            _discard_staged(staged)
    try:
        res = gpf_bridge.cure(row["gpf_case_id"], resultId, gpf_bridge.OFFICER_FOR_ROLE.get(user.role, "ao"), parsed, content, acting_name=user.display_name)
    except gpf_bridge.GpfError as exc:
        raise HTTPException(exc.status if 400 <= exc.status < 600 else 502, exc.detail) from None
    return {**res, **_gpf_after(conn, row, user, "cure", {"resultId": resultId, "file": content[0] if content else None})}


@router.get("/cases/{case_id}/gpf-issue-pack")
def case_gpf_issue_pack(case_id: str, user: User = Depends(require_roles(*workflow.AG_READERS)),
                        conn: db.Connection = Depends(get_conn)) -> dict:
    row = _gpf_case_or_404(conn, case_id, user)
    try:
        return gpf_bridge.issue_pack(row["gpf_case_id"])
    except gpf_bridge.GpfError as exc:
        raise HTTPException(exc.status if 400 <= exc.status < 600 else 502, exc.detail) from None


@router.get("/cases/{case_id}/gpf-sap-template")
def case_gpf_sap_template(case_id: str, user: User = Depends(require_roles(*workflow.AG_READERS)),
                          conn: db.Connection = Depends(get_conn)) -> dict:
    row = _gpf_case_or_404(conn, case_id, user)
    try:
        return gpf_bridge.sap_template(row["gpf_case_id"])
    except gpf_bridge.GpfError as exc:
        raise HTTPException(exc.status if 400 <= exc.status < 600 else 502, exc.detail) from None


@router.get("/cases/{case_id}/gpf/pages/{page}")
def case_gpf_page(case_id: str, page: int, user: User = Depends(current_user_q),
                  conn: db.Connection = Depends(get_conn)):
    """One page of the GP Fund claim as the module is reading it (1-based, in reading order), for
    the scanning view (30 Sep 2026). AG only, like the examination itself."""
    import json as _json
    from fastapi.responses import FileResponse
    if user.role not in workflow.AG_READERS:
        raise HTTPException(403, "the GP Fund examination is the Office of the Accountant General's")
    row = _case_or_404(conn, case_id, user)
    work = gpf_bridge.scratch_dir(row["id"], row["submission_no"])
    listing = work / "pages.json"
    if not listing.exists():
        # A claim examined before the page list was kept: render its pages the same way, once.
        docs = [Path(r["stored_path"]) for r in conn.execute(
            "SELECT stored_path FROM case_documents WHERE case_id = ? AND superseded_in_submission IS NULL "
            "ORDER BY submission_no, seq", (row["id"],)) if Path(r["stored_path"]).is_file()]
        if not docs:
            raise HTTPException(404, "no pages have been prepared for this claim yet")
        pages = gpf_bridge.page_images(docs, work)
        listing.write_text(_json.dumps([str(p) for p in pages]))
    pages = _json.loads(listing.read_text())
    if page < 1 or page > len(pages) or not Path(pages[page - 1]).is_file():
        raise HTTPException(404, f"no page {page}")
    # The address carries a token (current_user_q): a cached copy would be a token on disk (F10).
    return FileResponse(pages[page - 1], headers={"Cache-Control": "no-store"})


@router.get("/cases/{case_id}/gpf")
def case_gpf(case_id: str, user: User = Depends(require_roles(*workflow.AG_READERS)),
             conn: db.Connection = Depends(get_conn)) -> dict:
    """What the GP Fund module holds for this case: the reading job while it reads, its case
    afterwards, and the address of its screens for the portal's frame. AG only: the module's
    findings are the Accountant General's."""
    case_runs.sync_run_states(conn)
    row = _case_or_404(conn, case_id, user)
    if row["product"] != "GPF":
        raise HTTPException(404, "not a GP Fund case")
    if case_runs.sync_gpf_case(conn, row):
        row = _case_or_404(conn, case_id, user)
    out: dict[str, Any] = {"status": row["status"], "gpf_case_id": row["gpf_case_id"], "job": None, "case": None,
                           "officer": gpf_bridge.OFFICER_FOR_ROLE.get(user.role, "ao"),
                           "module_up": gpf_bridge.health() is not None}
    run_id = row["current_run_id"] or ""
    if run_id.startswith(case_runs.GPF_RUN_PREFIX) and row["status"] == workflow.AI_CHECKING:
        try:
            out["job"] = gpf_bridge.job(run_id[len(case_runs.GPF_RUN_PREFIX):])
        except gpf_bridge.GpfError as exc:
            out["job"] = {"state": "error", "detail": exc.detail}
    if row["gpf_case_id"]:
        try:
            view = gpf_bridge.case(row["gpf_case_id"])
            out["case"] = {"id": view.get("id"), "version": view.get("version"), "position": view.get("position"),
                           "caseDisp": view.get("caseDisp"), "meta": view.get("meta"),
                           "counts": {k: len(view.get("lists", {}).get(k) or []) for k in ("hard", "adv", "conf", "sap", "ok")}}
            out["embed_url"] = f"/gpf/?embed=1&officer={out['officer']}#/case/{row['gpf_case_id']}"
            # The module's whole view, for the portal's own GP Fund examination screen (30 Sep 2026).
            out["view"] = view
        except gpf_bridge.GpfError as exc:
            out["case"] = {"error": exc.detail}
    return out


# -- run artefacts, behind the case's ownership check -------------------------------------------

def _run_for(conn: db.Connection, user: User, case_id: str, run_id: str, *, acting: bool = False):
    row = _case_or_404(conn, case_id, user)
    if run_id.startswith(case_runs.GPF_RUN_PREFIX):
        raise HTTPException(404, "a GP Fund examination has no pension artefacts; open the GP Fund module's screens")
    if user.role == "DEPT_OFFICER":
        raise HTTPException(403, "the AI findings are read at the Office of the Accountant General; "
                                 "the department is told what is missing when a case is returned")
    if not conn.execute("SELECT 1 FROM case_runs WHERE case_id = ? AND run_id = ?", (row["id"], run_id)).fetchone():
        raise HTTPException(404, "this run does not belong to this case")
    if acting:
        # Findings are cleared on the case's current examination, while it is under review, by
        # the tier that holds the case, by an account that acted at no other tier on it. Until
        # 12 Oct 2026 any AG-side officer who could see the case could waive a HIGH finding on
        # any of its runs while another tier held it, and the Senior Auditor's forward gate
        # trusted those waivers (audit of 12 Oct 2026).
        if row["status"] != workflow.UNDER_REVIEW:
            raise HTTPException(409, "findings can be acted on only while the case is under the Office of the Accountant General's review")
        if run_id != row["current_run_id"]:
            raise HTTPException(409, "this run is not the case's current examination; findings are acted on in the current one")
        try:
            workflow.check_holder(user, row, "DISPOSE")
            workflow.check_one_tier_per_case(conn, user, row)
        except workflow.WorkflowError as exc:
            _raise(exc)
    return get_run(run_id)


@router.get("/cases/{case_id}/runs/{run_id}/report")
def case_report(case_id: str, run_id: str, user: User = Depends(current_user),
                conn: db.Connection = Depends(get_conn)):
    return report(_run_for(conn, user, case_id, run_id))


@router.get("/cases/{case_id}/runs/{run_id}/status")
def case_run_status(case_id: str, run_id: str, user: User = Depends(current_user),
                    conn: db.Connection = Depends(get_conn)) -> dict:
    return status(_run_for(conn, user, case_id, run_id))


@router.get("/cases/{case_id}/runs/{run_id}/bundle")
def case_run_bundle(case_id: str, run_id: str, user: User = Depends(current_user),
                    conn: db.Connection = Depends(get_conn)):
    return run_bundle(_run_for(conn, user, case_id, run_id))


@router.get("/cases/{case_id}/runs/{run_id}/pages/{page}", include_in_schema=False)
def case_page(case_id: str, run_id: str, page: int, user: User = Depends(current_user_q),
              conn: db.Connection = Depends(get_conn)):
    return page_image(_run_for(conn, user, case_id, run_id), page)


@router.get("/cases/{case_id}/runs/{run_id}/signatures/{name}", include_in_schema=False)
def case_signature(case_id: str, run_id: str, name: str, user: User = Depends(current_user_q),
                   conn: db.Connection = Depends(get_conn)):
    return signature_image(_run_for(conn, user, case_id, run_id), name)


@router.get("/cases/{case_id}/runs/{run_id}/events")
async def case_events(case_id: str, run_id: str, request: Request, user: User = Depends(current_user_q),
                      conn: db.Connection = Depends(get_conn)):
    return event_stream(_run_for(conn, user, case_id, run_id), request)


@router.get("/cases/{case_id}/runs/{run_id}/dispositions")
def case_dispositions(case_id: str, run_id: str, user: User = Depends(current_user),
                      conn: db.Connection = Depends(get_conn)) -> dict:
    from api.dispositions import calculation_gate, history, in_force, lapsed
    run = _run_for(conn, user, case_id, run_id)
    rep = report(run)
    rep = rep if isinstance(rep, dict) else {}
    # "current" is what applies to each finding NOW (H8): a disposition follows its finding's
    # fingerprint, and one whose finding changed is listed as lapsed, not applied.
    return {"run_id": run_id, "current": in_force(rep, run.run_dir), "history": history(run.run_dir),
            "lapsed": lapsed(rep, run.run_dir), "gate": calculation_gate(rep, run.run_dir)}


@router.post("/cases/{case_id}/runs/{run_id}/dispositions", status_code=201)
def case_disposition(case_id: str, run_id: str, body: dict = Body(...),
                     user: User = Depends(require_roles(*workflow.AG_SIDE)),
                     conn: db.Connection = Depends(get_conn), request: Request = None) -> dict:
    from api.dispositions import DispositionError, calculation_gate, in_force, record
    run = _run_for(conn, user, case_id, run_id, acting=True)
    rep = report(run)
    if not isinstance(rep, dict):
        raise HTTPException(409, "no case report yet; there are no findings to dispose of")
    flag_id = str(body.get("flag_id", "")).strip()
    flag = next((f for f in rep.get("flags", []) if f.get("id") == flag_id), None)
    if flag is None:
        raise HTTPException(404, f"this case has no finding {flag_id!r}")
    try:
        entry = record(run.run_dir, run_id=run_id, flag_id=flag_id, action=str(body.get("action", "")),
                       officer=user.display_name, role="ACCOUNTS_OFFICE",
                       ground=str(body.get("ground", "")), flag=flag)
    except DispositionError as exc:
        raise HTTPException(422, str(exc)) from None
    _audit_clearance(conn, user, request, case_id, run_id, f"FINDING_{entry.get('action', '')}", entry)
    from api.checklist_actions import apply
    gate = calculation_gate(apply(rep, run.run_dir), run.run_dir)
    settled = _settle(conn, case_id, user, run_id, gate)
    return {**entry, "gate": gate, "current": in_force(rep, run.run_dir), **({"case": settled} if settled else {})}


def _audit_clearance(conn: db.Connection, user: User, request: Request | None, case_id: str,
                     run_id: str, action: str, entry: dict) -> None:
    """An officer's waiver, correction or checklist action, on the append-only audit trail.

    These decide what is outstanding on a case, and they were kept only in the run folder's
    .jsonl files, under a display name and a fixed role: no account id, no address, and
    editable by anyone with the files (audit 6 Oct 2026). The run folder keeps its copy."""
    case = conn.execute("SELECT id FROM cases WHERE id = ? OR case_no = ?", (case_id, case_id)).fetchone()
    detail = {k: v for k, v in entry.items() if k not in ("officer", "role", "at")}
    workflow.audit(conn, actor=user, action=action.upper(), entity_type="case",
                   entity_id=case["id"] if case else case_id, before=None, after={"run_id": run_id, **detail},
                   reason=str(entry.get("ground") or ""), ip=_client_address(request) if request else None)


def _settle(conn: db.Connection, case_id: str, user: User, run_id: str, gate: dict) -> dict | None:
    """Clearing the last finding (or the last missing paper) is recorded; the case is not moved
    (business decision M1, 7 Oct 2026: no automatic approval). Returns None."""
    # By id or case number, as _case_or_404 accepts: a clearance sent with the case number
    # never approved the case before (audit 6 Oct 2026).
    row = conn.execute("SELECT * FROM cases WHERE id = ? OR case_no = ?", (case_id, case_id)).fetchone()
    if row is None or not case_runs.settle(conn, row, run_id, gate, user.display_name, by=user):
        return None
    fresh = conn.execute("SELECT * FROM cases WHERE id = ?", (row["id"],)).fetchone()
    return _redact(_case_dict(conn, fresh, full=True), user)


@router.get("/cases/{case_id}/runs/{run_id}/checklist-actions")
def case_checklist_actions(case_id: str, run_id: str, user: User = Depends(current_user),
                           conn: db.Connection = Depends(get_conn)) -> dict:
    from api import checklist_actions
    run = _run_for(conn, user, case_id, run_id)
    return {"run_id": run_id, "history": checklist_actions.history(run.run_dir),
            "current": checklist_actions.current(run.run_dir)}


@router.post("/cases/{case_id}/runs/{run_id}/checklist-actions", status_code=201)
def case_checklist_action(case_id: str, run_id: str, body: dict = Body(...),
                          user: User = Depends(require_roles(*workflow.AG_SIDE)),
                          conn: db.Connection = Depends(get_conn), request: Request = None) -> dict:
    from api import checklist_actions
    from api.artefacts import report_dict
    from api.dispositions import calculation_gate
    run = _run_for(conn, user, case_id, run_id, acting=True)
    rep = report_dict(run.run_dir)
    if rep is None:
        raise HTTPException(409, "no case report yet; there is no checklist to act on")
    try:
        entry = checklist_actions.record(
            run.run_dir, run_id=run_id, report=rep, action=str(body.get("action", "")),
            officer=user.display_name, role="ACCOUNTS_OFFICE",
            item_id=(str(body["item_id"]) if body.get("item_id") else None),
            pages=body.get("pages") or [], document_name=str(body.get("document_name", "")),
            ground=str(body.get("ground", "")),
            name_id=(str(body["name_id"]) if body.get("name_id") else None))
    except checklist_actions.ChecklistActionError as exc:
        raise HTTPException(422, str(exc)) from None
    _audit_clearance(conn, user, request, case_id, run_id, f"CHECKLIST_{entry.get('action', '')}", entry)
    applied = checklist_actions.apply(rep, run.run_dir)
    gate = calculation_gate(applied, run.run_dir)
    settled = _settle(conn, case_id, user, run_id, gate)
    from rules.scope import scrub_report
    return {**entry, "report": scrub_report(applied), "gate": gate, **({"case": settled} if settled else {})}


# -- the same artefacts, keyed by run id alone -----------------------------------------------
# The shared screens (page viewer, live analysis, findings) were written around a run id. A
# run belongs to exactly one case, so the server looks the case up and applies the same scope
# check; nothing is reachable this way that the case-keyed routes would refuse.

def _run_by_id(conn: db.Connection, user: User, run_id: str):
    link = conn.execute("SELECT case_id FROM case_runs WHERE run_id = ? "
                        "ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1", (run_id,)).fetchone()
    if link is None:
        raise HTTPException(404, "no such run")
    return _run_for(conn, user, link["case_id"], run_id)


@router.get("/runs/{run_id}/report")
def run_report_by_id(run_id: str, user: User = Depends(current_user), conn: db.Connection = Depends(get_conn)):
    return report(_run_by_id(conn, user, run_id))


@router.get("/runs/{run_id}/status")
def run_status_by_id(run_id: str, user: User = Depends(current_user), conn: db.Connection = Depends(get_conn)) -> dict:
    return status(_run_by_id(conn, user, run_id))


@router.get("/runs/{run_id}/pages/{page}", include_in_schema=False)
def run_page_by_id(run_id: str, page: int, user: User = Depends(current_user_q), conn: db.Connection = Depends(get_conn)):
    return page_image(_run_by_id(conn, user, run_id), page)


@router.get("/runs/{run_id}/signatures/{name}", include_in_schema=False)
def run_signature_by_id(run_id: str, name: str, user: User = Depends(current_user_q), conn: db.Connection = Depends(get_conn)):
    return signature_image(_run_by_id(conn, user, run_id), name)


@router.get("/runs/{run_id}/events")
async def run_events_by_id(run_id: str, request: Request, user: User = Depends(current_user_q),
                           conn: db.Connection = Depends(get_conn)):
    return event_stream(_run_by_id(conn, user, run_id), request)


@router.get("/runs/{run_id}/dispositions")
def run_dispositions_by_id(run_id: str, user: User = Depends(current_user), conn: db.Connection = Depends(get_conn)) -> dict:
    link = conn.execute("SELECT case_id FROM case_runs WHERE run_id = ? "
                        "ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1", (run_id,)).fetchone()
    if link is None:
        raise HTTPException(404, "no such run")
    return case_dispositions(link["case_id"], run_id, user, conn)


@router.post("/runs/{run_id}/dispositions", status_code=201)
def run_disposition_by_id(run_id: str, request: Request, body: dict = Body(...),
                          user: User = Depends(require_roles(*workflow.AG_SIDE)),
                          conn: db.Connection = Depends(get_conn)) -> dict:
    link = conn.execute("SELECT case_id FROM case_runs WHERE run_id = ? "
                        "ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1", (run_id,)).fetchone()
    if link is None:
        raise HTTPException(404, "no such run")
    return case_disposition(link["case_id"], run_id, body, user, conn, request)


@router.get("/runs/{run_id}/checklist-actions")
def run_checklist_by_id(run_id: str, user: User = Depends(current_user), conn: db.Connection = Depends(get_conn)) -> dict:
    link = conn.execute("SELECT case_id FROM case_runs WHERE run_id = ? "
                        "ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1", (run_id,)).fetchone()
    if link is None:
        raise HTTPException(404, "no such run")
    return case_checklist_actions(link["case_id"], run_id, user, conn)


@router.post("/runs/{run_id}/checklist-actions", status_code=201)
def run_checklist_action_by_id(run_id: str, request: Request, body: dict = Body(...),
                               user: User = Depends(require_roles(*workflow.AG_SIDE)),
                               conn: db.Connection = Depends(get_conn)) -> dict:
    link = conn.execute("SELECT case_id FROM case_runs WHERE run_id = ? "
                        "ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1", (run_id,)).fetchone()
    if link is None:
        raise HTTPException(404, "no such run")
    return case_checklist_action(link["case_id"], run_id, body, user, conn, request)


# -- admin -------------------------------------------------------------------------------------

def _user_row(conn: db.Connection, user_id: str) -> db.Row:
    row = conn.execute("SELECT * FROM users WHERE id = ? OR username = ?", (user_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(404, "no such user")
    return row


def _public_user(row: db.Row) -> dict:
    d = {k: row[k] for k in row.keys() if k != "password_hash"}
    d["active"] = bool(row["active"])
    d["portal"] = portal_for(row["role"], row["department_code"])
    return d


@router.get("/admin/users")
def list_users(role: str | None = None, pension_wing: str | None = None, user: User = Depends(require_roles("ADMIN")),
               conn: db.Connection = Depends(get_conn)) -> list[dict]:
    """Every account, narrowed by role and pension wing where asked (C4)."""
    where, args = ["1 = 1"], []
    if role:
        where.append("role = ?"); args.append(role)
    if pension_wing:
        where.append("pension_wing = ?"); args.append(pension_wing)
    return [_public_user(r) for r in conn.execute(f"SELECT * FROM users WHERE {' AND '.join(where)} ORDER BY role, username", args)]


def _wing_or_422(role: str, wing: str | None, dept: str | None, conn: db.Connection) -> tuple[str | None, str | None]:
    """The (department, wing) pair an account of this role may carry (C4, defaults Q4/Q5): a tier
    officer has a wing and no department; a DDO a department and no wing; the Deputy AG, the
    administrator and the legacy reviewer neither. A wing is not a department."""
    wing = (wing or "").strip() or None
    dept = (dept or "").strip() or None
    if role in TIER_ROLES:
        if wing not in PENSION_SECTION_ORDER:
            raise HTTPException(422, f"a {workflow.TIER_LABELS[workflow.tier_of(role)]} belongs to a pension wing: one of {', '.join(PENSION_SECTION_ORDER)}")
        if dept:
            raise HTTPException(422, "a wing officer has no department; the wing covers its departments")
        return None, wing
    if role == "DEPT_OFFICER":
        if wing:
            raise HTTPException(422, "a DDO belongs to a department, not to a pension wing")
        if not dept or not conn.execute("SELECT 1 FROM departments WHERE code = ? AND active = 1 AND code != ?",
                                        (dept, LEGACY_DEPARTMENT[0])).fetchone():
            raise HTTPException(422, "a DDO account needs an active department")
        return dept, None
    if wing or dept:
        raise HTTPException(422, f"a {workflow.TIER_LABELS.get(role, role.replace('_', ' ').lower())} takes neither a department nor a wing"
                            if role in workflow.TIER_LABELS else "this role takes neither a department nor a wing")
    return None, None


@router.get("/admin/wing-coverage")
def wing_coverage(user: User = Depends(require_roles("ADMIN")), conn: db.Connection = Depends(get_conn)) -> dict:
    """Per pension wing, how many active officers each tier has, and the tiers with none -- a wing
    with a gap stops its cases at that tier (C4)."""
    counts = {w: {t: 0 for t in workflow.TIERS} for w in PENSION_SECTION_ORDER}
    for r in conn.execute("SELECT pension_wing, role, COUNT(*) n FROM users WHERE active = 1 AND pension_wing IS NOT NULL "
                          "GROUP BY pension_wing, role"):
        tier = workflow.tier_of(r["role"])
        if tier and r["pension_wing"] in counts:
            counts[r["pension_wing"]][tier] = int(r["n"])
    wings = [{"wing": w, "tiers": c, "gaps": [t for t in workflow.TIERS if not c[t]]} for w, c in counts.items()]
    return {"wings": wings, "tier_labels": workflow.TIER_LABELS,
            "gaps": [{"wing": w["wing"], "tier": t} for w in wings for t in w["gaps"]],
            "deputy_ag": conn.execute("SELECT COUNT(*) FROM users WHERE active = 1 AND role = 'AG_DAG'").fetchone()[0]}


@router.post("/admin/users", status_code=201)
def create_user(request: Request, body: dict = Body(...), user: User = Depends(require_roles("ADMIN")),
                conn: db.Connection = Depends(get_conn)) -> dict:
    username = str(body.get("username", "")).strip().lower()
    role = str(body.get("role", ""))
    dept = (body.get("department_code") or None)
    password = str(body.get("password", ""))
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
        raise HTTPException(422, "username: 3-40 characters, letters, digits, . _ -")
    if role not in CREATABLE_ROLES:
        raise HTTPException(422, f"role must be one of {list(CREATABLE_ROLES)}")
    if username in SHARED_LOGINS and settings.production():
        raise HTTPException(422, "a login carries the officer's own name (decision C1)")
    dept, wing = _wing_or_422(role, body.get("pension_wing"), dept, conn)
    problem = password_problem(password, username)
    if problem:
        raise HTTPException(422, f"password: {problem}")
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        raise HTTPException(409, "that username is taken")
    now = db.now()
    uid = db.new_id()
    with db.transaction(conn):
        # A password the administrator chose is the administrator's; the officer replaces it at
        # first sign-in where the deployment asks for that (api.settings: production).
        conn.execute("INSERT INTO users(id, username, display_name, password_hash, role, department_code, pension_wing, "
                     "active, token_version, must_change_password, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?)",
                     (uid, username, str(body.get("display_name") or username), hash_password(password),
                      role, dept, wing, int(settings.force_password_change()), now, now))
        workflow.audit(conn, actor=user, action="USER_CREATE", entity_type="user", entity_id=uid, ip=_client_address(request),
                       before=None, after={"username": username, "role": role, "department_code": dept, "pension_wing": wing})
    return _public_user(_user_row(conn, uid))


@router.post("/admin/users/{user_id}/role")
def set_user_role(request: Request, user_id: str, body: dict = Body(...), user: User = Depends(require_roles("ADMIN")),
                  conn: db.Connection = Depends(get_conn)) -> dict:
    """Give an AG account its tier and wing (C4): the way an officer moves between tiers or wings,
    or an AG-desk account becomes a tier officer. A DDO stays a DDO
    (a department's account is not turned into an AG one). Every session of the account ends.
    Audited with before and after and a reason."""
    row = _user_row(conn, user_id)
    role = str(body.get("role", ""))
    if row["role"] == "DEPT_OFFICER" or role == "DEPT_OFFICER":
        raise HTTPException(422, "a DDO account is a department's; create the officer an AG account instead")
    if role not in CREATABLE_ROLES or role == "ADMIN":
        raise HTTPException(422, "role must be a tier (AG_SENIOR_AUDITOR, AG_ASSISTANT_AO, AG_AO), AG_DAG or AG_REVIEWER")
    if row["id"] == user.id:
        raise HTTPException(409, "you cannot change your own role")
    reason = " ".join(str(body.get("reason") or "").split())
    if len(reason) < MIN_RESET_REASON:
        raise HTTPException(422, f"a role change needs a reason of at least {MIN_RESET_REASON} characters")
    _, wing = _wing_or_422(role, body.get("pension_wing"), None, conn)
    with db.transaction(conn):
        conn.execute("UPDATE users SET role = ?, pension_wing = ?, department_code = NULL, token_version = token_version + 1, "
                     "updated_at = ? WHERE id = ?", (role, wing, db.now(), row["id"]))
        workflow.audit(conn, actor=user, action="USER_ROLE_CHANGE", entity_type="user", entity_id=row["id"], ip=_client_address(request),
                       before={"role": row["role"], "pension_wing": row["pension_wing"] if "pension_wing" in row.keys() else None},
                       after={"role": role, "pension_wing": wing}, reason=reason)
    return _public_user(_user_row(conn, row["id"]))


@router.post("/admin/users/{user_id}/username")
def set_username(request: Request, user_id: str, body: dict = Body(...), user: User = Depends(require_roles("ADMIN")),
                 conn: db.Connection = Depends(get_conn)) -> dict:
    """Rename an account (23 Oct 2026): the office mistypes a login, or an officer's name is
    recorded wrongly and the login carries it (decision C1, a login is the officer's own name).

    The account's history does not move with it. Every case event, every audit entry and every
    signature names the account by its id, and the display name is a separate column, so what
    changes is the word the officer types to sign in and nothing else -- an old case still
    reads as the work of the same person.

    Every session of the account ends, as a role change and a password reset end them. It is
    not optional here: the token names the account the officer signed in as, and leaving a
    session open under a username that no longer exists is a session nobody can account for.

    An administrator may rename their own account. Renaming is not a privilege change -- which
    is what the self-checks on role and disable are guarding -- and the cost of being wrong is
    signing in again under the name you just chose. The audit entry names the actor either way.
    """
    row = _user_row(conn, user_id)
    username = str(body.get("username", "")).strip().lower()
    was = row["username"]
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
        raise HTTPException(422, "username: 3-40 characters, letters, digits, . _ -")
    if username == was:
        raise HTTPException(422, "that is the username the account already has")
    if username in SHARED_LOGINS and settings.production():
        raise HTTPException(422, "a login carries the officer's own name (decision C1)")
    reason = " ".join(str(body.get("reason") or "").split())
    if len(reason) < MIN_RESET_REASON:
        raise HTTPException(422, f"a rename needs a reason of at least {MIN_RESET_REASON} characters")
    if conn.execute("SELECT 1 FROM users WHERE username = ? AND id <> ?", (username, row["id"])).fetchone():
        raise HTTPException(409, "that username is taken")
    with db.transaction(conn):
        conn.execute("UPDATE users SET username = ?, token_version = token_version + 1, updated_at = ? WHERE id = ?",
                     (username, db.now(), row["id"]))
        workflow.audit(conn, actor=user, action="USER_RENAME", entity_type="user", entity_id=row["id"],
                       ip=_client_address(request), before={"username": was}, after={"username": username},
                       reason=reason)
    return _public_user(_user_row(conn, row["id"]))


@router.post("/admin/users/{user_id}/disable")
def disable_user(request: Request, user_id: str, body: dict = Body(default={}), user: User = Depends(require_roles("ADMIN")),
                 conn: db.Connection = Depends(get_conn)) -> dict:
    row = _user_row(conn, user_id)
    if row["id"] == user.id:
        raise HTTPException(409, "you cannot disable your own account")
    with db.transaction(conn):
        conn.execute("UPDATE users SET active = 0, token_version = token_version + 1, updated_at = ? WHERE id = ?",
                     (db.now(), row["id"]))
        workflow.audit(conn, actor=user, action="USER_DISABLE", entity_type="user", entity_id=row["id"], ip=_client_address(request),
                       before={"active": bool(row["active"])}, after={"active": False},
                       reason=str(body.get("reason") or ""))
    return _public_user(_user_row(conn, row["id"]))


@router.post("/admin/users/{user_id}/enable")
def enable_user(request: Request, user_id: str, user: User = Depends(require_roles("ADMIN")),
                conn: db.Connection = Depends(get_conn)) -> dict:
    row = _user_row(conn, user_id)
    # An account disabled during the trial comes back with the trial's password. In production
    # that password is replaced at the next sign-in, as every seeded or reset one is (F1); the
    # start-up sweep only sees accounts that are active when the API starts (audit 6 Oct 2026, L4).
    must_change = 1 if settings.production() else int(row["must_change_password"] or 0)
    with db.transaction(conn):
        conn.execute("UPDATE users SET active = 1, must_change_password = ?, updated_at = ? WHERE id = ?",
                     (must_change, db.now(), row["id"]))
        workflow.audit(conn, actor=user, action="USER_ENABLE", entity_type="user", entity_id=row["id"], ip=_client_address(request),
                       before={"active": bool(row["active"])},
                       after={"active": True, "must_change_password": bool(must_change)})
    return _public_user(_user_row(conn, row["id"]))


@router.post("/admin/users/{user_id}/reset-password")
def reset_user_password(request: Request, user_id: str, body: dict = Body(...), user: User = Depends(require_roles("ADMIN")),
                        conn: db.Connection = Depends(get_conn)) -> dict:
    row = _user_row(conn, user_id)
    password = str(body.get("password", ""))
    problem = password_problem(password, row["username"])
    if problem:
        raise HTTPException(422, f"password: {problem}")
    reason = " ".join(str(body.get("reason") or "").split())
    if len(reason) < MIN_RESET_REASON:
        # The one remaining way to act as another officer is written down every time (N25).
        raise HTTPException(422, f"a password reset needs a reason of at least {MIN_RESET_REASON} characters")
    with db.transaction(conn):
        conn.execute("UPDATE users SET password_hash = ?, token_version = token_version + 1, "
                     "must_change_password = ?, updated_at = ? WHERE id = ?",
                     (hash_password(password), int(settings.force_password_change()), db.now(), row["id"]))
        workflow.audit(conn, actor=user, action="USER_RESET_PASSWORD", entity_type="user", ip=_client_address(request),
                       entity_id=row["id"], before=None, after=None, reason=reason)
    return {"ok": True}


@router.get("/admin/audit-log")
def audit_log(since: str | None = None, actor: str | None = None, limit: int = 200,
              user: User = Depends(require_roles("ADMIN")),
              conn: db.Connection = Depends(get_conn)) -> list[dict]:
    where, args = [], []
    if since:
        where.append("at >= ?"); args.append(since)
    if actor:
        where.append("(actor_id = ? OR actor_name LIKE ?)"); args.extend([actor, f"%{actor}%"])
    sql = ("SELECT * FROM audit_log" + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY at DESC LIMIT ?")
    args.append(max(1, min(int(limit), 1000)))
    out = []
    for r in conn.execute(sql, args):
        d = dict(r)
        # Stored to the microsecond so the order holds (workflow.audit); shown to the second, as always.
        d["at"] = (d["at"] or "")[:19]
        d["before"] = json.loads(d.pop("before_json") or "null")
        d["after"] = json.loads(d.pop("after_json") or "null")
        out.append(d)
    return out


@router.get("/admin/credentials", include_in_schema=False)
def admin_credentials(request: Request, user: User = Depends(current_user), conn: db.Connection = Depends(get_conn)):
    """The office's sign-in sheet (plain-text passwords), for the administrator only.

    Never served by the portals as a file; reachable here with an administrator's token in the
    Authorization header only -- not on the URL, where it would stay in a browser's history.
    Every read is entered in the audit log.
    """
    from fastapi.responses import HTMLResponse
    if user.role != "ADMIN":
        raise HTTPException(403, "only the administrator may read the credentials sheet")
    if settings.production():
        # Plaintext passwords over the web are the trial's convenience. In production the sheet
        # is read on the server itself and removed with `python3 -m api.db forget-credentials`.
        raise HTTPException(404, "the credentials sheet is not served in production")
    path = db.render_credentials_html()
    workflow.audit(conn, actor=user, action="CREDENTIALS_VIEWED", entity_type="file", entity_id="credentials-sheet",
                   before=None, after=None, ip=_client_address(request))
    return HTMLResponse(path.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/admin/overview")
def overview(user: User = Depends(require_roles("ADMIN")), conn: db.Connection = Depends(get_conn)) -> dict:
    case_runs.sync_run_states(conn)
    by_status = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM cases GROUP BY status")}
    return {"cases": sum(by_status.values()), "by_status": by_status,
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "departments": conn.execute("SELECT COUNT(*) FROM departments WHERE active = 1").fetchone()[0],
            "audit_entries": conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]}
