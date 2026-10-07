#!/usr/bin/env python3
"""End-to-end pass over the live stack: the main flows with real AI checks, plus isolation.

    python3 portals/e2e.py <dept-a.pdf> <dept-b.pdf> <dept-c.pdf> [<extra document for the resubmission>]

Signs in the way the portals do -- through each department's own port, so the portal server's
X-Portal header and the backend's portal rule are both exercised -- with the passwords from
artifacts/credentials/credentials.csv. Each AI check is the real pipeline (10-20 minutes a
case), so the whole pass takes about an hour. Prints one line per step and a tally; exit 0 only
if every step passed.

Flows:  1. Punjab Police files → AI check → forwards → AG takes up → approves; Police sees the remark.
        2. School Education files → forwards → AG returns → adds a document → re-checks → re-forwards.
        3. Agriculture files → forwards → AG requests documents → Agriculture uploads → re-checks → re-forwards.
        4. Admin overrides the approved Police case with a reason → audit log.
        5. Isolation: a department at another department's port, a department at the AG port, the AG at a
           department port → 403; a department cannot list, open, add to or forward another's case;
           the old /api routes need a token.
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CREDS = ROOT / "artifacts" / "credentials" / "credentials.csv"
HOST = "127.0.0.1"
AG_PORT = 5184
results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, note: str = "") -> None:
    results.append((name, ok, note))
    print(f"[{time.strftime('%H:%M:%S')}] {'PASS' if ok else 'FAIL'}  {name}{' — ' + note if note else ''}", flush=True)


def passwords() -> dict[str, str]:
    out: dict[str, str] = {}
    with open(CREDS, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            out[r["username"]] = r["password"]           # the newest row per username wins
    return out


def call(port: int, method: str, path: str, token: str | None = None, json_body: dict | None = None,
         files: list[tuple[str, str, bytes]] | None = None, fields: dict | None = None, headers: dict | None = None):
    headers = dict(headers or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if files is not None:
        boundary = "----e2e" + str(int(time.time() * 1000))
        body = b""
        for k, v in (fields or {}).items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for field, name, blob in files:
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{name}\"\r\n"
                     f"Content-Type: application/octet-stream\r\n\r\n").encode() + blob + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        data = body
    elif json_body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(json_body).encode()
    req = urllib.request.Request(f"http://{HOST}:{port}{path}", data=data, headers=headers, method=method)
    for attempt in range(6):                         # a portal-server restart is a few seconds' blip
        try:
            return _send(req)
        except urllib.error.URLError as exc:
            if attempt == 5 or not isinstance(getattr(exc, "reason", None), ConnectionRefusedError):
                raise
            time.sleep(3)


def _send(req):
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            text = r.read().decode()
            try:
                return r.status, (json.loads(text) if text else None)
            except ValueError:
                return r.status, text                         # an HTML page, not JSON
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, text


def portals() -> dict[str, int]:
    code, body = call(AG_PORT, "GET", "/api/v2/portals")
    assert code == 200, body
    ports = {d["slug"]: d["port"] for d in body["departments"]}
    ports["__single__"] = bool(body.get("single_portal"))
    return ports


def login(port: int, user: str, pw: dict[str, str]) -> tuple[int, str | None]:
    code, body = call(port, "POST", "/api/v2/auth/login", json_body={"username": user, "password": pw[user]})
    return code, (body["token"] if code == 200 else None)


def wait_status(port: int, token: str, case_id: str, wanted: set[str], limit_s: int = 40 * 60) -> dict:
    t0 = time.time()
    last = None
    while time.time() - t0 < limit_s:
        code, c = call(port, "GET", f"/api/v2/cases/{case_id}", token)
        assert code == 200, (code, c)
        if c["status"] != last:
            print(f"    {c['case_no']} → {c['status']}  ({int(time.time() - t0)} s)", flush=True)
            last = c["status"]
        if c["status"] in wanted:
            return c
        time.sleep(10)
    raise TimeoutError(f"{case_id} still {last} after {limit_s} s")


def main(argv: list[str]) -> int:
    pdf_a, pdf_b, pdf_c = argv[1], argv[2], argv[3]
    extra = argv[4] if len(argv) > 4 else argv[2]
    read = lambda p: open(p, "rb").read()
    pw = passwords()
    ports = portals()
    single = ports.pop("__single__", False)
    if single:                                       # one address for everyone (25 Sep 2026)
        P = E = A = AG_PORT
        step("one portal on :5184 for every account", True, "single-portal mode")
        code, _ = call(8110, "POST", "/api/v2/auth/login", json_body={"username": "punjab-police", "password": pw["punjab-police"]},
                       headers={"X-Portal": "school-education"})
        step("a department slug as portal is still refused by the backend", code == 403, f"HTTP {code}")
    else:
        P, E, A = ports["punjab-police"], ports["school-education"], ports["agriculture"]
        step("portal server lists every department port", len(ports) == 86, f"{len(ports)} ports")
        code, _ = login(E, "punjab-police", pw)
        step("Police officer refused at the School Education port", code == 403, f"HTTP {code}")
        code, _ = login(AG_PORT, "punjab-police", pw)
        step("Police officer refused at the AG port", code == 403, f"HTTP {code}")
        code, _ = login(P, "syed.haider", pw)
        step("AG reviewer refused at a department port", code == 403, f"HTTP {code}")
    code, police = login(P, "punjab-police", pw)
    step("Police officer admitted", code == 200 and police is not None, f"HTTP {code}")
    _, edu = login(E, "school-education", pw)
    _, agri = login(A, "agriculture", pw)
    _, rev = login(AG_PORT, "syed.haider", pw)
    _, adm = login(AG_PORT, "admin", pw)
    step("Education, Agriculture, reviewer and admin admitted at their own ports", all([edu, agri, rev, adm]))
    code, _ = call(AG_PORT, "GET", "/api/cases")
    step("old /api routes need a token", code == 401, f"HTTP {code}")
    code, _ = call(AG_PORT, "GET", "/api/v2/cases")
    step("no token → 401", code == 401, f"HTTP {code}")
    code, html = call(A, "GET", "/")
    want = '"slug": "ag"' if single else '"slug": "agriculture"'
    step("the portal page knows which portal it is", code == 200 and want in str(html), f"HTTP {code}")

    # 1. Police files (and 3. Agriculture files now, so the GPU work overlaps the polling)
    code, made = call(P, "POST", "/api/v2/cases", police, files=[("files", "case.pdf", read(pdf_a))])
    step("Police files a case and the AI check starts", code == 201 and "check" in made, f"HTTP {code} {made.get('check_error', '') if isinstance(made, dict) else ''}")
    pc = made["case"]["id"]
    code, made3 = call(A, "POST", "/api/v2/cases", agri, files=[("files", "case.pdf", read(pdf_c))])
    step("Agriculture files a case", code == 201, f"HTTP {code}")
    ac = made3["case"]["id"]

    # isolation on the case itself
    code, _ = call(E, "GET", f"/api/v2/cases/{pc}", edu)
    step("Education cannot open the Police case", code == 403, f"HTTP {code}")
    code, _ = call(E, "POST", f"/api/v2/cases/{pc}/forward", edu, json_body={"remark": "x"})
    step("Education cannot forward the Police case", code == 403, f"HTTP {code}")
    code, _ = call(E, "POST", f"/api/v2/cases/{pc}/documents", edu, files=[("files", "x.pdf", read(extra))])
    step("Education cannot add documents to the Police case", code == 403, f"HTTP {code}")
    code, mine = call(E, "GET", "/api/v2/cases", edu)
    step("Education's register does not list the Police or Agriculture cases", not any(c["id"] in (pc, ac) for c in mine))
    code, _ = call(E, "GET", f"/api/v2/cases/{pc}", police)
    step("a Police token used at the Education port is still scoped to Police cases", code == 200, f"HTTP {code}")

    c = wait_status(P, police, pc, {"AI_CHECKED", "AI_FAILED"})
    step("Police case AI check finished", c["status"] == "AI_CHECKED",
         f"{c['latest_run']['verdict']} · {c['latest_run']['high_flags']} HIGH" if c["latest_run"] else "")
    code, r = call(P, "POST", f"/api/v2/cases/{pc}/forward", police, json_body={"remark": "Submitted for AG review; the department has verified the papers by hand."})
    step("Police submits to the AG", code == 200 and r["case"]["status"] == "FORWARDED", f"HTTP {code}")
    code, counts = call(AG_PORT, "GET", "/api/v2/departments/counts", rev)
    pol = next((x for x in counts if x["code"] == "PUNJAB_POLICE"), {})
    step("AG Review counts it under Punjab Police", pol.get("awaiting_review", 0) >= 1, f"awaiting {pol.get('awaiting_review')}")
    names = [x["name"] for x in counts]
    step("AG Review sidebar order is alphabetical", names == sorted(names, key=str.lower))
    code, r = call(AG_PORT, "POST", f"/api/v2/cases/{pc}/take-up", rev)
    step("AG takes it up", code == 200 and r["case"]["status"] == "UNDER_REVIEW", f"HTTP {code}")
    code, r = call(AG_PORT, "POST", f"/api/v2/cases/{pc}/approve", rev, json_body={"remark": "Papers in order; findings reviewed against the pages and accepted."})
    step("AG approves", code == 200 and r["case"]["status"] == "APPROVED", f"HTTP {code} {r if code != 200 else ''}")
    code, c = call(P, "GET", f"/api/v2/cases/{pc}", police)
    step("Police sees APPROVED and the AG remark", c["status"] == "APPROVED" and any("in order" in e["remark"].lower() for e in c["events"]))

    # 4. Admin override
    code, r = call(AG_PORT, "POST", f"/api/v2/cases/{pc}/override", adm, json_body={"to_status": "RETURNED"})
    step("override without a reason refused", code == 422, f"HTTP {code}")
    code, r = call(AG_PORT, "POST", f"/api/v2/cases/{pc}/override", adm, json_body={"to_status": "RETURNED", "reason": "E2E: approval recorded on the wrong file; sent back."})
    step("Admin overrides APPROVED → RETURNED", code == 200 and r["case"]["status"] == "RETURNED", f"HTTP {code}")
    code, log = call(AG_PORT, "GET", "/api/v2/admin/audit-log", adm)
    step("override is in the audit log", code == 200 and log and log[0]["action"] == "CASE_OVERRIDE" and log[0]["before"] == {"status": "APPROVED"})

    # 3. Agriculture: document request and resubmission
    c = wait_status(A, agri, ac, {"AI_CHECKED", "AI_FAILED"})
    step("Agriculture case AI check finished", c["status"] == "AI_CHECKED")
    first_run_a = c["latest_run"]["run_id"]
    code, r = call(A, "POST", f"/api/v2/cases/{ac}/forward", agri, json_body={"remark": "E2E: submitted as filed."})
    step("Agriculture submits", code == 200, f"HTTP {code}")
    code, r = call(AG_PORT, "POST", f"/api/v2/cases/{ac}/request-docs", rev, json_body={"remark": "Attach the attested death certificate."})
    step("AG requests documents", code == 200 and r["case"]["status"] == "DOCS_REQUESTED", f"HTTP {code}")
    code, mine = call(A, "GET", "/api/v2/cases", agri)
    step("…and it is back on Agriculture's register, nowhere else", any(x["id"] == ac and x["status"] == "DOCS_REQUESTED" for x in mine))
    code, r = call(A, "POST", f"/api/v2/cases/{ac}/documents", agri, files=[("files", "death-certificate.pdf", read(extra))])
    step("Agriculture uploads the requested document (submission 2, back to draft)", code == 201 and r["submission_no"] == 2 and r["status"] == "DRAFT", f"HTTP {code}")
    code, r = call(A, "POST", f"/api/v2/cases/{ac}/check", agri)
    step("re-check started with a new run id", code == 202 and r["run_id"] != first_run_a, f"HTTP {code}")
    c = wait_status(A, agri, ac, {"AI_CHECKED", "AI_FAILED"})
    step("Agriculture re-check finished", c["status"] == "AI_CHECKED")
    code, r = call(A, "POST", f"/api/v2/cases/{ac}/forward", agri, json_body={"remark": "Death certificate attached; resubmitted."})
    step("Agriculture re-submits", code == 200 and r["case"]["status"] == "FORWARDED", f"HTTP {code}")

    # 2. Education: return and resubmit
    code, made2 = call(E, "POST", "/api/v2/cases", edu, files=[("files", "case.pdf", read(pdf_b))])
    step("Education files a case", code == 201, f"HTTP {code}")
    ec = made2["case"]["id"]
    c = wait_status(E, edu, ec, {"AI_CHECKED", "AI_FAILED"})
    step("Education case AI check finished", c["status"] == "AI_CHECKED")
    first_run = c["latest_run"]["run_id"]
    code, r = call(E, "POST", f"/api/v2/cases/{ec}/forward", edu, json_body={"remark": "E2E: submitted as filed."})
    step("Education submits", code == 200, f"HTTP {code}")
    code, r = call(AG_PORT, "POST", f"/api/v2/cases/{ec}/return", rev, json_body={"remark": "Last pay certificate missing; attach and resubmit."})
    step("AG returns it", code == 200 and r["case"]["status"] == "RETURNED", f"HTTP {code}")
    code, c = call(E, "GET", f"/api/v2/cases/{ec}", edu)
    step("Education sees RETURNED with the AG remark", c["status"] == "RETURNED" and any("Last pay" in e["remark"] for e in c["events"]))
    code, r = call(E, "POST", f"/api/v2/cases/{ec}/forward", edu, json_body={"remark": "x"})
    step("re-submit without a new check refused", code == 409, f"HTTP {code}")
    code, r = call(E, "POST", f"/api/v2/cases/{ec}/documents", edu, files=[("files", "lpc.pdf", read(extra))])
    step("Education adds a document (submission 2)", code == 201 and r["submission_no"] == 2, f"HTTP {code}")
    code, r = call(E, "POST", f"/api/v2/cases/{ec}/check", edu)
    step("re-check started with a new run id", code == 202 and r["run_id"] != first_run, f"HTTP {code}")
    c = wait_status(E, edu, ec, {"AI_CHECKED", "AI_FAILED"})
    step("re-check finished", c["status"] == "AI_CHECKED")
    code, r = call(E, "POST", f"/api/v2/cases/{ec}/forward", edu, json_body={"remark": "LPC attached; resubmitted."})
    step("Education re-submits", code == 200 and r["case"]["status"] == "FORWARDED", f"HTTP {code}")
    code, r = call(AG_PORT, "POST", f"/api/v2/cases/{ec}/take-up", rev)
    step("AG takes up submission 2", code == 200 and r["case"]["status"] == "UNDER_REVIEW" and r["case"]["submission_no"] == 2)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} steps passed" + (f"; FAILED: {failed}" if failed else ""), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
