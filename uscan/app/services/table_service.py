"""Schema-free table detection: ruled grids (OpenCV lines) first, then borderless alignment analysis."""
import statistics
import cv2
import numpy as np
from ..config import LOW_CONF


def _cluster(vals, tol):
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def _cell_text(words, box, hmed):
    x0, y0, x1, y1 = box
    ws = [w for w in words if x0 <= (w.x0 + w.x1) / 2 <= x1 and y0 <= (w.y0 + w.y1) / 2 <= y1]
    ws.sort(key=lambda w: (round((w.y0 + w.y1) / 2 / max(hmed, 1)), w.x0))
    conf = min((w.conf for w in ws), default=100)
    return " ".join(w.text for w in ws), conf


def _cell(text, conf, span=1):
    return {"text": text, "colspan": span, "needs_review": bool(text) and conf < LOW_CONF}


def _ruled(gray, words, W, H, hmed):
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10)
    hm = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(W // 25, 20), 1)))
    vm = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(H // 30, 20))))
    grid = cv2.dilate(cv2.bitwise_or(hm, vm), np.ones((7, 7), np.uint8))
    tables = []
    for c in cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(c)
        if w < W * 0.15 or h < 30:
            continue
        rh, rv = hm[y:y + h, x:x + w], vm[y:y + h, x:x + w]
        ys = [y + v for v in _cluster(np.where(rh.sum(axis=1) > 0.5 * w * 255)[0], 6)]
        xs = [x + v for v in _cluster(np.where(rv.sum(axis=0) > 0.35 * h * 255)[0], 6)]
        if len(ys) < 2 or len(xs) < 2:
            continue
        rows = []
        for r in range(len(ys) - 1):
            y0, y1 = int(ys[r]), int(ys[r + 1])
            row, start = [], 0
            for j in range(1, len(xs)):
                sep_present = j == len(xs) - 1 or vm[y0:y1, max(int(xs[j]) - 3, 0):int(xs[j]) + 3].any(axis=1).mean() >= 0.5
                if sep_present:
                    t, cf = _cell_text(words, (xs[start], y0, xs[j], y1), hmed)
                    row.append(_cell(t, cf, j - start))
                    start = j
            rows.append(row)
        tables.append({"kind": "ruled", "bbox": [xs[0], ys[0], xs[-1], ys[-1]], "rows": rows})
    return tables


def _borderless(words, W, hmed):
    lines = {}
    for w in words:
        lines.setdefault(w.line, []).append(w)
    rows = []
    for ws in sorted(lines.values(), key=lambda l: min(w.y0 for w in l)):
        ws.sort(key=lambda w: w.x0)
        segs, cur = [], [ws[0]]
        for a, b in zip(ws, ws[1:]):
            if b.x0 - a.x1 > 1.6 * hmed:
                segs.append(cur)
                cur = []
            cur.append(b)
        segs.append(cur)
        rows.append(segs)
    tables, run = [], []
    for segs in rows + [[]]:
        if len(segs) >= 3:
            run.append(segs)
            continue
        if len(run) >= 3:
            starts = _cluster([s[0].x0 for r in run for s in r], 0.03 * W)
            grid = []
            for r in run:
                cells = [[] for _ in starts]
                for s in r:
                    k = max((i for i, st in enumerate(starts) if st <= s[0].x0 + 0.02 * W), default=0)
                    cells[k] += s
                grid.append([_cell(" ".join(w.text for w in c), min((w.conf for w in c), default=100)) for c in cells])
            allw = [w for r in run for s in r for w in s]
            tables.append({"kind": "borderless", "bbox": [min(w.x0 for w in allw), min(w.y0 for w in allw), max(w.x1 for w in allw), max(w.y1 for w in allw)], "rows": grid})
        run = []
    return tables


def detect_tables(gray: np.ndarray, words: list) -> list[dict]:
    """words are in pixel coordinates of `gray`. Returns tables with normalised bbox."""
    H, W = gray.shape[:2]
    hmed = statistics.median([w.y1 - w.y0 for w in words]) if words else 20
    found = _ruled(gray, words, W, H, hmed)
    if not found and words:
        found = _borderless(words, W, hmed)
    out = []
    for i, t in enumerate(found):
        x0, y0, x1, y1 = t["bbox"]
        out.append({"id": f"t{i}", "kind": t["kind"], "bbox": [x0 / W, y0 / H, x1 / W, y1 / H], "rows": t["rows"]})
    return out
