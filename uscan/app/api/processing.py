from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.compilation import Compilation
from ..models.document import Document
from ..models.page import Page
from ..services import document_service as svc
from ..services.workspace_service import get_owner
from ..utils.security import require_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@router.post("/documents/{id}/process")
def process(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    d = db.get(Document, id)
    if not d or d.owner != owner:
        raise HTTPException(404, "Document not found")
    svc.check_capacity(owner)
    return {"job_id": svc.start_job([id], owner)}


@router.get("/jobs/{job_id}")
def job(job_id: str, owner: str = Depends(get_owner)):
    j = svc.JOBS.get(job_id)
    if not j or j["owner"] != owner:
        raise HTTPException(404, "Job not found")
    return {k: v for k, v in j.items() if k not in ("owner", "finished")}


@router.get("/stats")
def stats(db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    mine = select(Document.id).where(Document.owner == owner)
    live = (Page.deleted.is_(False)) & Page.document_id.in_(mine)
    return {
        "documents": db.scalar(select(func.count()).select_from(Document).where(Document.owner == owner)),
        "pages": db.scalar(select(func.count()).select_from(Page).where(live)),
        "pending_review": db.scalar(select(func.count()).select_from(Page).where(live, Page.reviewed.is_(False), Page.flags > 0)),
        "compiled": db.scalar(select(func.count()).select_from(Compilation).where(Compilation.owner == owner, Compilation.status == "done")),
    }
