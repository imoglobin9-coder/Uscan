from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import config
from ..config import DIRS
from ..database import get_db
from ..models.document import Document
from ..models.page import Page
from ..schemas.document import DocPatch, OrderIn, PagePatch, clean_blocks, clean_tables, doc_out, page_out
from ..services import document_service as svc
from ..services.workspace_service import create_workspace, get_owner
from ..utils import limits
from ..utils.security import require_auth, safe_join, safe_name

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def _doc(db, id_, owner) -> Document:
    d = db.get(Document, id_)
    if not d or d.owner != owner:  # not yours == does not exist
        raise HTTPException(404, "Document not found")
    return d


def _page(db, id_, owner) -> Page:
    p = db.get(Page, id_)
    d = db.get(Document, p.document_id) if p else None
    if not p or not d or d.owner != owner:
        raise HTTPException(404, "Page not found")
    return p


@router.post("/documents/upload")
def upload(request: Request, response: Response, files: list[UploadFile] = File(...), db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    if len(files) > config.MAX_FILES_PER_UPLOAD:
        raise HTTPException(400, f"Please upload at most {config.MAX_FILES_PER_UPLOAD} files at a time.")
    svc.check_capacity(owner)  # before anything is stored or created
    if not owner:
        owner = create_workspace(db, request, response)
    docs, errors = [], []
    for f in files:
        try:
            docs.append(svc.create_from_upload(db, f, owner))
        except ValueError as e:  # one bad file never blocks the rest of the batch
            errors.append({"filename": safe_name(f.filename), "error": str(e)})
    return {"documents": [doc_out(d) for d in docs], "errors": errors,
            "job_id": svc.start_job([d.id for d in docs], owner) if docs else None}


@router.get("/documents")
def list_docs(db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    return [doc_out(d) for d in db.scalars(select(Document).where(Document.owner == owner).order_by(Document.uploaded_at.desc()))]


@router.get("/documents/{id}")
def get_doc(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    return doc_out(_doc(db, id, owner))


@router.get("/documents/{id}/pages")
def get_pages(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    return [page_out(p) for p in _doc(db, id, owner).pages if not p.deleted]


@router.put("/documents/{id}")
def rename(id: str, body: DocPatch, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    d = _doc(db, id, owner)
    d.title = body.title.strip()
    db.commit()
    return doc_out(d)


@router.delete("/documents/{id}")
def delete_doc(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    d = _doc(db, id, owner)
    if d.status in ("processing", "uploaded") and svc.has_active_job(owner):
        raise HTTPException(409, "This report is still being read. Try again when it has finished.")
    svc.delete_files(d)
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.put("/documents/{id}/order")
def reorder(id: str, body: OrderIn, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    d = _doc(db, id, owner)
    by_id = {p.id: p for p in d.pages if not p.deleted}
    if set(body.page_ids) != set(by_id):
        raise HTTPException(400, "page_ids must list every page of the document exactly once")
    for i, pid in enumerate(body.page_ids):
        by_id[pid].position = i
    db.commit()
    return {"ok": True}


@router.get("/pages/{id}/image")
def page_image(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    p = _page(db, id, owner)
    try:
        path = safe_join(DIRS["previews"], p.document_id, f"{p.id}.jpg")
    except ValueError:
        raise HTTPException(404)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@router.put("/pages/{id}")
def edit_page(id: str, body: PagePatch, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    p = _page(db, id, owner)
    try:  # never store client-supplied structure as-is: only text of known lines / cells may change
        if body.blocks is not None:
            p.blocks = clean_blocks(body.blocks, p.blocks or [])
        if body.tables is not None:
            p.tables = clean_tables(body.tables, p.tables or [])
    except ValueError as e:
        raise HTTPException(422, str(e))
    p.flags = sum(b["needs_review"] for b in p.blocks) + sum(c.get("needs_review", False) for t in p.tables for r in t["rows"] for c in r)
    if body.reviewed is not None:
        p.reviewed = body.reviewed
    db.commit()
    svc.refresh_doc(db, db.get(Document, p.document_id))
    return page_out(p)


@router.delete("/pages/{id}")
def delete_page(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    p = _page(db, id, owner)
    p.deleted = True
    db.commit()
    svc.refresh_doc(db, db.get(Document, p.document_id))
    return {"ok": True}


@router.post("/pages/{id}/restore")
def restore_page(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    p = _page(db, id, owner)
    p.deleted = False
    db.commit()
    svc.refresh_doc(db, db.get(Document, p.document_id))
    return page_out(p)


@router.post("/pages/{id}/rotate")
def rotate(id: str, degrees: int = 90, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    if degrees not in (90, 180, 270):
        raise HTTPException(400, "degrees must be 90, 180 or 270")
    p = _page(db, id, owner)
    limits.require_disk()
    with limits.heavy():
        svc.rotate_page(db, p, degrees)
    return page_out(p)


@router.post("/pages/{id}/rescan")
def rescan(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    p = _page(db, id, owner)
    with limits.heavy():
        svc.rescan_page(db, p)
    return page_out(p)
