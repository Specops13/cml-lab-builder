"""Hardening for the local web UI (since 3.3.0).

The UI listens on 127.0.0.1 only, but any web page the user visits can still try to talk to it. This module adds:

* Host allowlist: requests must be addressed to 127.0.0.1 / localhost / [::1] (any port). A DNS-rebinding page
  (evil.example resolving to 127.0.0.1) sends Host: evil.example and is refused.
* CSRF: state-changing requests (POST/PUT/PATCH/DELETE) need the custom header X-CMLLab-Request: 1 (a cross-site page
  cannot send it without a CORS preflight, which this app never approves), must not come from another origin
  (Origin / Sec-Fetch-Site), and every /api and /report request from another site is refused.
* No CORS: no Access-Control-Allow-* headers are ever sent.
* Optional access token (on in the desktop app): a random per-launch secret. The launcher opens
  http://127.0.0.1:<port>/?token=..., which sets an HttpOnly SameSite=Strict cookie; without it (or
  Authorization: Bearer <token>) only the static files, /api/health and a short "open the app from its window" page
  are served. This keeps other local users of a shared computer out.
* Security headers on every response: a strict Content-Security-Policy (no inline script), nosniff,
  frame-ancestors 'none' / X-Frame-Options, Referrer-Policy no-referrer, COOP/CORP, Permissions-Policy."""
from __future__ import annotations

import hmac
import os
import secrets

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

CSRF_HEADER = "x-cmllab-request"
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
PUBLIC_PATHS = ("/static/", "/api/health", "/favicon.ico")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
       "frame-ancestors 'none'")
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}

LOCKED_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CML Lab Builder</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family:system-ui,sans-serif;max-width:36rem;margin:4rem auto;padding:0 1rem;line-height:1.5">
<h1 style="font-size:1.4rem">Open CML Lab Builder from its window</h1>
<p>This page needs the access link the app opened for you. Start CML Lab Builder again (its shortcut or
<code>cml-lab-builder</code>): it opens your browser with access, even when it is already running.</p>
<p>The address with access is also shown in the app's console window.</p></body></html>"""


def new_token() -> str:
    return secrets.token_urlsafe(24)


def allowed_hosts(extra=()) -> set[str]:
    out = set(LOOPBACK)
    out.update(h.strip().lower() for h in os.environ.get("CMLLAB_ALLOWED_HOSTS", "").split(",") if h.strip())
    out.update(h.lower() for h in extra if h)
    return out


def host_name(host_header: str) -> str:
    """'127.0.0.1:8765' -> '127.0.0.1', '[::1]:8765' -> '::1', 'Localhost.' -> 'localhost'."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else ""
    if h.count(":") == 1:
        h = h.split(":", 1)[0]
    return h.rstrip(".")


def _origin_ok(origin: str, host_header: str) -> bool:
    """Same origin as the request: http://<the Host header>."""
    o = (origin or "").strip().lower()
    return o in (f"http://{host_header.strip().lower()}", f"https://{host_header.strip().lower()}")


def cookie_name(port) -> str:
    return f"cmllab_access_{port or 0}"


def install(app, access_token: str | None = None, extra_hosts=()) -> None:
    hosts = allowed_hosts(extra_hosts)
    app.state.access_token = access_token

    @app.middleware("http")
    async def guard(request, call_next):
        resp = await _check(request, call_next, hosts, access_token)
        for k, v in HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8", "replace"), b.encode("utf-8", "replace"))


def _deny(status: int, msg: str) -> Response:
    return JSONResponse({"detail": msg}, status_code=status)


async def _check(request, call_next, hosts, token):
    host_header = request.headers.get("host", "")
    if host_name(host_header) not in hosts:
        return _deny(421, "unknown Host header: this app only answers on 127.0.0.1 / localhost (DNS rebinding protection)")
    path = request.url.path
    method = request.method.upper()
    raw = request.scope.get("path", path)      # percent-decoded
    if ".." in raw.split("/") or "\\" in raw or "\x00" in raw:   # ids never contain these (path traversal guard)
        return _deny(400, "invalid path")
    site = request.headers.get("sec-fetch-site", "")
    origin = request.headers.get("origin")
    sensitive = path.startswith(("/api/", "/report/")) and not path.startswith("/api/health")
    if sensitive and site in ("cross-site", "same-site"):
        return _deny(403, "cross-site request refused")
    if method == "OPTIONS":   # CORS preflight: never approved
        return Response(status_code=403)
    if method in UNSAFE:
        if origin is not None and not _origin_ok(origin, host_header):
            return _deny(403, "cross-origin request refused (CSRF protection)")
        if request.headers.get(CSRF_HEADER) != "1":
            return _deny(403, "missing X-CMLLab-Request header (CSRF protection); reload the page")
    if token and not path.startswith(PUBLIC_PATHS):
        given = request.query_params.get("token")
        if given is not None and _same(given, token) and method == "GET":
            resp = RedirectResponse(path if not path.startswith("/api/") else "/", status_code=303)
            resp.set_cookie(cookie_name(request.url.port), token, httponly=True, samesite="strict", path="/")
            return resp
        cookie = request.cookies.get(cookie_name(request.url.port), "")
        auth = request.headers.get("authorization", "")
        bearer = auth[7:] if auth.lower().startswith("bearer ") else ""
        if not (_same(cookie, token) or _same(bearer, token)):
            if path.startswith("/api/") or method != "GET":
                return _deny(401, "access token required: open the app from its window (or start it again)")
            return HTMLResponse(LOCKED_PAGE, status_code=401)
    return await call_next(request)
