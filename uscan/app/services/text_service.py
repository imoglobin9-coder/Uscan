"""Merge the extracted TEXT of many reports into one text-only file (no page images)."""
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _inside(b, t) -> bool:
    cx, cy = (b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2
    x0, y0, x1, y1 = t["bbox"]
    return x0 <= cx <= x1 and y0 <= cy <= y1


def page_elements(page: dict) -> list[tuple[str, dict]]:
    """Reading-order text lines and tables; lines that belong to a table are not repeated."""
    tables = [t for t in page.get("tables") or [] if t.get("rows")]
    els = [("table", t["bbox"][1], t["bbox"][0], t) for t in tables]
    for b in page.get("blocks") or []:
        if b["text"].strip() and not any(_inside(b, t) for t in tables):
            els.append(("text", b["bbox"][1], b["bbox"][0], b))
    els.sort(key=lambda e: (round(e[1], 3), e[2]))
    return [(k, x) for k, _, _, x in els]


def _row_cells(row) -> list[str]:
    out = []
    for c in row:
        out += [c["text"]] + [""] * (c.get("colspan", 1) - 1)
    return out


def to_txt(docs: list[dict]) -> str:
    out = []
    for d in docs:
        out += ["=" * 70, d["title"], "=" * 70]
        for p in d["pages"]:
            out.append(f"\n--- Page {p['number']} ---")
            for kind, x in page_elements(p):
                out.append(x["text"] if kind == "text" else "\n".join(" | ".join(_row_cells(r)) for r in x["rows"]) + "\n")
        out.append("")
    return "\n".join(out)


def _table(t, style):
    ncols = max(sum(c.get("colspan", 1) for c in r) for r in t["rows"])
    data, spans = [], []
    for ri, r in enumerate(t["rows"]):
        row, ci = [], 0
        for c in r:
            span = c.get("colspan", 1)
            row += [Paragraph(escape(c["text"]), style)] + [""] * (span - 1)
            if span > 1:
                spans.append(("SPAN", (ci, ri), (ci + span - 1, ri)))
            ci += span
        data.append(row + [""] * (ncols - len(row)))
    tb = Table(data, repeatRows=1)
    tb.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")] + spans))
    return tb


def to_pdf(docs: list[dict], path, title="Merged Text"):
    ss = getSampleStyleSheet()
    small = ParagraphStyle("cell", parent=ss["BodyText"], fontSize=8, leading=10)
    story = [Paragraph(escape(title), ss["Title"])]
    for i, d in enumerate(docs):
        if i:
            story.append(PageBreak())
        story.append(Paragraph(escape(d["title"]), ss["Heading1"]))
        for p in d["pages"]:
            story.append(Paragraph(f"Page {p['number']}", ss["Heading3"]))
            for kind, x in page_elements(p):
                if kind == "text":
                    story.append(Paragraph(escape(x["text"]), ss["Heading2"] if x.get("kind") == "heading" else ss["BodyText"]))
                else:
                    story += [_table(x, small), Spacer(1, 8)]
    SimpleDocTemplate(str(path), pagesize=A4, title=title).build(story)
