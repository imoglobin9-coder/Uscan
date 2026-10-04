"""Runs before any test module imports the app: isolate data, allow TestClient's host, ignore a developer's .env auth."""
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="uscan-test-"))
os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
os.environ["APP_PASSWORD"] = ""  # set explicitly so a real .env password can't lock the tests out
os.environ["API_KEY"] = ""
os.environ["ENABLE_DOCS"] = "false"
os.environ["PUBLIC_MODE"] = "false"  # public-mode tests switch it on explicitly
