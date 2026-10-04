import re
import uuid
from pydantic import BaseModel, Field

MAX_TEXT, MAX_BLOCKS = 2000, 5000
_ID = re.compile(r"[\w\-]{1,40}")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class DocPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class PagePatch(BaseModel):
    blocks: list[dict] | None = Field(default=None, max_length=MAX_BLOCKS)
    tables: list[dict] | None = Field(default=None, max_length=100)
    reviewed: bool | None = None


class OrderIn(BaseModel):
    page_ids: list[str] = Field(max_length=2000)


def _text(v) -> str:
    return _CTRL.sub("", str(v if v is not None else ""))[:MAX_TEXT]


def clean_blocks(incoming: list[dict], existing: list[dict]) -> list[dict]:
    """Only the text of known lines can change; user-added lines get a fully server-built record.
    Raises ValueError on malformed input (the API turns that into a 422)."""
    old = {b.get("id"): b for b in existing}
    out = []
    for b in incoming:
        if not isinstance(b, dict):
            raise ValueError("Invalid line data.")
        text, o = _text(b.get("text")), old.get(b.get("id"))
        if o:
            edited = bool(o.get("edited")) or text != o.get("text", "")
            out.append({**o, "text": text, "edited": edited, **({"needs_review": False} if edited else {})})
            continue
        try:
            bbox = [min(1.0, max(0.0, float(v))) for v in list(b.get("bbox") or [0.05, 0.05, 0.95, 0.08])]
        except (TypeError, ValueError):
            raise ValueError("Invalid line position.")
        if len(bbox) != 4:
            raise ValueError("Invalid line position.")
        bid = str(b.get("id", ""))
        out.append({"id": bid if _ID.fullmatch(bid) else uuid.uuid4().hex[:12], "kind": "text", "text": text, "words": [],
                    "conf": 100, "bbox": bbox, "needs_review": False, "edited": True, "tags": []})
    return out


def clean_tables(incoming: list[dict], existing: list[dict]) -> list[dict]:
    """Table shape is fixed by the scan: only cell text may change (an edited cell stops needing review)."""
    def bad():
        return ValueError("Table data does not match this page. Reload the page and try again.")
    if len(incoming) != len(existing):
        raise bad()
    out = []
    for nt, ot in zip(incoming, existing):
        rows_in = nt.get("rows") if isinstance(nt, dict) else None
        if not isinstance(rows_in, list) or len(rows_in) != len(ot["rows"]):
            raise bad()
        rows = []
        for rin, rold in zip(rows_in, ot["rows"]):
            if not isinstance(rin, list) or len(rin) != len(rold):
                raise bad()
            row = []
            for cin, cold in zip(rin, rold):
                text = _text(cin.get("text") if isinstance(cin, dict) else None)
                row.append({**cold, "text": text, "needs_review": False if text != cold.get("text", "") else cold.get("needs_review", False)})
            rows.append(row)
        out.append({**ot, "rows": rows})
    return out


def doc_out(d) -> dict:
    live = [p for p in d.pages if not p.deleted]
    return {
        "id": d.id, "filename": d.original_filename, "title": d.title, "file_type": d.file_type,
        "uploaded_at": d.uploaded_at.isoformat(), "processed_at": d.processed_at.isoformat() if d.processed_at else None,
        "pages": len(live), "status": d.status, "ocr_status": d.ocr_status,
        "confidence": round(d.confidence, 1) if d.confidence is not None else None,
        "reviewed_pages": sum(1 for p in live if p.reviewed), "error": d.error,
    }


def page_out(p) -> dict:
    return {
        "id": p.id, "document_id": p.document_id, "position": p.position, "kind": p.kind,
        "reviewed": p.reviewed, "confidence": round(p.confidence, 1) if p.confidence is not None else None,
        "flags": p.flags, "blocks": p.blocks or [], "tables": p.tables or [], "ops": p.ops or [],
        "error": p.error, "image": f"/api/pages/{p.id}/image", "width_pt": p.width_pt, "height_pt": p.height_pt,
    }
