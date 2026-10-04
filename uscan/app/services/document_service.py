import datetime as dt
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import cv2
import pymupdf as fitz
import numpy as np
from PIL import Image, ImageOps, ImageSequence
from sqlalchemy import func, select, update
from .. import config
from ..config import DIRS, LOW_CONF, MAX_IMAGE_PIXELS, MAX_PAGES
from ..database import SessionLocal
from ..models.document import Document, uid
from ..models.page import Page
from ..utils.file_utils import save_upload
from ..utils.image_utils import imread, imwrite_png, jpeg_bytes
from ..utils import limits
from ..utils.security import safe_name
from . import image_service as IS, ocr_service as OCR, pdf_service as PS, table_service as TS

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS  # Pillow raises DecompressionBombError above 2x this
JOBS: dict[str, dict] = {}
_pool = ThreadPoolExecutor(max_workers=1)  # one OCR worker: uploads from everyone queue up behind it
_jobs_lock = threading.Lock()


def create_from_upload(db, up, owner: str = "local") -> Document:
    if config.MAX_WORKSPACE_DOCS and db.scalar(select(func.count()).select_from(Document).where(Document.owner == owner)) >= config.MAX_WORKSPACE_DOCS:
        raise ValueError(f"Your workspace holds up to {config.MAX_WORKSPACE_DOCS} reports. Delete one to add more.")
    doc_id = uid()
    stored, ext = save_upload(up.file, up.filename, doc_id)
    size = (DIRS["uploads"] / stored).stat().st_size
    if config.MAX_WORKSPACE_MB:
        used = db.scalar(select(func.coalesce(func.sum(Document.size_bytes), 0)).where(Document.owner == owner))
        if used + size > config.MAX_WORKSPACE_MB * 1048576:
            (DIRS["uploads"] / stored).unlink(missing_ok=True)
            raise ValueError(f"Your workspace is full ({config.MAX_WORKSPACE_MB} MB). Delete a report to make room.")
    name = safe_name(up.filename)
    d = Document(id=doc_id, original_filename=name, title=Path(name).stem, file_type=ext.lstrip("."), stored_name=stored,
                 owner=owner, size_bytes=size)
    db.add(d)
    db.commit()
    return d


def _paths(doc_id, page_id):
    (DIRS["processed"] / doc_id).mkdir(exist_ok=True)
    (DIRS["previews"] / doc_id).mkdir(exist_ok=True)
    return DIRS["processed"] / doc_id / f"{page_id}.png", DIRS["previews"] / doc_id / f"{page_id}.jpg"


def analyze(display: np.ndarray) -> dict:
    """OCR + blocks + tables on an already-geometrically-corrected page image."""
    gray, scale, ops = IS.ocr_gray(display)
    rot = OCR.detect_rotation(gray)
    if rot:
        display = OCR.rotate90(display, rot)
        gray, scale, ops = IS.ocr_gray(display)
        ops.append(f"rotate {rot}°")
    words = OCR.recognize(IS.remove_rules(gray))
    tables = TS.detect_tables(gray, words)
    H, W = gray.shape
    norm = [OCR.Word(w.text, w.conf, w.x0 / W, w.y0 / H, w.x1 / W, w.y1 / H, w.line) for w in words]
    return {"display": display, "blocks": OCR.build_blocks(norm), "tables": tables, "ops": ops}


def _stats(blocks, tables):
    conf = [b["conf"] for b in blocks]
    flags = sum(b["needs_review"] for b in blocks) + sum(c["needs_review"] for t in tables for r in t["rows"] for c in r)
    return (sum(conf) / len(conf) if conf else None), flags


def _fill(page: Page, blocks, tables, ops):
    page.blocks, page.tables, page.ops = blocks, tables, ops
    page.confidence, page.flags = _stats(blocks, tables)


def _save_scanned(page: Page, doc_id: str, display: np.ndarray, dpi: float):
    proc, prev = _paths(doc_id, page.id)
    imwrite_png(proc, display)
    prev.write_bytes(jpeg_bytes(display, 80, 1100))
    page.width_pt, page.height_pt = display.shape[1] * 72 / dpi, display.shape[0] * 72 / dpi


def _scan_page(page, doc_id, bgr, dpi):
    display, ops0 = IS.geometric(bgr)
    r = analyze(display)
    page.kind = "scanned"
    _save_scanned(page, doc_id, r["display"], dpi)
    _fill(page, r["blocks"], r["tables"], ops0 + r["ops"])


