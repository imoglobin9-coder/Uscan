import cv2
import numpy as np


def imread(path) -> np.ndarray:
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def imwrite_png(path, img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("encode failed")
    buf.tofile(str(path))


def jpeg_bytes(img, quality=80, max_w=None) -> bytes:
    if max_w and img.shape[1] > max_w:
        s = max_w / img.shape[1]
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes()
