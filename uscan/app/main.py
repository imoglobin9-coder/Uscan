import html
import logging
import re
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from . import config
from .api import auth, compilations, documents, exports, processing, workspace
from .config import BASE
from .database import init_db
from .services import document_service, workspace_service
from .utils import limits
from .utils.file_utils import cleanup_tmp

log = logging.getLogger("scanner")

# Everything the UI needs is served from this origin: no inline scripts/styles, no third-party hosts.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Requests that run OCR or build PDFs: these get the stricter per-address limit.
HEAVY_PATH = re.compile(r"^/api/(documents/upload|documents/[^/]+/process|pages/[^/]+/(rotate|rescan)|compilations/[^/]+/export|compilations/merge-all|export/text)$")
MAX_JSON_BODY = 5 * 1024 * 1024
MAX_UPLOAD_BODY = (config.MAX_UPLOAD_MB * config.MAX_FILES_PER_UPLOAD + 1) * 1024 * 1024


@asynccontextmanager
async def lifespan(app):
    init_db()
    document_service.reset_interrupted()
    cleanup_tmp()
    if config.PUBLIC_MODE:
        workspace_service.start_janitor()  # expires idle workspaces and removes orphaned files
    yield


app = FastAPI(title="uscan", lifespan=lifespan, redoc_url=None,
              docs_url="/docs" if config.ENABLE_DOCS else None,
              openapi_url="/openapi.json" if config.ENABLE_DOCS else None)
for r in (auth, documents, processing, compilations, exports, workspace):
    app.include_router(r.router)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def _hostname(host: str) -> str:
    host = (host or "").strip().lower()
    return host.split("]")[0] + "]" if host.startswith("[") else host.split(":")[0]  # keep IPv6 literals intact


def secure(resp, request: Request):
    h, path = resp.headers, request.url.path
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    if not path.startswith(("/docs", "/openapi")):  # Swagger UI loads assets from a CDN, so it is exempt when enabled
        h["Content-Security-Policy"] = CSP
    if path.startswith("/api/"):
        h["Cache-Control"] = "no-store"  # extracted text and page images are private
    elif not path.startswith("/docs"):
        h["Cache-Control"] = "no-cache"
    if request.url.scheme == "https":
        h["Strict-Transport-Security"] = "max-age=31536000"
    return resp


def _reject(request: Request, status: int, msg: str, headers: dict | None = None):
    return secure(JSONResponse({"detail": msg}, status_code=status, headers=headers), request)


@app.middleware("http")
async def guard(request: Request, call_next):
    host_header, path = request.headers.get("host", ""), request.url.path
    if path != "/healthz" and "*" not in config.ALLOWED_HOSTS and _hostname(host_header) not in config.ALLOWED_HOSTS:
        return _reject(request, 400, "Unrecognised host. Add it to ALLOWED_HOSTS in .env if this is intentional.")  # DNS-rebinding guard
    if path.startswith("/api/") and config.RATE_LIMIT_PER_MIN:
        ip = limits.client_ip(request)
        if not limits.GENERAL.allow(ip, config.RATE_LIMIT_PER_MIN) or (HEAVY_PATH.match(path) and not limits.HEAVY.allow(ip, config.HEAVY_LIMIT_PER_MIN)):
            return _reject(request, 429, "You're going a little fast. Please wait a moment and try again.", {"Retry-After": "30"})
    if request.method in UNSAFE:
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none") or \
                (origin and (origin == "null" or urlparse(origin).netloc.lower() != host_header.lower())):
            return _reject(request, 403, "Cross-site request blocked.")  # CSRF guard
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            return _reject(request, 400, "Invalid Content-Length.")
        if length > (MAX_UPLOAD_BODY if request.url.path == "/api/documents/upload" else MAX_JSON_BODY):
            return _reject(request, 413, "Request is too large.")
    return secure(await call_next(request), request)


@app.exception_handler(limits.LimitError)
async def limited(request: Request, exc: limits.LimitError):
    return _reject(request, exc.status, str(exc), {"Retry-After": "30"} if exc.status in (429, 503) else None)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error")  # details stay in server logs, never in the response
    return secure(JSONResponse({"detail": "Something went wrong on the server."}, status_code=500), request)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE / "app" / "templates" / "index.html")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.get("/privacy", include_in_schema=False)
def privacy():
    page = (BASE / "app" / "templates" / "privacy.html").read_text(encoding="utf-8")
    ttl = f"{config.WORKSPACE_TTL_HOURS} hours" if config.WORKSPACE_TTL_HOURS else "until you delete them yourself"
    who = f'<a href="mailto:{html.escape(config.CONTACT_EMAIL)}">{html.escape(config.CONTACT_EMAIL)}</a>' if config.CONTACT_EMAIL else "the person who runs this site"
    return HTMLResponse(page.replace("{{TTL}}", ttl).replace("{{CONTACT}}", who))
