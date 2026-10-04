"""Generate sample reports with *different* layouts (used by tests; run directly to write data/samples/)."""
from pathlib import Path
import cv2
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet


def table_pdf(path, header, rows, size=A4):
    doc = SimpleDocTemplate(str(path), pagesize=size)
    t = Table([header] + rows)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 11)]))
    doc.build([Paragraph("Quarterly Report", getSampleStyleSheet()["Title"]), Paragraph("Prepared on 09/29/2026. Total: 15,000.00", getSampleStyleSheet()["Normal"]), t])


def scanned_png(path, angle=3.0):
    img = np.full((1100, 850, 3), 255, np.uint8)
    for i in range(16):
        cv2.putText(img, f"Line {i}: Juan Dela Cruz 09/29/2026 amount 15,000.00", (50, 90 + i * 55), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2)
    m = cv2.getRotationMatrix2D((425, 550), angle, 1)
    img = cv2.warpAffine(img, m, (850, 1100), borderValue=(255, 255, 255))
    cv2.imwrite(str(path), img)


def make_all(d: Path) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    table_pdf(d / "report_a.pdf", ["Name", "Position", "Date"], [["Ana Cruz", "Manager", "09/01/2026"], ["Ben Lee", "Clerk", "09/02/2026"]])
    table_pdf(d / "report_b.pdf", ["Employee", "Department", "Amount", "Date"], [["Ana Cruz", "Sales", "15,000.00", "09/01/2026"], ["Ben Lee", "IT", "20,000.00", "09/02/2026"]], landscape(LETTER))
    scanned_png(d / "report_c.png")
    return {p.name: p for p in d.iterdir()}


if __name__ == "__main__":
    print(make_all(Path(__file__).resolve().parent.parent / "data" / "samples"))
