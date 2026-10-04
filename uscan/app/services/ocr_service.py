"""Pluggable OCR: subclass OCREngine and register it in ENGINES."""
import os
import re
import statistics
from dataclasses import dataclass
import cv2
import numpy as np
from ..config import LOW_CONF, OCR_ENGINE, OCR_LANG


@dataclass
class Word:
    text: str
    conf: float
    x0: float
    y0: float
    x1: float
    y1: float
    line: tuple = (0, 0, 0)


class OCREngine:
    name = "base"

    def recognize(self, gray: np.ndarray) -> list[Word]:
        raise NotImplementedError


class TesseractEngine(OCREngine):
    name = "tesseract"

    def recognize(self, gray):
        import pytesseract
        if os.getenv("TESSERACT_CMD"):
            pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD")
        d = pytesseract.image_to_data(gray, lang=OCR_LANG, config="--psm 3", output_type=pytesseract.Output.DICT, timeout=120)
        out = []
        for i, t in enumerate(d["text"]):
            if t.strip() and float(d["conf"][i]) >= 0:
                x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
                out.append(Word(t.strip(), float(d["conf"][i]), x, y, x + w, y + h,
                                (d["block_num"][i], d["par_num"][i], d["line_num"][i])))
        return out


class EasyOCREngine(OCREngine):  # optional fallback: pip install easyocr
    name = "easyocr"

    def recognize(self, gray):
        import easyocr
        if not hasattr(self, "_r"):
            self._r = easyocr.Reader([OCR_LANG[:2]], gpu=False)
        out = []
        for n, (box, text, conf) in enumerate(self._r.readtext(gray)):
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            out.append(Word(text, conf * 100, min(xs), min(ys), max(xs), max(ys), (0, 0, n)))
        return out


ENGINES = {"tesseract": TesseractEngine, "easyocr": EasyOCREngine}


def get_engine() -> OCREngine:
    return ENGINES.get(OCR_ENGINE, TesseractEngine)()


def recognize(gray) -> list[Word]:
    try:
        return get_engine().recognize(gray)
    except Exception:
        if OCR_ENGINE != "tesseract":
            return TesseractEngine().recognize(gray)  # fall back
        raise


def detect_rotation(gray: np.ndarray) -> int:
    """Clockwise degrees needed to make the page upright (0/90/180/270); 0 when unsure."""
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT, timeout=30)
        return int(osd["rotate"]) if float(osd["orientation_conf"]) >= 2 else 0
    except Exception:
        return 0


def rotate90(img: np.ndarray, deg: int) -> np.ndarray:
    code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(deg % 360)
    return cv2.rotate(img, code) if code is not None else img


TAGS = {
    "date": r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4})\b",
    "amount": r"[₱$€£]\s?\d[\d,]*(\.\d+)?|\b\d{1,3}(,\d{3})+(\.\d+)?\b",
    "email": r"\b[\w.+-]+@[\w-]+\.[\w.]+\b",
    "id": r"\b[A-Z]{1,4}[-/]?\d{3,}\b|\b\d{2,}-\d{2,}(-\d+)*\b",
    "checkbox": r"[☐☑☒□■]|\[\s?[xX ]?\s?\]",
}


def build_blocks(words: list[Word]) -> list[dict]:
    """Group words into lines and classify them. Coordinates must already be normalised 0..1."""
    lines: dict = {}
    for w in words:
        lines.setdefault(w.line, []).append(w)
    if not lines:
        return []
    med_h = statistics.median(max(w.y1 - w.y0, 1e-6) for w in words)
    blocks = []
    for ws in sorted(lines.values(), key=lambda l: (min(w.y0 for w in l), min(w.x0 for w in l))):
        ws.sort(key=lambda w: w.x0)
        text = " ".join(w.text for w in ws)
        conf = sum(w.conf for w in ws) / len(ws)
        h = statistics.median(w.y1 - w.y0 for w in ws)
        bbox = [min(w.x0 for w in ws), min(w.y0 for w in ws), max(w.x1 for w in ws), max(w.y1 for w in ws)]
        if h > 1.35 * med_h and len(ws) <= 10 or (len(ws) <= 6 and text.isupper() and len(text) > 3):
            kind = "heading"
        elif re.match(r"^[^:]{1,40}:\s*\S", text):
            kind = "field"
        else:
            kind = "text"
        low = any(w.conf < LOW_CONF for w in ws)
        blocks.append({
            "id": f"b{len(blocks)}", "kind": kind, "text": text, "words": [[w.text, round(w.conf)] for w in ws],
            "conf": round(conf, 1), "bbox": [round(v, 4) for v in bbox], "needs_review": low, "edited": False,
            "tags": [k for k, rx in TAGS.items() if re.search(rx, text)] + (["page_number"] if re.fullmatch(r"(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?", text.strip(), re.I) else []),
        })
    return blocks
