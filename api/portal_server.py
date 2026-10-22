"""One process, every portal: the built frontend on 87 ports, each port knowing which portal it is.

86 department portals plus the AG portal cannot be 86 development servers (a Vite process costs
~200 MB and this box has a few GB spare), so one Starlette app is served by one uvicorn server on
87 pre-bound sockets. Each request knows the local port it arrived on; the port names the
portal; the portal's config -- kind, slug, name, theme -- is written into ``index.html`` as
``window.__PORTAL__`` so the same bundle wears the right name and colours. ``/api/*`` is proxied
to the backend, streaming both ways (a 256 MB upload, a live event stream), with an ``X-Portal``
header the backend trusts over anything in the body.

    /home/tmc/vllm_env/bin/python3 -m api.portal_server          # all ports
    /home/tmc/vllm_env/bin/python3 -m api.portal_server 5184 5180   # a subset (debugging)

A port that cannot be bound (another service holds it) is logged and skipped; the rest still
serve. ``GET /__portals`` on any port lists what is actually bound.

Deployment (docs/DEPLOYMENT.md F5, F7, F9):

    PENSION_PORTAL_BIND      address to listen on; 0.0.0.0 in the trial, 127.0.0.1 in production
                             (nginx in front is then the only way in)
    PENSION_TRUSTED_PROXIES  addresses whose X-Forwarded-For is believed (default 127.0.0.1: the
                             nginx on this machine). Anyone else's is ignored, so a caller cannot
                             give itself another address to escape the login limit or the audit log.
    PENSION_GPF_PROXY        /gpf/ serves the GP Fund module's own page and API, which the AG's
                             case screen shows in a frame. The module has no sign-in of its own,
                             so every /gpf/ request must carry the frame cookie the portal sets
                             for an AG or administrator account (api.v2 /auth/gpf-session); the
                             API confirms it. PENSION_GPF_PROXY=open drops the check (a closed
                             demo only). Before 5 Oct 2026 /gpf/ was open to anyone.

In production (PENSION_ENV=production) /start.html and /__portals are not served, and
PENSION_TRUST_PORT_HEADER is ignored.
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote
import contextlib
import json
import mimetypes
import os
import re
import secrets
import socket
import sys
from pathlib import Path

import aiohttp
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.gzip import GZipMiddleware
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from api import gpf_bridge, settings
from api.departments import AG_PORTAL_PORT, AG_PORTAL_SLUG, BY_PORT, DEPARTMENTS, SINGLE_PORTAL
from api.themes import theme_for

MAX_REQUEST_BYTES = settings.MAX_REQUEST_BYTES

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(os.environ.get("PENSION_PORTAL_DIST") or ROOT / "portals" / "dist")
API = os.environ.get("PENSION_API_URL") or "http://127.0.0.1:8110"

#: The GP Fund frame's sign-in cookie (api.v2.GPF_COOKIE).
GPF_COOKIE = "pension_gpf"
#: The module's reads that are judged per examination: the register of cases and anything under
#: one case (the case, its pages, specimens, issue pack, SAP template).
_GPF_READ_ROUTE = re.compile(r"^/api/cases(?:/([^/]+))?(?:/|$)")
#: How long a frame cookie's "yes" from the API is remembered. Long enough that a page's dozens of
#: asset requests cost one check; short enough that a sign-out or a disabled account is felt
#: within seconds, and sign-out itself forgets the entry at once (audit 6 Oct 2026, L11).
GPF_CHECK_TTL_S = 10

#: Never served from dist, whatever lands there.
_FORBIDDEN = ("credentials", ".csv", ".env", ".sqlite")

#: Headers this server sets itself; a client's copies are dropped before proxying.
_SERVER_SET = {"x-portal", "x-forwarded-host", "x-forwarded-port", "x-forwarded-for", "x-forwarded-proto", "x-portal-port"}
_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
               "trailers", "transfer-encoding", "upgrade", "host", "content-length"}


def portal_config(port: int) -> dict:
    """What a browser on this port must know about itself."""
    if port == AG_PORTAL_PORT:
        return {"kind": "ag", "slug": AG_PORTAL_SLUG, "code": None, "name": "Accountant General Punjab",
                "port": port, "single_portal": SINGLE_PORTAL, "theme": theme_for("ag", title="SERVE PUNJAB")}
    d = BY_PORT.get(port)
    if d is None:
        return {"kind": "unknown", "slug": None, "code": None, "name": f"port {port}", "port": port,
                "theme": theme_for("secretariat", title="Pension Portal")}
    return {"kind": "department", "slug": d.slug, "code": d.code, "name": d.name, "port": port,
            "is_police": d.is_police, "theme": theme_for(d.theme, title=f"{d.name} — Pension Portal")}


#: One nonce per process for the one inline script this server writes (the portal config); the
#: Content-Security-Policy names it, so no other inline script can run.
NONCE = secrets.token_urlsafe(16)

SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'nonce-" + NONCE + "'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; font-src 'self' data:; object-src 'none'; "
        "frame-src 'self' blob:; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"),
}

#: The GP Fund module's pages (proxied under /gpf/) are framed by the case screen and carry their
#: own module scripts, so they get a header set of their own: framed by this origin only, no nonce.
GPF_SECURITY_HEADERS = {
    **SECURITY_HEADERS,
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "connect-src 'self'; font-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'self'"),
}


class SecurityHeaders:
    """Pure ASGI middleware: the headers above on every response this server sends."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        chosen = GPF_SECURITY_HEADERS if scope.get("path", "").startswith("/gpf") else SECURITY_HEADERS

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for k, v in chosen.items():
                    headers[k] = v
            await send(message)
        return await self.app(scope, receive, send_with_headers)


