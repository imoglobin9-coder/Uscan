"""Public mode: every visitor gets an anonymous private workspace. These tests are about NOT leaking between visitors."""
import datetime as dt
import time
import unittest
from unittest import mock

try:
    from app import config
    from app.utils import limits
except ImportError:
    limits = None

PNG = b"\x89PNG\r\n\x1a\n" + b"not really an image"  # passes the magic-byte check; processing then fails harmlessly


@unittest.skipIf(limits is None, "app dependencies missing")
class WindowTests(unittest.TestCase):
    def test_sliding_window(self):
        w = limits.Window(60)
        self.assertTrue(all(w.allow("a", 3) for _ in range(3)))
        self.assertFalse(w.allow("a", 3))
        self.assertTrue(w.allow("b", 3))    # another address is unaffected
        self.assertTrue(w.allow("a", 0))    # 0 = unlimited

    def test_window_forgets(self):
        w = limits.Window(0.05)
        self.assertTrue(w.allow("a", 1)); self.assertFalse(w.allow("a", 1))
        time.sleep(0.08)
        self.assertTrue(w.allow("a", 1))


class PublicModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import pymupdf as fitz  # noqa: F401
            from fastapi.testclient import TestClient
        except ImportError:
            raise unittest.SkipTest("full dependencies not installed")
        from app.main import app
        cls.TestClient, cls.app = TestClient, app
        cls.stack = mock.patch.multiple(config, PUBLIC_MODE=True, WORKSPACE_TTL_HOURS=24, MAX_WORKSPACE_DOCS=15, MAX_WORKSPACE_MB=100,
                                        MAX_WORKSPACES=200, NEW_WORKSPACES_PER_IP_HOUR=50, MAX_QUEUED_DOCS=30, MIN_FREE_MB=0, RATE_LIMIT_PER_MIN=0)
        cls.stack.start()
        cls.janitor = mock.patch("app.services.workspace_service.start_janitor")  # tests call sweep() themselves
        cls.janitor.start()

    @classmethod
    def tearDownClass(cls):
        cls.janitor.stop()
        cls.stack.stop()

    def setUp(self):
        limits.NEW_WORKSPACE.hits.clear()

    def visitor(self):
        c = self.TestClient(self.app)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def upload(self, c, name="a.png"):
        r = c.post("/api/documents/upload", files=[("files", (name, PNG))])
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        for _ in range(100 if body["job_id"] else 0):  # wait for the background job so the next upload isn't refused as "still busy"
            if c.get(f"/api/jobs/{body['job_id']}").json()["done"]:
                break
            time.sleep(0.1)
        return body

    def test_no_cookie_means_empty_and_nothing_is_created_by_reading(self):
        c = self.visitor()
        self.assertEqual(c.get("/api/documents").json(), [])
        self.assertEqual(c.get("/api/stats").json()["documents"], 0)
        self.assertNotIn("uscan_ws", c.cookies)

    def test_upload_sets_a_hardened_cookie(self):
        c = self.visitor()
        r = c.post("/api/documents/upload", files=[("files", ("a.png", PNG))])
        cookie = r.headers["set-cookie"].lower()
        self.assertIn("uscan_ws=", cookie)
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)

    def test_visitors_cannot_see_or_touch_each_others_files(self):
        a, b = self.visitor(), self.visitor()
        doc = self.upload(a)["documents"][0]
        job = a.post(f"/api/documents/{doc['id']}/process").json()["job_id"]
        self.assertEqual(len(a.get("/api/documents").json()), 1)
        self.assertEqual(b.get("/api/documents").json(), [])                      # list
        self.assertEqual(b.get(f"/api/documents/{doc['id']}").status_code, 404)    # read
        self.assertEqual(b.get(f"/api/documents/{doc['id']}/pages").status_code, 404)
        self.assertEqual(b.put(f"/api/documents/{doc['id']}", json={"title": "x"}).status_code, 404)  # rename
        self.assertEqual(b.post(f"/api/documents/{doc['id']}/process").status_code, 404)
        self.assertEqual(b.get(f"/api/jobs/{job}").status_code, 404)               # job progress
        self.assertEqual(b.delete(f"/api/documents/{doc['id']}").status_code, 404)
        r = b.post("/api/compilations", json={"title": "steal", "items": [{"document_id": doc["id"]}]})
        self.assertEqual(r.status_code, 400)                                       # cannot compile someone else's report
        self.assertEqual(b.get("/api/export/text").status_code, 400)               # nothing of theirs to export
        self.assertEqual(len(a.get("/api/documents").json()), 1)                   # still intact

    def test_pages_and_images_are_private(self):
        from app.database import SessionLocal
        from app.models.page import Page
        a, b = self.visitor(), self.visitor()
        doc = self.upload(a)["documents"][0]
        db = SessionLocal()
        p = Page(document_id=doc["id"], blocks=[], tables=[]); db.add(p); db.commit(); pid = p.id; db.close()
        self.assertEqual(a.put(f"/api/pages/{pid}", json={"reviewed": True}).status_code, 200)  # the owner can
        for call in (b.get(f"/api/pages/{pid}/image"), b.put(f"/api/pages/{pid}", json={"reviewed": True}), b.delete(f"/api/pages/{pid}"),
                     b.post(f"/api/pages/{pid}/rotate"), b.post(f"/api/pages/{pid}/rescan"), b.post(f"/api/pages/{pid}/restore")):
            self.assertEqual(call.status_code, 404)

    def test_forged_or_unknown_cookie_gets_nothing(self):
        c = self.visitor()
        c.cookies.set("uscan_ws", "x" * 43)
        self.assertEqual(c.get("/api/documents").json(), [])
        c.cookies.set("uscan_ws", "y" * 500)  # oversized
        self.assertEqual(c.get("/api/documents").json(), [])

    def test_document_quota(self):
        c = self.visitor()
        with mock.patch.object(config, "MAX_WORKSPACE_DOCS", 1):
            self.assertEqual(len(self.upload(c)["documents"]), 1)
            second = self.upload(c, "b.png")
            self.assertEqual(second["documents"], [])
            self.assertIn("up to 1 report", second["errors"][0]["error"])

    def test_storage_quota_removes_the_rejected_file(self):
        from app.config import DIRS
        c = self.visitor()
        before = len(list(DIRS["uploads"].iterdir()))
        with mock.patch.object(config, "MAX_WORKSPACE_MB", 0.00001):
            r = c.post("/api/documents/upload", files=[("files", ("a.png", PNG))]).json()
        self.assertEqual(r["documents"], [])
        self.assertIn("full", r["errors"][0]["error"])
        self.assertEqual(len(list(DIRS["uploads"].iterdir())), before)  # nothing left on disk

    def test_one_batch_at_a_time_per_visitor(self):
        from app.database import SessionLocal
        from app.models.document import Document
        from app.services import document_service as svc
        c = self.visitor()
        doc = self.upload(c)["documents"][0]
        with SessionLocal() as db:
            owner = db.get(Document, doc["id"]).owner
        with svc._jobs_lock:
            svc.JOBS["fake-running"] = {"owner": owner, "total": 1, "results": [], "done": False, "finished": None}
        try:
            self.assertEqual(c.post("/api/documents/upload", files=[("files", ("c.png", PNG))]).status_code, 429)
        finally:
            svc.JOBS.pop("fake-running", None)

    def test_new_workspace_rate_limit_per_address(self):
        with mock.patch.object(config, "NEW_WORKSPACES_PER_IP_HOUR", 1):
            self.assertEqual(self.visitor().post("/api/documents/upload", files=[("files", ("a.png", PNG))]).status_code, 200)
            self.assertEqual(self.visitor().post("/api/documents/upload", files=[("files", ("a.png", PNG))]).status_code, 429)

    def test_site_capacity_cap(self):
        from sqlalchemy import func, select
        from app.database import SessionLocal
        from app.models.workspace import Workspace
        self.upload(self.visitor())  # make sure at least one workspace exists
        with SessionLocal() as db:
            existing = db.scalar(select(func.count()).select_from(Workspace))
        with mock.patch.object(config, "MAX_WORKSPACES", existing):
            r = self.visitor().post("/api/documents/upload", files=[("files", ("a.png", PNG))])
        self.assertEqual(r.status_code, 503)

    def test_delete_my_data_removes_rows_and_files(self):
        from app.config import DIRS
        from app.database import SessionLocal
        from app.models.document import Document
        c = self.visitor()
        doc = self.upload(c)["documents"][0]
        with SessionLocal() as db:
            stored = db.get(Document, doc["id"]).stored_name
        self.assertTrue((DIRS["uploads"] / stored).exists())
        self.assertEqual(c.delete("/api/workspace").status_code, 200)
        self.assertFalse((DIRS["uploads"] / stored).exists())
        self.assertEqual(c.get("/api/documents").json(), [])
        with SessionLocal() as db:
            self.assertIsNone(db.get(Document, doc["id"]))

    def test_idle_workspaces_expire_and_their_files_are_deleted(self):
        from app.config import DIRS
        from app.database import SessionLocal
        from app.models.document import Document
        from app.models.workspace import Workspace
        from app.services import workspace_service as ws
        c, other = self.visitor(), self.visitor()
        mine = self.upload(c)["documents"][0]
        theirs = self.upload(other, "b.png")["documents"][0]
        with SessionLocal() as db:
            stored = db.get(Document, mine["id"]).stored_name
            owner = db.get(Document, mine["id"]).owner
            db.get(Workspace, owner).last_seen = dt.datetime.utcnow() - dt.timedelta(hours=25)
            db.commit()
        self.assertEqual(c.get("/api/documents").json(), [])  # expired immediately, even before cleanup runs
        ws.sweep()
        self.assertFalse((DIRS["uploads"] / stored).exists())
        with SessionLocal() as db:
            self.assertIsNone(db.get(Document, mine["id"]))
            self.assertIsNotNone(db.get(Document, theirs["id"]))  # the other visitor's data is untouched
        self.assertEqual(len(other.get("/api/documents").json()), 1)

    def test_orphan_files_are_swept_but_fresh_ones_are_not(self):
        import os
        from app.config import DIRS
        from app.services import workspace_service as ws
        old, fresh = DIRS["uploads"] / ("f" * 32 + ".pdf"), DIRS["uploads"] / ("e" * 32 + ".pdf")
        old.write_bytes(b"x"); fresh.write_bytes(b"x")
        os.utime(old, (time.time() - 7200,) * 2)
        ws.sweep()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())  # could be an upload still being written
        fresh.unlink()

    def test_wipe_is_unavailable_outside_public_mode(self):
        c = self.visitor()
        with mock.patch.object(config, "PUBLIC_MODE", False):
            self.assertEqual(c.delete("/api/workspace").status_code, 404)

    def test_rate_limit_and_healthcheck(self):
        c = self.visitor()
        with mock.patch.object(config, "RATE_LIMIT_PER_MIN", 3):
            limits.GENERAL.hits.clear()
            codes = [c.get("/api/stats").status_code for _ in range(5)]
            self.assertEqual(codes[:3], [200] * 3)
            self.assertEqual(codes[3:], [429, 429])
            self.assertEqual(c.get("/healthz").status_code, 200)  # not rate limited, no host check
        limits.GENERAL.hits.clear()

    def test_session_and_privacy_page(self):
        c = self.visitor()
        s = c.get("/api/session").json()
        self.assertTrue(s["public"])
        self.assertEqual(s["ttl_hours"], 24)
        page = c.get("/privacy")
        self.assertEqual(page.status_code, 200)
        self.assertIn("24 hours", page.text)
        self.assertNotIn("{{", page.text)
        with mock.patch.object(config, "CONTACT_EMAIL", '"><script>x</script>'):
            self.assertNotIn("<script>x", c.get("/privacy").text)  # contact address is escaped


if __name__ == "__main__":
    unittest.main()
