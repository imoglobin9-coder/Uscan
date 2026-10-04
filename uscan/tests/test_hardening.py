import unittest
from unittest import mock

try:
    from app import config
    from app.utils import security as sec
    from app.schemas import document as D
except ImportError:  # fastapi / pydantic not installed
    sec = None


@unittest.skipIf(sec is None, "fastapi/pydantic missing")
class SessionTests(unittest.TestCase):
    def test_session_lifecycle(self):
        t = sec.create_session()
        self.assertTrue(sec.valid_session(t))
        self.assertFalse(sec.valid_session("forged"))
        sec.end_session(t)
        self.assertFalse(sec.valid_session(t))

    def test_login_lockout(self):
        ip = "203.0.113.9"
        self.assertEqual(sec.login_allowed(ip), 0)
        for _ in range(sec.MAX_FAILS):
            sec.login_failed(ip)
        self.assertGreater(sec.login_allowed(ip), 0)
        sec.login_ok(ip)
        self.assertEqual(sec.login_allowed(ip), 0)

    def test_non_ascii_password_compare_does_not_crash(self):
        self.assertTrue(sec._eq("pässwörd", "pässwörd"))
        self.assertFalse(sec._eq("pässwörd", "password"))


@unittest.skipIf(sec is None, "fastapi/pydantic missing")
class SanitizerTests(unittest.TestCase):
    OLD = [{"id": "a", "kind": "text", "text": "hi", "words": [], "conf": 40, "bbox": [0, 0, 1, 1], "needs_review": True, "edited": False, "tags": []}]

    def test_edit_clears_flag_and_drops_unknown_keys(self):
        r = D.clean_blocks([{"id": "a", "text": "hello", "injected": 1}], self.OLD)[0]
        self.assertEqual((r["text"], r["needs_review"], r["edited"]), ("hello", False, True))
        self.assertNotIn("injected", r)

    def test_new_line_is_rebuilt_server_side(self):
        r = D.clean_blocks([{"id": "<b>", "text": "x" * 5000, "bbox": [5, -5, 0.5, 0.5]}], [])[0]
        self.assertEqual(len(r["text"]), 2000)
        self.assertEqual(r["bbox"][:2], [1.0, 0.0])
        self.assertNotEqual(r["id"], "<b>")

    def test_malformed_input_is_rejected(self):
        for bad in ([5], [{"text": "x", "bbox": ["a", 1, 1, 1]}], [{"text": "x", "bbox": [1, 2]}]):
            with self.assertRaises(ValueError):
                D.clean_blocks(bad, [])

    def test_tables_keep_their_shape(self):
        old = [{"kind": "ruled", "rows": [[{"text": "a", "colspan": 1, "needs_review": True}]]}]
        ok = D.clean_tables([{"rows": [[{"text": "A"}]]}], old)
        self.assertFalse(ok[0]["rows"][0][0]["needs_review"])
        for bad in ([], [{"rows": []}], [{"rows": [[{"text": "x"}, {"text": "y"}]]}]):
            with self.assertRaises(ValueError):
                D.clean_tables(bad, old)


class ApiHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import pymupdf as fitz  # noqa: F401
            from fastapi.testclient import TestClient
        except ImportError:
            raise unittest.SkipTest("full dependencies not installed")
        from app.database import init_db
        from app.main import app
        init_db()  # these tests don't run the app lifespan, so create the tables themselves
        cls.TestClient, cls.app = TestClient, app

    def client(self):
        return self.TestClient(self.app)

    def test_security_headers(self):
        h = self.client().get("/").headers
        self.assertIn("default-src 'self'", h["content-security-policy"])
        self.assertEqual(h["x-frame-options"], "DENY")
        self.assertEqual(h["x-content-type-options"], "nosniff")

    def test_unknown_host_is_refused(self):
        self.assertEqual(self.client().get("/api/session", headers={"host": "evil.example"}).status_code, 400)

    def test_cross_origin_writes_are_refused(self):
        c = self.client()
        self.assertEqual(c.post("/api/logout", headers={"origin": "http://evil.example"}).status_code, 403)
        self.assertEqual(c.post("/api/logout", headers={"origin": "http://testserver"}).status_code, 200)

    def test_api_docs_off_by_default(self):
        self.assertEqual(self.client().get("/docs").status_code, 404)
        self.assertEqual(self.client().get("/openapi.json").status_code, 404)

    def test_password_login_flow(self):
        with mock.patch.object(config, "APP_PASSWORD", "pw123"):
            c = self.client()
            self.assertEqual(c.get("/api/documents").status_code, 401)
            self.assertTrue(c.get("/api/session").json()["auth_required"])
            self.assertEqual(c.post("/api/login", json={"password": "wrong"}).status_code, 401)
            ok = c.post("/api/login", json={"password": "pw123"})
            self.assertEqual(ok.status_code, 200)
            cookie = ok.headers["set-cookie"].lower()
            self.assertIn("httponly", cookie)
            self.assertIn("samesite=strict", cookie)
            self.assertEqual(c.get("/api/documents").status_code, 200)
            c.post("/api/logout")
            self.assertEqual(c.get("/api/documents").status_code, 401)

    def test_api_key_header(self):
        with mock.patch.object(config, "API_KEY", "k-123"):
            c = self.client()
            self.assertEqual(c.get("/api/documents").status_code, 401)
            self.assertEqual(c.get("/api/documents", headers={"X-API-Key": "k-123"}).status_code, 200)
            self.assertEqual(c.get("/api/documents", headers={"X-API-Key": "nöpe".encode()}).status_code, 401)  # non-ASCII must not 500

    def test_too_many_files(self):
        files = [("files", (f"a{i}.png", b"x")) for i in range(config.MAX_FILES_PER_UPLOAD + 1)]
        self.assertEqual(self.client().post("/api/documents/upload", files=files).status_code, 400)

    def test_page_edit_validation_and_undo_delete(self):
        from app.database import SessionLocal
        from app.models.document import Document
        from app.models.page import Page
        with self.client() as c:  # context manager runs startup (creates tables)
            db = SessionLocal()
            d = Document(original_filename="t.pdf", title="t", file_type="pdf", stored_name="none.pdf", status="processed")
            db.add(d); db.commit()
            p = Page(document_id=d.id, blocks=[{"id": "b1", "kind": "text", "text": "hi", "words": [], "conf": 40, "bbox": [0, 0, 1, 1], "needs_review": True, "edited": False, "tags": []}],
                     tables=[{"id": "t0", "kind": "ruled", "bbox": [0, 0, 1, 1], "rows": [[{"text": "a", "colspan": 1, "needs_review": True}]]}], flags=2)
            db.add(p); db.commit(); pid = p.id; db.close()
            self.assertEqual(c.put(f"/api/pages/{pid}", json={"tables": [{"rows": []}]}).status_code, 422)  # wrong shape
            self.assertEqual(c.put(f"/api/pages/{pid}", json={"blocks": [5]}).status_code, 422)
            r = c.put(f"/api/pages/{pid}", json={"blocks": [{"id": "b1", "text": "hello"}], "tables": [{"rows": [[{"text": "A"}]]}]})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["flags"], 0)
            self.assertEqual(c.delete(f"/api/pages/{pid}").status_code, 200)
            self.assertEqual(c.post(f"/api/pages/{pid}/restore").status_code, 200)
            self.assertEqual(len(c.get(f"/api/documents/{d.id}/pages").json()), 1)


if __name__ == "__main__":
    unittest.main()