def _digital_page(page, doc_id, fpage):
    _, prev = _paths(doc_id, page.id)
    prev.write_bytes(jpeg_bytes(PS.render_page(fpage, 110), 80, 1100))
    page.kind, page.width_pt, page.height_pt = "digital", fpage.rect.width, fpage.rect.height
    _fill(page, OCR.build_blocks(PS.digital_words(fpage)), PS.digital_tables(fpage), ["selectable text"])


def _sources(path: Path, ext: str, limit: int = MAX_PAGES):
    """Yield (index, fitz_page_or_None, bgr_or_None, dpi). `limit` = pages this report may still use."""
    if ext == ".pdf":
        with fitz.open(str(path)) as src:
            if src.page_count > MAX_PAGES:
                raise limits.LimitError(f"This report has more than {MAX_PAGES} pages, which is the limit per report.")
            if src.page_count > limit:
                raise limits.LimitError(f"This report has {src.page_count} pages but your workspace only has room for {limit} more. Delete another report first.")
            for i, fp in enumerate(src):
                yield i, (fp if PS.is_digital(fp) else None), (None if PS.is_digital(fp) else PS.render_page(fp, 200)), 200
        return
    with Image.open(path) as im:
        for i, fr in enumerate(ImageSequence.Iterator(im)):
            if i >= limit:
                break
            dpi = float(fr.info.get("dpi", (200,))[0] or 200)
            dpi = dpi if 72 <= dpi <= 600 else 200
            fr = ImageOps.exif_transpose(fr.convert("RGB"))
            if max(fr.size) > 7000:
                fr.thumbnail((7000, 7000))
            yield i, None, np.asarray(fr)[:, :, ::-1].copy(), dpi


def process_document(db, doc: Document, progress=None, budget: int | None = None):
    path = DIRS["uploads"] / doc.stored_name
    doc.status, doc.ocr_status, doc.error = "processing", "running", None
    for p in list(doc.pages):
        db.delete(p)
    db.commit()
    n, made = 0, []  # `made`: the pages created in this run (doc.pages is not refreshed until the session flushes)
    limit = MAX_PAGES if budget is None else min(MAX_PAGES, budget)
    try:
        with fitz.open(str(path)) as f:
            total = f.page_count if doc.file_type == "pdf" else 0
    except Exception:
        total = 0
    try:
        for i, fp, bgr, dpi in _sources(path, "." + doc.file_type, limit):
            if progress:
                progress(page=i + 1, pages=total or i + 1, op="Running OCR..." if bgr is not None else "Reading text...")
            pg = Page(id=uid(), document_id=doc.id, position=n, src_index=i)  # id is needed now: image paths are built from it before the row is flushed
            try:
                if fp is not None:
                    _digital_page(pg, doc.id, fp)
                else:
                    _scan_page(pg, doc.id, bgr, dpi)
            except Exception:
                pg.error, pg.flags, pg.kind = "Page could not be processed; please review or rescan.", 1, "scanned"
            db.add(pg)
            made.append(pg)
            n += 1
        doc.page_count = n
        confs = [p.confidence for p in made if p.confidence is not None]
        doc.confidence = sum(confs) / len(confs) if confs else None
        doc.status = "needs_review" if any(p.flags for p in made) else "processed"
        doc.ocr_status, doc.processed_at = "complete", dt.datetime.utcnow()
    except limits.LimitError as e:  # our own, visitor-safe message (page limits)
        doc.status, doc.ocr_status, doc.error = "error", "failed", str(e)
    except Exception:
        doc.status, doc.ocr_status = "error", "failed"
        doc.error = f"{doc.title} could not be processed. Please review or upload a clearer copy."
    db.commit()


def rescan_page(db, page: Page):
    doc = db.get(Document, page.document_id)
    proc, _ = _paths(doc.id, page.id)
    if page.kind == "digital":
        with fitz.open(str(DIRS["uploads"] / doc.stored_name)) as src:
            _digital_page(page, doc.id, src[page.src_index])
    else:
        r = analyze(imread(proc))
        imwrite_png(proc, r["display"])
        _fill(page, r["blocks"], r["tables"], r["ops"])
    page.reviewed = False
    refresh_doc(db, doc)