def render_index(template: str, port: int) -> str:
    """index.html with this port's portal config injected before </head>."""
    cfg = json.dumps(portal_config(port), ensure_ascii=False).replace("</", "<\\/")
    tag = f'<script nonce="{NONCE}">window.__PORTAL__={cfg}</script>'
    if "</head>" in template:
        return template.replace("</head>", tag + "\n</head>", 1)
    return tag + template


def gpf_subpath(raw: str) -> str | None:
    """The path under /gpf/ as one normalised string, used for the action check AND the forwarded
    request -- or None for a path that must be refused.

    The check matched the case id on the raw path while aiohttp/yarl collapsed dot segments on the
    way out, so ``/gpf/api/cases/nonexistent/../REALID/dispose`` passed the check on "nonexistent"
    and acted on REALID (frontend review F3, 9 Oct 2026). Starlette hands the route the path
    decoded once; a ``%`` still in it is a second layer of encoding, refused along with a ``.`` or
    ``..`` segment, an empty segment, a backslash and control characters.
    """
    path = raw or ""
    if "%" in path or "\\" in path or any(ord(c) < 32 or c == "\x7f" for c in path):
        return None
    # /gpf/ itself is the module's own page, the one the case screen frames (``/gpf/?embed=1``):
    # an empty path is the root, not an empty segment. (Refused from 9 Oct to 12 Oct 2026: every
    # GP Fund case screen read "not a valid GP Fund path".)
    if path == "":
        return "/"
    if any(seg in ("", ".", "..") for seg in path.split("/")):
        return None
    return "/" + path


