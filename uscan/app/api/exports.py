from pydantic import BaseModel
from sqlalchemy import select
import datetime as dt
import logging
import re
import uuid
from starlette.background import BackgroundTask
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..config import DIRS
from ..database import get_db
from ..models.compilation import Compilation
from ..models.document import Document
from ..schemas.compilation import CompilationIn, Item, Options, comp_out
from ..services import compilation_service as cs, text_service as ts
from ..services.workspace_service import get_owner
from ..utils import limits
from ..utils.security import require_auth, safe_join
from .compilations import check_pdf_quota, get_comp

log = logging.getLogger("scanner")
router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@router.post("/compilations/{id}/export")
def export(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    c = get_comp(db, id, owner)
    limits.require_disk()
    with limits.heavy():  # acquired outside the try: "busy" must not be recorded as a failed PDF
        try:
            c.page_count, c.status, c.error = cs.build(db, c), "done", None
        except ValueError as e:
            c.status, c.error = "error", str(e)
        except Exception:
            log.exception("PDF compilation failed")  # details stay in the server log, never in the response
            c.status, c.error = "error", "The PDF could not be generated."
    db.commit()
    if c.status == "error":
        raise HTTPException(400, c.error)
    return comp_out(c)


@router.get("/compilations/{id}/download")
def download(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    c = get_comp(db, id, owner)
    if c.status != "done" or not c.output_name:
        raise HTTPException(409, "Compilation has not been exported yet")
    return FileResponse(safe_join(DIRS["compilations"], c.output_name), media_type="application/pdf", filename=cs.download_name(c))


@router.delete("/compilations/{id}")
def delete(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    c = get_comp(db, id, owner)
    if c.output_name:
        safe_join(DIRS["compilations"], c.output_name).unlink(missing_ok=True)
    db.delete(c)
    db.commit()
    return {"ok": True}


class MergeAllIn(BaseModel):
    title: str = "Merged Reports"
    options: Options = Options()


@router.post("/compilations/merge-all")
def merge_all(body: MergeAllIn = MergeAllIn(), db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    """One step: merge every processed report (upload order) into a single PDF."""
    docs = [d for d in db.scalars(select(Document).where(Document.owner == owner).order_by(Document.uploaded_at))
            if d.status in ("processed", "needs_review") and d.pages]
    if not docs:
        raise HTTPException(400, "No processed reports to merge yet.")
    check_pdf_quota(db, owner)
    c = Compilation(owner=owner, title=body.title.strip() or "Merged Reports",
                    items=[Item(document_id=d.id, title=d.title).model_dump() for d in docs],
                    options=body.options.model_dump())
    db.add(c)
    db.commit()
    return export(c.id, db, owner)


@router.get("/export/text")
def export_text(format: str = "txt", ids: str = "", db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    """All extracted text (edits included) of the processed reports in ONE text-only file."""
    if format not in ("txt", "pdf"):
        raise HTTPException(400, "format must be txt or pdf")
    want = {i for i in ids.split(",") if re.fullmatch(r"[0-9a-f]{32}", i)}
    data = []
    for d in db.scalars(select(Document).where(Document.owner == owner).order_by(Document.uploaded_at)):
        if d.status in ("processed", "needs_review") and (not want or d.id in want):
            live = [p for p in d.pages if not p.deleted]
            data.append({"title": d.title, "pages": [{"number": i + 1, "blocks": p.blocks, "tables": p.tables} for i, p in enumerate(live)]})
    if not data:
        raise HTTPException(400, "No processed reports to export yet.")
    path = DIRS["exports"] / f"{uuid.uuid4().hex}.{format}"
    if format == "txt":
        path.write_text(ts.to_txt(data), encoding="utf-8-sig")  # BOM so Windows Notepad reads it correctly
    else:
        with limits.heavy():
            ts.to_pdf(data, path)
    return FileResponse(path, media_type="text/plain" if format == "txt" else "application/pdf",
                        filename=f"Merged_Text_{dt.date.today():%Y-%m-%d}.{format}",
                        background=BackgroundTask(lambda: path.unlink(missing_ok=True)))
