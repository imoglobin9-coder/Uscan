import hashlib
import hmac
import re
import secrets
import threading
import time
import unicodedata
from pathlib import Path
from fastapi import Header, HTTPException, Request
from .. import config

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
MAGIC = {
    ".pdf": [b"%PDF"], ".jpg": [b"\xff\xd8\xff"], ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"], ".tif": [b"II*\x00", b"MM\x00*"], ".tiff": [b"II*\x00", b"MM\x00*"],
}
SESSION_COOKIE = "uscan_session"


def safe_name(name: str | None) -> str:
    name = Path((name or "file").replace("\\", "/")).name
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^\w.\- ]", "_", name).strip(". ")[:120]
    return name or "file"


def validate_upload(filename: str | None, head: bytes) -> str:
    """Return the validated lowercase extension or raise ValueError."""
    ext = Path(safe_name(filename)).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("Unsupported file type. Allowed: PDF, JPG, PNG, TIFF.")
    if not any(head.startswith(m) for m in MAGIC[ext]):
        raise ValueError("File content does not match its extension.")
    return ext


def safe_join(base: Path, *parts: str) -> Path:
    base = base.resolve()
    p = base.joinpath(*parts).resolve()
    if p != base and base not in p.parents:
        raise ValueError("Invalid path")
    return p


# ---------------------------------------------------------------- authentication
def _eq(a: str, b: str) -> bool:
    """Constant-time compare that also accepts non-ASCII input (compare_digest on str would raise)."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def auth_enabled() -> bool:
    return bool(config.API_KEY or config.APP_PASSWORD)


def ui_password() -> str:
    """Password for the sign-in page. Falls back to API_KEY so setting only that still lets you in."""
    return config.APP_PASSWORD or config.API_KEY


_SESSIONS: dict[str, float] = {}  # sha256(token) -> expiry; server-side so logout really ends a session
_FAILS: dict[str, list[float]] = {}
_lock = threading.Lock()
MAX_SESSIONS, MAX_FAILS, FAIL_WINDOW_S = 100, 5, 300


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session() -> str:
    token, now = secrets.token_urlsafe(32), time.time()
    with _lock:
        for k in [k for k, exp in _SESSIONS.items() if exp < now]:
            del _SESSIONS[k]
        while len(_SESSIONS) >= MAX_SESSIONS:  # drop the oldest
            del _SESSIONS[min(_SESSIONS, key=_SESSIONS.get)]
        _SESSIONS[_h(token)] = now + config.SESSION_HOURS * 3600
    return token


def valid_session(token: str | None) -> bool:
    if not token:
        return False
    with _lock:
        exp = _SESSIONS.get(_h(token))
        if exp is not None and exp < time.time():
            del _SESSIONS[_h(token)]
            return False
        return exp is not None


def end_session(token: str | None):
    if token:
        with _lock:
            _SESSIONS.pop(_h(token), None)


def login_allowed(ip: str) -> int:
    """0 if the client may try a password, otherwise the seconds it must wait."""
    now = time.time()
    with _lock:
        recent = [t for t in _FAILS.get(ip, []) if now - t < FAIL_WINDOW_S]
        _FAILS[ip] = recent
        if len(_FAILS) > 1000:  # bound memory
            for k in [k for k, v in _FAILS.items() if not v or now - v[-1] > FAIL_WINDOW_S]:
                _FAILS.pop(k, None)
        return int(FAIL_WINDOW_S - (now - recent[0])) + 1 if len(recent) >= MAX_FAILS else 0


def login_failed(ip: str):
    with _lock:
        _FAILS.setdefault(ip, []).append(time.time())


def login_ok(ip: str):
    with _lock:
        _FAILS.pop(ip, None)


def is_authenticated(request: Request, x_api_key: str | None = None) -> bool:
    if not auth_enabled():
        return True
    x_api_key = x_api_key if x_api_key is not None else request.headers.get("x-api-key")
    if config.API_KEY and x_api_key and _eq(x_api_key, config.API_KEY):
        return True
    return valid_session(request.cookies.get(SESSION_COOKIE))


def require_auth(request: Request, x_api_key: str | None = Header(default=None)):
    """No-op unless APP_PASSWORD / API_KEY is set. Accepts the browser session cookie or an X-API-Key header."""
    if not is_authenticated(request, x_api_key):
        raise HTTPException(401, "Unauthorized")
    return {"user": "local"}
