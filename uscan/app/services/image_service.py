"""Adaptive preprocessing: each operation is applied only if the page measurably needs it."""
import cv2
import numpy as np


def skew_angle(gray: np.ndarray) -> float:
    bw = cv2.threshold(cv2.GaussianBlur(gray, (5, 5), 0), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    bw = cv2.dilate(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3)))
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles, weights = [], []
    for c in cnts:
        (_, _), (w, h), a = cv2.minAreaRect(c)
        if max(w, h) < gray.shape[1] * 0.08 or max(w, h) < 4 * min(w, h):  # keep long, thin text-line blobs
            continue
        if w < h:
            a -= 90
        a = (a + 45) % 90 - 45  # normalise to [-45, 45)
        angles.append(a)
        weights.append(max(w, h))
    if not angles:
        return 0.0
    order = np.argsort(angles)
    cw = np.cumsum(np.array(weights)[order])
    return float(np.array(angles)[order][np.searchsorted(cw, cw[-1] / 2)])  # weighted median


def rotate_bound(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def crop_dark_borders(img: np.ndarray) -> tuple[np.ndarray, bool]:
    """Crop scanner-bed borders only; white page margins are left untouched."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edge = np.mean([g[:8].mean(), g[-8:].mean(), g[:, :8].mean(), g[:, -8:].mean()])
    if edge > 70:
        return img, False
    mask = cv2.morphologyEx((g > 110).astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    pts = cv2.findNonZero(mask)
    if pts is None:
        return img, False
    x, y, w, h = cv2.boundingRect(pts)
    if w * h < 0.5 * g.size or w * h > 0.98 * g.size:
        return img, False
    return img[y:y + h, x:x + w], True


def geometric(img: np.ndarray) -> tuple[np.ndarray, list[str]]:
    ops = []
    img, cropped = crop_dark_borders(img)
    if cropped:
        ops.append("crop borders")
    a = skew_angle(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    if 0.3 < abs(a) <= 15:
        img = rotate_bound(img, a)
        ops.append(f"deskew {a:.1f}°")
    return img, ops


def ocr_gray(img: np.ndarray) -> tuple[np.ndarray, float, list[str]]:
    """Return (grayscale image for OCR, scale factor applied, operations used)."""
    ops = ["grayscale"]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    scale = 1.0
    if g.shape[1] < 1500:
        scale = 1500 / g.shape[1]
        g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        ops.append("upscale")
    if np.mean(cv2.absdiff(g, cv2.medianBlur(g, 3))) > 2.0:
        g = cv2.fastNlMeansDenoising(g, None, 10)
        ops.append("denoise")
    bg = cv2.medianBlur(g, 51)
    if bg.std() > 12:  # uneven illumination -> flatten + adaptive threshold
        g = cv2.divide(g, bg, scale=255)
        g = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
        ops.append("adaptive threshold")
    elif g.std() < 55:
        g = cv2.createCLAHE(2.0, (8, 8)).apply(g)
        ops.append("contrast")
    return g, scale, ops


def remove_rules(gray: np.ndarray) -> np.ndarray:
    """Erase long table/form ruling lines so OCR layout analysis is not confused by them."""
    H, W = gray.shape[:2]
    inv = 255 - gray if gray.mean() > 127 else gray
    bw = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    hm = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(W // 25, 20), 1)))
    vm = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(H // 30, 20))))
    mask = cv2.dilate(cv2.bitwise_or(hm, vm), np.ones((3, 3), np.uint8))
    out = gray.copy()
    out[mask > 0] = 255 if gray.mean() > 127 else 0
    return out
