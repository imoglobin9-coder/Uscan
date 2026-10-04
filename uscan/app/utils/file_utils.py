import os
import shutil
import tempfile
import time
from pathlib import Path
from ..config import DIRS, MAX_UPLOAD_MB
from .security import safe_join, validate_upload


def save_upload(fileobj, filename: str, doc_id: str) -> tuple[str, str]:
    """Stream to a temp file with size limit, validate magic bytes, move to uploads/<uuid>.<ext>."""
    head = fileobj.read(16)
    fileobj.seek(0)
    ext = validate_upload(filename, head)
    limit = MAX_UPLOAD_MB * 1024 * 1024
    fd, tmp = tempfile.mkstemp(dir=DIRS["tmp"], suffix=".part")
    try:
        size = 0
        with os.fdopen(fd, "wb") as t:
            while chunk := fileobj.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise ValueError(f"File exceeds the {MAX_UPLOAD_MB} MB limit.")
                t.write(chunk)
        stored = f"{doc_id}{ext}"
        shutil.move(tmp, safe_join(DIRS["uploads"], stored))
        return stored, ext
    finally:
        Path(tmp).unlink(missing_ok=True)


def cleanup_tmp(max_age_s: int = 3600):
    now = time.time()
    for f in DIRS["tmp"].glob("*"):
        try:
            if now - f.stat().st_mtime > max_age_s:
                f.unlink()
        except OSError:
            pass