class PortalApp:
    def __init__(self, dist: Path = DIST, api: str = API, trust_port_header: bool | None = None) -> None:
        self.dist = dist
        self.api = api.rstrip("/")
        self.gpf = os.environ.get("PENSION_GPF_URL", "http://127.0.0.1:8201").rstrip("/")
        # Tests send X-Portal-Port to pretend a request arrived on another port; in service the
        # bound socket's port is the only truth, so the header is honoured only when asked for.
        self.trust_port_header = (os.environ.get("PENSION_TRUST_PORT_HEADER") == "1") if trust_port_header is None else trust_port_header
        if self.trust_port_header and settings.production() and trust_port_header is None:
            print("[portals] PENSION_TRUST_PORT_HEADER is a test switch; ignored in production", file=sys.stderr)
            self.trust_port_header = False
        self.template = ""
        self.template_mtime = 0.0
        self.rendered: dict[int, str] = {}
        self._reload_template()
        self.bound: list[int] = []
        self.session: aiohttp.ClientSession | None = None
        self._gpf_ok: dict[str, tuple[float, str]] = {}        # frame cookie -> (checked-until, officer)
        self._gpf_read_ok: dict[tuple[str, str], float] = {}   # (frame cookie, examination) -> checked-until
        routes = [
            Route("/__portals", self.portals),
            Route("/start.html", self.start_sheet),
            Route("/api/{path:path}", self.proxy, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
            # The GP Fund module (GP/backend on :8201), reached through the portal's own address so
            # an officer opens one site: its web app is embedded in the case screen (28 Sep 2026).
            Route("/gpf", self.gpf_root),
            Route("/gpf/{path:path}", self.gpf_proxy, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
        ]
        if (dist / "assets").is_dir():
            routes.append(Mount("/assets", StaticFiles(directory=dist / "assets"), name="assets"))
        # Self-hosted type. page() below serves a file at the bundle ROOT only -- one segment, no
        # slash -- so until this mount existed every /fonts/*.woff2 fell through to the catch-all,
        # which answered index.html with HTTP 200 and content-type text/html. A browser rejects
        # markup as a font silently, so the page simply drew in the fallback face and nothing in
        # any log said why. That is the whole history of the Geist face this bundle declared for a
        # month and never once rendered (22 Oct 2026). The office's type is served from here now,
        # and the portal must reach the registry for no part of its own appearance.
        # Python's table does not know woff2, and StaticFiles asks that table: without this the
        # font goes out as application/octet-stream.
        mimetypes.add_type("font/woff2", ".woff2")
        if (dist / "fonts").is_dir():
            routes.append(Mount("/fonts", StaticFiles(directory=dist / "fonts"), name="fonts"))
        routes.append(Route("/{path:path}", self.page, methods=["GET", "HEAD"]))

        @contextlib.asynccontextmanager
        async def lifespan(_app):
            await self.start()
            try:
                yield
            finally:
                await self.stop()

        # GZip before the security headers, so it wraps the proxied module's assets too.
        # Nothing compressed anything: no middleware here, none in the API, and nginx -- which
        # would normally do it -- is not in front on this deployment. The portal's own bundle
        # is 357 KB of JavaScript and 59 KB of CSS, and opening the GP Fund examination adds
        # the module's 43 KB and 32 KB on top, all of it uncompressed over a public address.
        # Measured 20 Oct 2026: 502 KB becomes 145 KB, a 71% saving, which is most of a second
        # on a 2 Mbit link and the reason the examination tab felt slow to open.
        #
        # 500 bytes: below that a gzip header and the CPU cost it, and the small JSON replies
        # the case screen polls are better left alone.
        self.app = Starlette(routes=routes, lifespan=lifespan,
                             middleware=[Middleware(GZipMiddleware, minimum_size=500),
                                         Middleware(SecurityHeaders)])

    def _reload_template(self) -> None:
        """Read index.html once, and again whenever a rebuild changes it (its asset names change)."""
        index = self.dist / "index.html"
        try:
            mtime = index.stat().st_mtime
        except OSError:
            if not self.template:
                self.template = ("<!doctype html><html><head><title>Pension Portal</title></head><body>The portal has not been "
                                 "built: run <code>npm run build</code> in portals/.</body></html>")
            return
        if mtime != self.template_mtime:
            self.template = index.read_text(encoding="utf-8")
            self.template_mtime = mtime
            self.rendered.clear()

    async def start(self) -> None:
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))

    async def stop(self) -> None:
        if self.session:
            await self.session.close()

    def _port(self, request: Request) -> int:
        server = request.scope.get("server") or ("", 0)
        if self.trust_port_header:                              # tests only (PENSION_TRUST_PORT_HEADER=1)
            forced = request.headers.get("x-portal-port")
            if forced and forced.isdigit():
                return int(forced)
        return int(server[1] or 0)

    async def portals(self, request: Request) -> Response:
        if settings.production():
            return Response("not found", status_code=404)
        return JSONResponse({"this_port": self._port(request), "bound": self.bound,
                             "portals": [portal_config(p) for p in self.bound]})

    async def start_sheet(self, request: Request) -> Response:
        """The office's sign-in sheet, on the AG portal's port only (user's decision, 25 Sep 2026:
        the sheet is served openly as before). It is the live credentials file, so a password
        reset shows here at once."""
        if self._port(request) != AG_PORTAL_PORT or settings.production():
            return Response("not found", status_code=404)
        from api import db, gpf_bridge
        path = db.CREDENTIALS_HTML
        if not path.exists():
            return Response("The credentials sheet has not been generated yet (python3 -m api.db credentials).",
                            status_code=404)
        # The sheet's own inline script (its search box) must carry this server's nonce, or the
        # Content-Security-Policy stops it and the search box does nothing (9 Oct 2026).
        html = path.read_text(encoding="utf-8").replace("<script>", f'<script nonce="{NONCE}">')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    async def page(self, request: Request) -> Response:
        path = request.path_params.get("path", "")
        if path and "/" not in path and "." in path:
            # A real file at the bundle root (the TMC logo, a favicon) -- never a secret.
            if any(bad in path.lower() for bad in _FORBIDDEN):
                return Response("not found", status_code=404)
            candidate = self.dist / path
            if candidate.is_file() and candidate.resolve().parent == self.dist.resolve():
                return FileResponse(candidate)
        port = self._port(request)
        self._reload_template()
        html = self.rendered.get(port)
        if html is None:
            html = self.rendered[port] = render_index(self.template, port)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @staticmethod
    def gpf_open() -> bool:
        """/gpf/ without the sign-in check: only where explicitly asked for, and never in production."""
        return os.environ.get("PENSION_GPF_PROXY", "").strip().lower() == "open" and not settings.production()

    async def gpf_signed_in(self, request: Request) -> str | None:
        """The officer this /gpf/ request acts as, where it is from a signed-in AG or administrator
        (the frame cookie); None otherwise. Asked of the API, which holds the secret and the
        accounts; a yes is remembered for 30 seconds so a page's dozens of asset requests cost
        one check. In open mode (a closed demo) the request names no officer: ""."""
        if self.gpf_open():
            return ""
        token = request.cookies.get(GPF_COOKIE)
        if not token:
            return None
        now = asyncio.get_running_loop().time()
        cached = self._gpf_ok.get(token)
        if cached and cached[0] > now:
            return cached[1]
        if self.session is None:                               # not started: refuse rather than fail open
            return None
        try:
            async with self.session.get(f"{self.api}/api/v2/auth/gpf-check",
                                        headers={"X-GPF-Session": token}) as r:
                if r.status != 200:
                    return None
                answer = await r.json()
                officer = str(answer.get("officer") or "")
                name = str(answer.get("name") or "")
        except (aiohttp.ClientError, ValueError):
            return None
        if not officer:
            return None
        if len(self._gpf_ok) > 1000:
            self._gpf_ok.clear()
        # The band and the officer's own name travel together; the name is what the module records
        # the action under (G6). Encoded as band|name, the form the module's api reads.
        acting = f"{officer}|{name}" if name else officer
        self._gpf_ok[token] = (now + GPF_CHECK_TTL_S, acting)
        return acting

    def forget_frame_sign_in(self, token: str | None) -> None:
        """Drop a frame cookie from the remembered checks: sign-out must take effect at once, not
        when the cache entry happens to lapse (audit 6 Oct 2026, L11)."""
        if token:
            self._gpf_ok.pop(token, None)

    async def gpf_read_refused(self, request: Request, sub: str) -> Response | None:
        """A read of the module's register or of one examination is passed on only if the API
        agrees this officer may see it (the case system's wing and tier visibility). Other reads
        (health, the rules, a reading job's progress) pass. A yes is remembered per examination
        for GPF_CHECK_TTL_S seconds; a no is never remembered."""
        m = _GPF_READ_ROUTE.match(sub)
        if m is None:
            return None
        token = request.cookies.get(GPF_COOKIE, "")
        key = (token, m.group(1) or "")
        now = asyncio.get_running_loop().time()
        cached = self._gpf_read_ok.get(key)
        if cached and cached > now:
            return None
        refused = await self.gpf_act_refused(request, sub)
        if refused is None:
            if len(self._gpf_read_ok) > 1000:
                self._gpf_read_ok.clear()
            self._gpf_read_ok[key] = now + GPF_CHECK_TTL_S
        return refused

    async def gpf_act_refused(self, request: Request, sub: str) -> Response | None:
        """A change sent from the frame is passed on only if the API agrees this officer may act on
        that examination now: never from the sign-in cache, because what decides it is the
        portal case's status and holder, which move (audit 6 Oct 2026). Fails closed. The method
        travels with the path, so the API knows a read from a change."""
        try:
            async with self.session.get(f"{self.api}/api/v2/auth/gpf-act-check",
                                        headers={"X-GPF-Session": request.cookies.get(GPF_COOKIE, ""),
                                                 "X-GPF-Path": sub, "X-GPF-Method": request.method}) as r:
                if r.status == 200:
                    return None
                detail = str((await r.json(content_type=None) or {}).get("detail") or "not allowed")
                return JSONResponse({"detail": detail}, status_code=r.status if r.status in (401, 403, 409) else 502)
        except (aiohttp.ClientError, ValueError):
            return JSONResponse({"detail": "the portal could not confirm this action; try again"}, status_code=502)

    @staticmethod
    def _gpf_refused() -> Response:
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>Sign in</title><p style='font-family:sans-serif'>"
                            "The GP Fund module opens from a case in the pension portal, for the Accountant General's "
                            "desk. Sign in at the portal and open the case there.</p>", status_code=401)

    async def gpf_root(self, request: Request) -> Response:
        if await self.gpf_signed_in(request) is None:
            return self._gpf_refused()
        return RedirectResponse(url="/gpf/" + (f"?{request.url.query}" if request.url.query else ""), status_code=307)

    async def gpf_proxy(self, request: Request) -> Response:
        """Pass a request under /gpf/ to the GP Fund module, path prefix stripped. Signed-in only."""
        officer = await self.gpf_signed_in(request)
        if officer is None:
            return self._gpf_refused()
        assert self.session is not None
        sub = gpf_subpath(request.path_params.get("path", ""))
        if sub is None:
            return JSONResponse({"detail": "not a valid GP Fund path"}, status_code=400)
        # Every change is asked about, and every read of the module's register or of one
        # examination too: until 12 Oct 2026 a GET through the frame listed every GP Fund claim
        # and opened any wing's scans on the cookie alone (audit of 12 Oct 2026). A read answered
        # yes is remembered for a few seconds per examination, since a page's scans are dozens
        # of requests.
        reading = request.method in ("GET", "HEAD", "OPTIONS")
        if not self.gpf_open():
            refused = (await self.gpf_read_refused(request, sub) if reading
                       else await self.gpf_act_refused(request, sub))
            if refused is not None:
                return refused
        url = f"{self.gpf}{quote(sub, safe='/-_.~:@!$&()*+,;=')}" + (f"?{request.url.query}" if request.url.query else "")
        # The module gets neither the portal's cookies (the frame's sign-in among them) nor its token,
        # and the officer it records is the signed-in account's: a browser's X-GPF-Officer is dropped.
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in _HOP_BY_HOP and k.lower() not in ("host", "cookie", "authorization", "x-gpf-officer", "x-gpf-user", "x-gpf-key")}
        # The key that tells the module this came from the portal, which has already decided who
        # the officer is and what they may touch; a browser cannot forge it because it never has
        # it (audit of 13 Oct 2026, C-04). Dropped from the client's own headers just above.
        key = gpf_bridge.api_key()
        if key:
            headers[gpf_bridge.GPF_KEY_HEADER] = key
        if officer:
            band, _, name = officer.partition("|")
            headers["X-GPF-Officer"] = band
            if name:
                headers["X-GPF-User"] = gpf_bridge.header_name(name)
        body = await request.body()
        try:
            async with self.session.request(request.method, url, headers=headers, data=body, allow_redirects=False) as up:
                content = await up.read()
                out = {k: v for k, v in up.headers.items() if k.lower() not in _HOP_BY_HOP and k.lower() != "content-length"}
                return Response(content, status_code=up.status, headers=out)
        except aiohttp.ClientError as exc:
            return JSONResponse({"detail": f"the GP Fund module is not reachable ({exc}); start it with ./GP/run.sh"},
                                status_code=502)

    async def proxy(self, request: Request) -> Response:
        assert self.session is not None
        port = self._port(request)
        cfg = portal_config(port)
        url = f"{self.api}{request.url.path}" + (f"?{request.url.query}" if request.url.query else "")
        # The portal and the forwarding headers are this server's to set: whatever the client sent
        # under those names is dropped first, so a browser cannot claim another portal or address.
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in _HOP_BY_HOP and k.lower() not in _SERVER_SET}
        headers["X-Portal"] = cfg["slug"] or ""
        # The length goes through (it is not hop-by-hop for a body passed on unchanged): without it
        # the body went upstream chunked and the API's early size refusal never fired. Past the
        # limit the request stops here (audit 6 Oct 2026).
        length = request.headers.get("content-length", "")
        if length.isdigit():
            if int(length) > MAX_REQUEST_BYTES:
                return JSONResponse({"detail": f"the request exceeds {MAX_REQUEST_BYTES // 1048576} MB"},
                                    status_code=413)
            headers["Content-Length"] = length
        headers["X-Forwarded-Host"] = request.headers.get("host", "")
        headers["X-Forwarded-Port"] = str(port)
        headers["X-Forwarded-For"] = request.client.host if request.client else ""
        body = None if request.method in ("GET", "HEAD", "OPTIONS") else request.stream()
        try:
            upstream = await self.session.request(request.method, url, headers=headers, data=body,
                                                  allow_redirects=False)
        except aiohttp.ClientError as exc:
            return JSONResponse({"detail": f"the application server is not reachable ({exc.__class__.__name__})"},
                                status_code=502)
        out_headers = {k: v for k, v in upstream.headers.items()
                       if k.lower() not in _HOP_BY_HOP and k.lower() != "content-encoding"}
        if request.url.path == "/api/v2/auth/logout" and request.method == "POST":
            self.forget_frame_sign_in(request.cookies.get(GPF_COOKIE))

        async def body_iter():
            try:
                async for chunk in upstream.content.iter_any():
                    yield chunk
            finally:
                upstream.release()

        return StreamingResponse(body_iter(), status_code=upstream.status, headers=out_headers,
                                 media_type=upstream.headers.get("content-type"))


