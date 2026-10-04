from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .. import config
from ..database import get_db
from ..models.compilation import Compilation
from ..schemas.compilation import CompilationIn, comp_out
from ..services import compilation_service as cs
from ..services.workspace_service import get_owner
from ..utils.limits import LimitError
from ..utils.security import require_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def get_comp(db, id_, owner) -> Compilation:
    c = db.get(Compilation, id_)
    if not c or c.owner != owner:
        raise HTTPException(404, "Compilation not found")
    return c


def check_pdf_quota(db, owner):
    cap = config.MAX_WORKSPACE_PDFS
    if cap and db.scalar(select(func.count()).select_from(Compilation).where(Compilation.owner == owner, Compilation.status != "error")) >= cap:
        raise LimitError(f"You can keep up to {cap} compiled PDFs. Delete an old one to make a new one.", 409)


@router.post("/compilations")
def create(body: CompilationIn, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    c = Compilation(owner=owner, title=body.title.strip() or "Compiled Report", items=[i.model_dump() for i in body.items], options=body.options.model_dump())
    try:
        cs.resolve(db, c.items, owner)  # validates the selection AND that every document is yours
    except ValueError as e:
        raise HTTPException(400, str(e))
    check_pdf_quota(db, owner)
    db.add(c)
    db.commit()
    return comp_out(c)


@router.get("/compilations")
def list_(db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    return [comp_out(c) for c in db.scalars(select(Compilation).where(Compilation.owner == owner).order_by(Compilation.created_at.desc()))]


@router.get("/compilations/{id}")
def get(id: str, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    return comp_out(get_comp(db, id, owner))
