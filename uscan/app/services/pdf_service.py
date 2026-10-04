"""PDF reading (PyMuPDF) and generation (ReportLab front matter + PyMuPDF assembly / invisible OCR layer)."""
import io
import cv2
import pymupdf as fitz  # PyMuPDF
import numpy as np
from reportlab.lib.pagesizes import A4, LEGAL, LETTER
from reportlab.pdfgen import canvas
from .ocr_service import Word

SIZES = {"A4": A4, "LETTER": LETTER, "LEGAL": LEGAL}
MAX_RENDER_PIXELS = 40_000_000


def render_page(page: "fitz.Page", dpi=200) -> np.ndarray:
    r = page.rect
    dpi = min(dpi, (MAX_RENDER_PIXELS / max(r.width * r.height, 1)) ** 0.5 * 72)  # cap pixels, not just dpi
    pix = page.get_pixmap(dpi=max(dpi, 20), colorspace=fitz.csRGB, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3)[:, :, ::-1].copy()


def is_digital(page: "fitz.Page") -> bool:
    return len(page.get_text("text").strip()) >= 25


def digital_words(page: "fitz.Page") -> list[Word]:
    r = page.rect
    return [Word(w[4], 100.0, w[0] / r.width, w[1] / r.height, w[2] / r.width, w[3] / r.height, (w[5], w[6], 0))
            for w in page.get_text("words") if w[4].strip()]


def digital_tables(page: "fitz.Page") -> list[dict]:
    out = []
    try:
        r = page.rect
        for i, t in enumerate(page.find_tables().tables):
            rows = [[{"text": (c or "").strip(), "colspan": 1, "needs_review": False} for c in row] for row in t.extract()]
            x0, y0, x1, y1 = t.bbox
            if rows and len(rows[0]) > 1:
                out.append({"id": f"t{i}", "kind": "digital", "bbox": [x0 / r.width, y0 / r.height, x1 / r.width, y1 / r.height], "rows": rows})
    except Exception:
        pass
    return out


def _canvas_pages(size, specs):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    W, H = size
    for s in specs:
        c.setFont("Helvetica-Bold", 26 if s["kind"] != "toc" else 18)
        c.drawCentredString(W / 2, H * (0.6 if s["kind"] != "toc" else 0.9), s["title"][:70])
        c.setFont("Helvetica", 12)
        if s.get("subtitle"):
            c.drawCentredString(W / 2, H * 0.53, s["subtitle"][:90])
        y = H * 0.84
        for left, right in s.get("lines", []):
            c.drawString(60, y, left[:80])
            c.drawRightString(W - 60, y, right)
            y -= 18
        c.showPage()
    c.save()
    return fitz.open(stream=buf.getvalue(), filetype="pdf")


def _target_size(opt: str, w: float, h: float):
    if opt in SIZES:
        a, b = sorted(SIZES[opt])
        return (b, a) if w > h else (a, b)
    if "x" in opt:
        try:
            a, b = (float(v) for v in opt.lower().split("x"))
            if 36 <= a <= 5000 and 36 <= b <= 5000:
                return a, b
        except ValueError:
            pass
    return w, h


def add_page(out, page, src_path, cache, image_path, opts):
    tw, th = _target_size(opts["page_size"], page.width_pt, page.height_pt)
    np_ = out.new_page(width=tw, height=th)
    s = min(tw / page.width_pt, th / page.height_pt)
    rw, rh = page.width_pt * s, page.height_pt * s
    x0, y0 = (tw - rw) / 2, (th - rh) / 2
    rect = fitz.Rect(x0, y0, x0 + rw, y0 + rh)
    if page.kind == "digital":
        src = cache.setdefault(str(src_path), fitz.open(str(src_path)))
        np_.show_pdf_page(rect, src, page.src_index)
        return
    data = image_path.read_bytes()
    if opts["quality"] == "optimized":
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
    np_.insert_image(rect, stream=data)
    if opts["text_layer"]:  # invisible text: page looks identical but is searchable/selectable
        for b in page.blocks or []:
            bx0, by0, bx1, by1 = b["bbox"]
            fs = max(3.0, (by1 - by0) * rh * 0.85)
            try:
                np_.insert_text(fitz.Point(x0 + bx0 * rw, y0 + by1 * rh - fs * 0.2), b["text"], fontsize=fs, render_mode=3)
            except Exception:
                pass


def stamp(out, first_numbered: int, opts):
    for i, p in enumerate(out):
        w, h = p.rect.width, p.rect.height
        if opts["header"]:
            p.insert_text(fitz.Point((w - fitz.get_text_length(opts["header"], fontsize=9)) / 2, 22), opts["header"], fontsize=9)
        if opts["footer"]:
            p.insert_text(fitz.Point(36, h - 16), opts["footer"], fontsize=9)
        if opts["page_numbers"] and i >= first_numbered:
            t = str(i + 1)
            p.insert_text(fitz.Point(w - 36 - fitz.get_text_length(t, fontsize=9), h - 16), t, fontsize=9)
