from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from .. import config
from ..database import get_db
from ..services import document_service as svc
from ..services.workspace_service import COOKIE, get_owner, purge
from ..utils.limits import LimitError
from ..utils.security import require_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@router.delete("/workspace")
def wipe(response: Response, db: Session = Depends(get_db), owner: str = Depends(get_owner)):
    """'Delete my data': removes every report, page image and PDF of this visitor's workspace, right now."""
    if not config.PUBLIC_MODE:
        raise HTTPException(404, "Not found")
    if owner:
        if svc.has_active_job(owner):
            raise LimitError("Your files are still being read. Wait for that to finish, then delete.", 409)
        purge(db, owner)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