def rotate_page(db, page: Page, deg: int):
    doc = db.get(Document, page.document_id)
    proc, _ = _paths(doc.id, page.id)
    if page.kind == "digital":  # convert to raster so rotation is baked in and OCR layer matches
        with fitz.open(str(DIRS["uploads"] / doc.stored_name)) as src:
            img = PS.render_page(src[page.src_index], 200)
        page.kind = "scanned"
    else:
        img = imread(proc)
    img = OCR.rotate90(img, deg)
    r = analyze(img)
    old_w, old_h = page.width_pt, page.height_pt
    _save_scanned(page, doc.id, r["display"], 200)
    page.width_pt, page.height_pt = (old_h, old_w) if deg in (90, 270) else (old_w, old_h)  # keep physical size
    _fill(page, r["blocks"], r["tables"], r["ops"])
    page.reviewed = False
    refresh_doc(db, doc)


def refresh_doc(db, doc: Document):
    live = [p for p in doc.pages if not p.deleted]
    confs = [p.confidence for p in live if p.confidence is not None]
    doc.confidence = sum(confs) / len(confs) if confs else None
    if doc.status in ("processed", "needs_review"):
        doc.status = "needs_review" if any(p.flags and not p.reviewed for p in live) else "processed"
    doc.page_count = len(live)
    db.commit()


def _budget(db, owner: str, exclude_id: str) -> int | None:
    """Pages this workspace may still add (None = no cap)."""
    if not config.MAX_WORKSPACE_PAGES:
        return None
    used = db.scalar(select(func.coalesce(func.sum(Document.page_count), 0)).where(Document.owner == owner, Document.id != exclude_id))
    return max(0, config.MAX_WORKSPACE_PAGES - used)


def has_active_job(owner: str) -> bool:
    with _jobs_lock:
        return any(j["owner"] == owner and not j["done"] for j in JOBS.values())


def check_capacity(owner: str):
    """Public mode: one batch at a time per visitor, a site-wide queue cap, and a disk guard."""
    if not config.PUBLIC_MODE:
        return
    with _jobs_lock:
        if any(j["owner"] == owner and not j["done"] for j in JOBS.values()):
            raise limits.LimitError("Still reading your previous files. Please wait for them to finish, then add more.")
        queued = sum(j["total"] - len(j["results"]) for j in JOBS.values() if not j["done"])
    if config.MAX_QUEUED_DOCS and queued >= config.MAX_QUEUED_DOCS:
        raise limits.LimitError("uscan is busy right now. Please try again in a few minutes.", 503)
    limits.require_disk()


def reset_interrupted():
    """After a restart no job is running, so anything still 'processing' or 'queued' was cut off."""
    with SessionLocal() as db:
        db.execute(update(Document).where(Document.status.in_(("processing", "uploaded")))
                   .values(status="error", ocr_status="failed", error="Reading was interrupted. Use Retry to read it again."))
        db.commit()


def start_job(doc_ids: list[str], owner: str = "local") -> str:
    job_id, now = uuid.uuid4().hex, time.time()
    with _jobs_lock:
        for k in [k for k, j in JOBS.items() if j["done"] and now - (j["finished"] or now) > 600]:  # finished jobs live 10 min
            JOBS.pop(k, None)
        JOBS[job_id] = {"id": job_id, "owner": owner, "total": len(doc_ids), "index": 0, "doc": "", "page": 0, "pages": 0,
                        "op": "Queued", "percent": 0, "done": False, "finished": None, "results": []}
    _pool.submit(_run_job, job_id, doc_ids)
    return job_id


def _run_job(job_id, doc_ids):
    job = JOBS[job_id]
    try:
        for k, did in enumerate(doc_ids):
            db = SessionLocal()
            try:
                doc = db.get(Document, did)
                job.update(index=k + 1, doc=doc.title, page=0, pages=0)

                def cb(page, pages, op, k=k):
                    job.update(page=page, pages=pages, op=op, percent=int(100 * (k + page / max(pages, 1)) / job["total"]))
                process_document(db, doc, cb, _budget(db, job["owner"], did))
                job["results"].append({"id": did, "title": doc.title, "status": doc.status, "pages": doc.page_count,
                                       "flagged_pages": sum(1 for p in doc.pages if p.flags), "error": doc.error})
            except Exception:
                job["results"].append({"id": did, "status": "error", "error": "Document could not be processed."})
            finally:
                db.close()
            job["percent"] = int(100 * (k + 1) / job["total"])
    finally:
        job.update(done=True, op="Done", percent=100, finished=time.time())


def delete_files(doc: Document):
    for sub in ("processed", "previews"):
        shutil.rmtree(DIRS[sub] / doc.id, ignore_errors=True)
    (DIRS["uploads"] / doc.stored_name).unlink(missing_ok=True)