def bind_host() -> str:
    """Where the portals listen: everywhere for the trial, loopback behind nginx in production."""
    return os.environ.get("PENSION_PORTAL_BIND") or ("127.0.0.1" if settings.production() else "0.0.0.0")


def bind(ports: list[int], host: str | None = None) -> tuple[list[socket.socket], list[int], list[tuple[int, str]]]:
    socks, bound, failed = [], [], []
    host = host or bind_host()
    for port in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            s.listen(128)
            s.set_inheritable(True)
            socks.append(s)
            bound.append(port)
        except OSError as exc:
            s.close()
            failed.append((port, str(exc)))
    return socks, bound, failed


def all_ports() -> list[int]:
    """One port for everyone, unless the per-department ports are switched on."""
    if SINGLE_PORTAL:
        return [AG_PORTAL_PORT]
    return [AG_PORTAL_PORT] + [d.port for d in DEPARTMENTS]


async def serve(ports: list[int]) -> None:
    portal = PortalApp()
    socks, bound, failed = bind(ports)
    portal.bound = bound
    for port, why in failed:
        who = BY_PORT.get(port)
        print(f"[portals] could not bind :{port} ({who.name if who else 'AG portal'}): {why}", file=sys.stderr)
    if not socks:
        print("[portals] nothing could be bound; exiting", file=sys.stderr)
        return
    print(f"[portals] serving {len(bound)} portal(s) on {bind_host()} from {DIST} → API {API}", file=sys.stderr)
    # X-Forwarded-For is believed from the reverse proxy only; "*" let any caller name its own address.
    trusted = os.environ.get("PENSION_TRUSTED_PROXIES") or "127.0.0.1"
    config = uvicorn.Config(portal.app, log_level="warning", proxy_headers=True, forwarded_allow_ips=trusted,
                            timeout_keep_alive=30)
    server = uvicorn.Server(config)
    await server.serve(sockets=socks)


def main(argv: list[str]) -> int:
    ports = [int(a) for a in argv[1:]] or all_ports()
    asyncio.run(serve(ports))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
