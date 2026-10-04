"""Regenerate docs/screenshots/*.png with sample data (dev tool, not needed to run uscan).

    pip install playwright && playwright install chromium
    python scripts/screenshots.py
"""
import os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
PORT = 8765
sys.path.insert(0, str(ROOT))


def main():
    from playwright.sync_api import sync_playwright
    from tests.make_samples import make_all

    tmp = Path(tempfile.mkdtemp(prefix="uscan-shots-"))
    samples = tmp / "samples"
    make_all(samples)
    env = {**os.environ, "DATA_DIR": str(tmp / "data"), "USCAN_PORT": str(PORT), "ALLOWED_HOSTS": "127.0.0.1,localhost"}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz"); break
            except Exception:
                time.sleep(.5)
        OUT.mkdir(parents=True, exist_ok=True)
        files = sorted(str(p) for p in samples.iterdir() if p.suffix.lower() in {".pdf", ".png", ".jpg", ".tif", ".tiff"})
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=2, color_scheme="light", bypass_csp=True)
            pg = ctx.new_page(); pg.goto(f"http://127.0.0.1:{PORT}/")
            pg.wait_for_selector("#f", state="attached")
            pg.set_input_files("#f", files)
            pg.wait_for_function("document.querySelectorAll('tbody tr').length>=%d && !document.querySelector('.tag.processing,.tag.uploaded')" % len(files), timeout=120000)
            pg.wait_for_timeout(2500)  # let toasts settle
            pg.evaluate("document.querySelector('#toasts').replaceChildren()")
            pg.screenshot(path=str(OUT / "dashboard.png"), full_page=True)
            # dark
            pg.evaluate("document.documentElement.dataset.theme='dark'"); pg.wait_for_timeout(200)
            pg.screenshot(path=str(OUT / "dark.png"), full_page=True)
            pg.evaluate("document.documentElement.dataset.theme='light'")
            # review (open the one that needs a look if any, else first)
            btn = pg.locator("[data-act=open]:not([disabled])").first
            btn.click(); pg.wait_for_selector(".rev"); pg.wait_for_timeout(800)
            pg.screenshot(path=str(OUT / "review.png"))
            # compile
            pg.click("nav [data-v=comp]"); pg.wait_for_selector(".opts"); pg.wait_for_timeout(500)
            pg.screenshot(path=str(OUT / "compile.png"))
            # mobile
            m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme="light", is_mobile=True, has_touch=True, bypass_csp=True)
            mp = m.new_page(); mp.goto(f"http://127.0.0.1:{PORT}/"); mp.wait_for_selector("tbody tr"); mp.wait_for_timeout(600)
            mp.screenshot(path=str(OUT / "mobile.png"))
            b.close()
        print("wrote", *sorted(p.name for p in OUT.glob("*.png")))
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
