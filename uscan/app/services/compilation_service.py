import datetime as dt
import re
import pymupdf as fitz
from ..config import DIRS
from ..models.document import Document
from ..models.page import Page
from . import pdf_service as PS


def parse_pages(spec: str, n: int) -> list[int]:
    """'all' or '1-3,5' -> zero-based indexes (validated, order preserved, no duplicates)."""
    spec = (spec or "all").strip().lower()
    if spec == "all":
        return list(range(n))
    out = []
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", part)
        if not m:
            raise ValueError(f"Invalid page selection: {spec!r}")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b < a or b > n:
            raise ValueError(f"Page selection {part.strip()!r} is outside 1-{n}.")
        out += [i for i in range(a - 1, b) if i not in out]
    return out


def resolve(db, items, owner: str) -> list[dict]:
    res = []
    for it in items:
        doc = db.get(Document, it["document_id"])
        if not doc or doc.owner != owner:  # someone else's document looks exactly like a missing one
            raise ValueError("A selected document no longer exists.")
        live = [p for p in doc.pages if not p.deleted]
        idx = parse_pages(it.get("pages", "all"), len(live))
        res.append({"doc": doc, "title": (it.get("title") or doc.title), "pages": [live[i] for i in idx]})
    return res


def build(db, comp) -> int:
    o, sections = comp.options, resolve(db, comp.items, comp.owner)
    if not any(s["pages"] for s in sections):
        raise ValueError("No pages selected.")
    first = next(p for s in sections for p in s["pages"])
    size = PS._target_size(o["page_size"], first.width_pt, first.height_pt)
    toc_lines_per_page = 38
    n_toc = -(-len(sections) // toc_lines_per_page) if o["toc"] else 0
    cur = (1 if o["cover"] else 0) + n_toc + 1
    starts = []
    for s in sections:
        cur += 1 if o["separators"] else 0
        starts.append(cur)
        cur += len(s["pages"])
    out = fitz.open()
    if o["cover"]:
        out.insert_pdf(PS._canvas_pages(size, [{"kind": "cover", "title": comp.title,
                       "subtitle": f"{len(sections)} reports · {dt.date.today():%B %d, %Y}"}]))
    for k in range(n_toc):
        chunk = list(zip(sections, starts))[k * toc_lines_per_page:(k + 1) * toc_lines_per_page]
        out.insert_pdf(PS._canvas_pages(size, [{"kind": "toc", "title": "Table of Contents",
                       "lines": [(s["title"], f"{st}") for s, st in chunk]}]))
    cache, toc = {}, []
    try:
        for s, st in zip(sections, starts):
            if o["separators"]:
                out.insert_pdf(PS._canvas_pages(size, [{"kind": "sep", "title": s["title"], "subtitle": f"{len(s['pages'])} pages"}]))
            toc.append([1, s["title"][:80], st])
            for pg in s["pages"]:
                PS.add_page(out, pg, DIRS["uploads"] / s["doc"].stored_name, cache,
                            DIRS["processed"] / pg.document_id / f"{pg.id}.png", o)
    finally:
        for c in cache.values():
            c.close()
    PS.stamp(out, 1 if o["cover"] else 0, o)
    out.set_toc(toc)
    out.set_metadata({"title": comp.title, "producer": "uscan"})
    name = f"{comp.id}.pdf"
    out.save(str(DIRS["compilations"] / name), garbage=3, deflate=True)
    n = len(out)
    out.close()
    comp.output_name = name
    return n


def download_name(comp) -> str:
    base = re.sub(r"[^\w\- ]", "", comp.title).strip().replace(" ", "_") or "Compiled_Report"
    return f"{base}_{comp.created_at:%Y-%m-%d}.pdf"
