import shutil
import tempfile
import time
import unittest
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None

from app.utils.security import safe_join, safe_name, validate_upload


class SecurityTests(unittest.TestCase):
    def test_extension_and_magic(self):
        self.assertEqual(validate_upload("a.PDF", b"%PDF-1.7"), ".pdf")
        with self.assertRaises(ValueError):
            validate_upload("a.exe", b"MZ")
        with self.assertRaises(ValueError):
            validate_upload("fake.pdf", b"\x89PNG\r\n\x1a\n")

    def test_safe_name_and_join(self):
        self.assertEqual(safe_name("../../etc/passwd"), "passwd")
        self.assertNotIn("\\", safe_name("C:\\Users\\x\\rep ort.pdf"))
        with self.assertRaises(ValueError):
            safe_join(Path(tempfile.gettempdir()), "..", "x")


@unittest.skipIf(cv2 is None, "OpenCV missing")
class ImageTableTests(unittest.TestCase):
    def test_deskew_detects_angle(self):
        from app.services import image_service as IS
        img = np.full((1100, 850, 3), 255, np.uint8)
        for i in range(16):
            cv2.putText(img, f"Line {i} some report text goes here", (50, 90 + i * 55), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
        r = IS.rotate_bound(img, 4)
        self.assertAlmostEqual(IS.skew_angle(cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)), -4, delta=0.7)
        fixed, ops = IS.geometric(r)
        self.assertTrue(any("deskew" in o for o in ops))

    def test_ruled_grid_any_shape(self):
        from app.services import table_service as TS
        for cols, rows in ((3, 3), (5, 4)):  # different schemas, same code path
            g = np.full((700, 1000, 3), 255, np.uint8)
            xs = np.linspace(50, 950, cols + 1).astype(int)
            ys = np.linspace(50, 50 + 70 * rows, rows + 1).astype(int)
            for x in xs:
                cv2.line(g, (int(x), 50), (int(x), int(ys[-1])), (0, 0, 0), 2)
            for y in ys:
                cv2.line(g, (50, int(y)), (950, int(y)), (0, 0, 0), 2)
            t = TS.detect_tables(cv2.cvtColor(g, cv2.COLOR_BGR2GRAY), [])
            self.assertEqual((len(t[0]["rows"]), len(t[0]["rows"][0])), (rows, cols))

    def test_low_confidence_never_invented(self):
        from app.services.ocr_service import Word, build_blocks
        b = build_blocks([Word("Juan", 95, 0.1, 0.1, 0.2, 0.12), Word("Dela", 90, 0.21, 0.1, 0.3, 0.12), Word("C...", 30, 0.31, 0.1, 0.4, 0.12)])[0]
        self.assertEqual(b["text"], "Juan Dela C...")
        self.assertTrue(b["needs_review"])


class PageSelectionTests(unittest.TestCase):
    def test_parse(self):
        try:
            from app.services.compilation_service import parse_pages
        except ImportError:
            self.skipTest("PyMuPDF missing")
        self.assertEqual(parse_pages("all", 3), [0, 1, 2])
        self.assertEqual(parse_pages("1-2,5", 5), [0, 1, 4])
        with self.assertRaises(ValueError):
            parse_pages("9", 3)


class EndToEndTests(unittest.TestCase):
    """Upload -> scan -> review -> compile -> download (needs fastapi, httpx, PyMuPDF, tesseract)."""

    @classmethod
    def setUpClass(cls):
        try:
            import pymupdf as fitz  # noqa: F401
            from fastapi.testclient import TestClient
        except ImportError:
            raise unittest.SkipTest("full dependencies not installed")
        if not shutil.which("tesseract"):
            raise unittest.SkipTest("tesseract not installed")
        cls.tmp = tempfile.mkdtemp()
        import os
        os.environ["DATA_DIR"] = cls.tmp
        from app.main import app
        cls.client = TestClient(app).__enter__()
        from tests.make_samples import make_all
        cls.files = make_all(Path(cls.tmp) / "samples")

    def test_full_flow(self):
        c = self.client
        up = [("files", (n, p.read_bytes())) for n, p in self.files.items()]
        up.append(("files", ("evil.exe", b"MZ")))
        r = c.post("/api/documents/upload", files=up).json()
        self.assertEqual(len(r["documents"]), 3)
        self.assertEqual(len(r["errors"]), 1)  # bad file rejected, batch continues
        for _ in range(180):
            j = c.get(f"/api/jobs/{r['job_id']}").json()
            if j["done"]:
                break
            time.sleep(1)
        self.assertTrue(j["done"])
        docs = c.get("/api/documents").json()
        self.assertTrue(all(d["pages"] >= 1 for d in docs))
        first = c.get(f"/api/documents/{docs[0]['id']}/pages").json()[0]
        self.assertEqual(c.put(f"/api/pages/{first['id']}", json={"reviewed": True}).status_code, 200)
        comp = c.post("/api/compilations", json={"title": "Test", "items": [{"document_id": d["id"]} for d in docs]}).json()
        self.assertEqual(c.post(f"/api/compilations/{comp['id']}/export").status_code, 200)
        pdf = c.get(f"/api/compilations/{comp['id']}/download")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        import pymupdf as fitz
        doc = fitz.open(stream=pdf.content, filetype="pdf")
        self.assertGreaterEqual(len(doc), 5)  # cover + toc + 3 reports
        self.assertIn("Juan", "".join(p.get_text() for p in doc))  # scanned page is searchable


if __name__ == "__main__":
    unittest.main()
