import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# PUBLIC_MODE: every visitor gets an anonymous private workspace (cookie), with quotas and automatic deletion.
PUBLIC_MODE = _bool("PUBLIC_MODE")


def _n(name: str, public: int, private: int) -> int:
    """Integer setting whose default depends on the mode (0 = unlimited / off)."""
    return int(os.getenv(name, public if PUBLIC_MODE else private))


BASE = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("DATA_DIR", BASE / "data")).resolve()
DIRS = {k: DATA / k for k in ("uploads", "processed", "previews", "compilations", "exports", "database", "tmp")}
for _d in DIRS.values():
    _d.mkdir(parents=True, exist_ok=True)
if os.name == "posix":  # documents are private: only the owner can read the data folders
    for _d in (DATA, *DIRS.values()):
        try:
            _d.chmod(0o700)
        except OSError:
            pass
DB_URL = f"sqlite:///{(DIRS['database'] / 'app.db').as_posix()}"

# --- processing limits
MAX_UPLOAD_MB = _n("MAX_UPLOAD_MB", 25, 50)
MAX_FILES_PER_UPLOAD = _n("MAX_FILES_PER_UPLOAD", 10, 20)
MAX_PAGES = _n("MAX_PAGES", 60, 300)  # per report
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", 60_000_000))  # decompression-bomb guard
LOW_CONF = float(os.getenv("LOW_CONF", 70))
OCR_LANG = os.getenv("OCR_LANG", "eng")
OCR_ENGINE = os.getenv("OCR_ENGINE", "tesseract")

# --- access control
API_KEY = os.getenv("API_KEY", "")            # optional: X-API-Key header for scripts
APP_PASSWORD = os.getenv("APP_PASSWORD", "")  # optional: sign-in page for the web UI
SESSION_HOURS = int(os.getenv("SESSION_HOURS", 12))
COOKIE_SECURE = _bool("COOKIE_SECURE")        # set true when served over HTTPS
HOST = os.getenv("USCAN_HOST", "127.0.0.1")   # not "HOST": many shells export that
PORT = int(os.getenv("USCAN_PORT") or os.getenv("PORT") or 8000)  # hosting platforms usually provide PORT
# Public sites sit behind a proxy on a name we can't know in advance, so any Host is accepted there.
ALLOWED_HOSTS = {h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "*" if PUBLIC_MODE else "localhost,127.0.0.1,[::1]").split(",") if h.strip()}
TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", "127.0.0.1")  # who may set X-Forwarded-For (real client IPs)
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "").strip()  # shown on the privacy page
ENABLE_DOCS = _bool("ENABLE_DOCS")            # interactive API docs at /docs (off by default)

# --- public-mode quotas (0 = unlimited). Defaults only apply when PUBLIC_MODE=true.
WORKSPACE_TTL_HOURS = _n("WORKSPACE_TTL_HOURS", 24, 0)      # a workspace is deleted after this long without activity
MAX_WORKSPACE_DOCS = _n("MAX_WORKSPACE_DOCS", 15, 0)        # reports per workspace
MAX_WORKSPACE_MB = _n("MAX_WORKSPACE_MB", 100, 0)           # total uploaded MB per workspace
MAX_WORKSPACE_PAGES = _n("MAX_WORKSPACE_PAGES", 100, 0)     # total pages per workspace
MAX_WORKSPACE_PDFS = _n("MAX_WORKSPACE_PDFS", 10, 0)        # compiled PDFs kept per workspace
MAX_WORKSPACES = _n("MAX_WORKSPACES", 200, 0)               # concurrent workspaces on the whole site
MAX_QUEUED_DOCS = _n("MAX_QUEUED_DOCS", 30, 0)              # reports waiting for the OCR worker, site-wide
NEW_WORKSPACES_PER_IP_HOUR = _n("NEW_WORKSPACES_PER_IP_HOUR", 10, 0)
MIN_FREE_MB = _n("MIN_FREE_MB", 1024, 0)                    # refuse new work when the disk is nearly full
RATE_LIMIT_PER_MIN = _n("RATE_LIMIT_PER_MIN", 600, 0)       # API requests per address per minute
HEAVY_LIMIT_PER_MIN = _n("HEAVY_LIMIT_PER_MIN", 20, 0)      # OCR / PDF-building requests per address per minute
HEAVY_CONCURRENCY = int(os.getenv("HEAVY_CONCURRENCY", 2))  # OCR / PDF jobs allowed to run at the same time
