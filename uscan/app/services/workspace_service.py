"""Anonymous per-visitor workspaces (PUBLIC_MODE): who is this request, creating one, expiry, and deletion."""
import datetime as dt
import hashlib
import logging
import secrets
import shutil
import threading
import time
from fastapi import Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .. import config
from ..config import DIRS
from ..database import SessionLocal, get_db
from ..models.compilation import Compilation
from ..models.document import Document
from ..models.workspace import Workspace
from ..utils import limits
from ..utils.file_utils import cleanup_tmp
from ..utils.security import safe_join
from . import document_service as svc

log = logging.getLogger("scanner")
COOKIE, LOCAL, TOUCH_EVERY_S = "uscan_ws", "local", 300


def _wid(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def get_owner(request: Request, db: Session = Depends(get_db)) -> str:
    """The workspace this request may touch. "local" when not public; "" when the visitor has none (yet),
    which matches no document, so every lookup simply finds nothing."""
    if not config.PUBLIC_MODE:
        return LOCAL
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 128:
        return ""
    ws = db.get(Workspace, _wid(token))
    if not ws:
        return ""
    now, idle = dt.datetime.utcnow(), dt.datetime.utcnow() - ws.last_seen
    if config.WORKSPACE_TTL_HOURS and idle > dt.timedelta(hours=config.WORKSPACE_TTL_HOURS):
        return ""  # expired; the janitor removes its files shortly
    if idle.total_seconds() > TOUCH_EVERY_S:
        ws.last_seen = now
        db.commit()
    return ws.id


def create_workspace(db: Session, request: Request, response: Response) -> str:
    if not limits.NEW_WORKSPACE.allow(limits.client_ip(request), config.NEW_WORKSPACES_PER_IP_HOUR):
        raise limits.LimitError("Too many new sessions from your network. Please try again later.")
    if config.MAX_WORKSPACES and db.scalar(select(func.count()).select_from(Workspace)) >= config.MAX_WORKSPACES:
        raise limits.LimitError("uscan is at capacity right now. Please try again later.", 503)
    token = secrets.token_urlsafe(32)
    wid = _wid(token)
    db.add(Workspace(id=wid))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=7 * 86400, httponly=True, samesite="strict", path="/",
                        secure=config.COOKIE_SECURE or request.url.scheme == "https")
    return wid


def purge(db: Session, owner: str):
    """Delete everything a workspace owns: rows AND files on disk."""
    for d in db.scalars(select(Document).where(Document.owner == owner)).all():
        svc.delete_files(d)
        db.delete(d)
    for c in db.scalars(select(Compilation).where(Compilation.owner == owner)).all():
        if c.output_name:
            try:
                safe_join(DIRS["compilations"], c.output_name).unlink(missing_ok=True)
            except ValueError:
                pass
        db.delete(c)
    ws = db.get(Workspace, owner)
    if ws:
        db.delete(ws)
    db.commit()


def _old(path, age_s: float) -> bool:
    try:
        return time.time() - path.stat().st_mtime > age_s
    except OSError:
        return False


def sweep_orphans(db: Session, min_age_s: int = 3600):
    """Remove files no database row points to (crashes, races). Only old files, so uploads in flight are safe."""
    doc_ids = set(db.scalars(select(Document.id)))
    stored = set(db.scalars(select(Document.stored_name)))
    outputs = {x for x in db.scalars(select(Compilation.output_name)) if x}
    for sub in ("processed", "previews"):
        for p in DIRS[sub].iterdir():
            if p.name not in doc_ids and _old(p, min_age_s):
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    for sub, keep in (("uploads", stored), ("compilations", outputs)):
        for p in DIRS[sub].iterdir():
            if p.name not in keep and _old(p, min_age_s):
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    for p in DIRS["exports"].iterdir():
        if _old(p, 3600):
            p.unlink(missing_ok=True)


def sweep():
    """Delete expired workspaces, orphaned files and stale temp files."""
    with SessionLocal() as db:
        if config.WORKSPACE_TTL_HOURS:
            cutoff = dt.datetime.utcnow() - dt.timedelta(hours=config.WORKSPACE_TTL_HOURS)
            for ws in db.scalars(select(Workspace).where(Workspace.last_seen < cutoff)).all():
                if not svc.has_active_job(ws.id):
                    purge(db, ws.id)
        sweep_orphans(db)
    cleanup_tmp()


def start_janitor(every_s: int = 600):
    def loop():
        while True:
            try:
                sweep()
            except Exception:
                log.exception("Cleanup failed")
            time.sleep(every_s)
    threading.Thread(target=loop, daemon=True, name="uscan-janitor").start()
