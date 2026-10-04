from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from .. import config
from ..utils import security as sec

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    password: str = Field(max_length=256)


@router.get("/session")
def session(request: Request):
    """Public: tells the UI whether to show the sign-in page, plus its (non-sensitive) limits."""
    return {"auth_required": sec.auth_enabled(), "authenticated": sec.is_authenticated(request),
            "max_upload_mb": config.MAX_UPLOAD_MB, "max_files": config.MAX_FILES_PER_UPLOAD,
            "extensions": sorted(sec.ALLOWED_EXT), "low_conf": config.LOW_CONF,
            "public": config.PUBLIC_MODE, "ttl_hours": config.WORKSPACE_TTL_HOURS if config.PUBLIC_MODE else 0}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    wait = sec.login_allowed(ip)
    if wait:
        raise HTTPException(429, f"Too many attempts. Try again in {wait // 60 + 1} min.", headers={"Retry-After": str(wait)})
    secret = sec.ui_password()
    if secret and not sec._eq(body.password, secret):
        sec.login_failed(ip)
        raise HTTPException(401, "Incorrect password.")
    sec.login_ok(ip)
    if secret:
        response.set_cookie(sec.SESSION_COOKIE, sec.create_session(), max_age=config.SESSION_HOURS * 3600, httponly=True,
                            samesite="strict", secure=config.COOKIE_SECURE or request.url.scheme == "https", path="/")
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response):
    sec.end_session(request.cookies.get(sec.SESSION_COOKIE))
    response.delete_cookie(sec.SESSION_COOKIE, path="/")
    return {"ok": True}
