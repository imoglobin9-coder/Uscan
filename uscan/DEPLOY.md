# Publishing uscan for the public

Public mode (`PUBLIC_MODE=true`) gives **every visitor an anonymous private workspace** — no sign-up. Nobody can see anyone else's files.

| What | How it works |
|---|---|
| Privacy between visitors | A random cookie (`HttpOnly`, `SameSite=Strict`, `Secure`) opens one workspace. Every API call is checked against it; someone else's report looks exactly like a report that doesn't exist. |
| Automatic deletion | A workspace and all its files are deleted after `WORKSPACE_TTL_HOURS` (24) without use. Visitors can also press **Delete my data**. A cleanup task also removes orphaned files. |
| Fair use | Per workspace: 15 reports, 100 MB, 100 pages, 10 compiled PDFs. Per report: 25 MB, 60 pages. One batch at a time per visitor, a site-wide queue cap, and rate limits per address. |
| Protecting the server | Only 2 OCR / PDF jobs run at once (others get a friendly "busy"); new work is refused when the disk is nearly full (`MIN_FREE_MB`); the container has memory / CPU / process ceilings. |
| No tracking | No analytics, no access log. `/privacy` explains all of this to visitors and shows your `CONTACT_EMAIL`. |

All limits are environment variables — see `.env.example`.

## 1. Try it on your computer first
```bash
PUBLIC_MODE=true python run.py        # Windows (PowerShell): $env:PUBLIC_MODE="true"; python run.py
```
Open it in two different browsers (or one normal + one private window), upload a file in each, and confirm neither can see the other's. Also open `/privacy`.

## 2. Publish on a hosting platform — no domain needed
Platforms such as Railway, Render or Fly.io build the `Dockerfile` and give you an `https://…` address.

1. Put the project in a GitHub repository — public or private both work, because `.gitignore` keeps `.env` and `data/` out. Never commit real settings or uploaded documents; set secrets as environment variables on the platform instead.
2. On the platform, create a service from that repository. It should detect the `Dockerfile`.
3. Set at least `CONTACT_EMAIL` as an environment variable. Everything else defaults to sensible public-mode values. The app reads the platform's `PORT` automatically.
4. Give it **at least 2 GB of RAM** and 1–2 CPUs (OCR is memory- and CPU-hungry).
5. Optional: attach a volume at `/data` if you want files to survive redeploys. Without one they vanish on redeploy, which is acceptable because they are temporary anyway.
6. Generate the public address in the platform's networking settings and open it.
7. **Set a spending limit** in the platform's billing settings if it offers one. A public OCR service can be used heavily.

## 3. Publish on your own server (needs a domain)
1. A VPS with Docker installed, and a domain (or subdomain) whose DNS points at it.
2. Copy the project there, then `cp .env.example .env` and add `SITE_ADDRESS=your.domain.example` and `CONTACT_EMAIL=you@example.com`.
3. `docker compose up -d --build` — Caddy obtains the HTTPS certificate automatically.

## Before you announce it
- [ ] Two-browser isolation test (step 1) on the **deployed** address, too.
- [ ] Read `/privacy` and make sure every sentence is true for how *you* run it (backups, provider logs, retention). Check the privacy rules where you and your visitors live; this page is a plain-language notice, not legal advice.
- [ ] Upload a large PDF and watch memory, CPU and disk for a few minutes.
- [ ] Decide what you'll do if someone uploads something you don't want to host. You are the operator; there is no reporting mechanism built in beyond your contact address.

## Sizing
Untested estimates, not measurements: scanned pages are stored as images of roughly 2–5 MB each, so a full workspace (100 pages) can use a few hundred MB, and reading a page takes a few seconds of CPU. If your disk is small, lower `MAX_WORKSPACE_PAGES`, `MAX_WORKSPACES` or `WORKSPACE_TTL_HOURS`. If reports pile up in the queue, raise CPU or lower `MAX_QUEUED_DOCS`.

## Troubleshooting
- **"Cross-site request blocked"** — your proxy is changing the `Host` header. Make it pass the original one through.
- **Everyone shares one address / rate limits hit too fast** — the proxy's IP is being seen instead of visitors'. Set `TRUSTED_PROXIES` (the Dockerfile uses `*`, which is only safe when nothing but the platform's proxy can reach the app).
- **Can't write to `/data`** — the mounted volume is owned by root. Fix the volume's ownership for uid 10001 or use the platform's setting for volume permissions.
- **`run.py` exits immediately** — public mode on a network address needs `COOKIE_SECURE=true` and HTTPS in front; that's deliberate.
- **Uploads fail with "busy"** — a visitor can only have one batch reading at a time; the queue is site-wide.

## Limits of this design
- Run **one** process/instance only. Sessions, the OCR queue and rate limits live in memory. Don't scale it horizontally or use more than one worker.
- Files are **not encrypted on disk**, and uploads are parsed inside the app's container. The container limits reduce the damage of a malicious file but don't remove the risk. Keep the image and dependencies updated.
- Cookie-based workspaces mean clearing cookies (or switching browser) loses access to the files. That is the trade-off for having no accounts.
- I could not build the Docker image or run the server in the environment where this was written. Do the local test above, then a first deploy, before relying on it.
