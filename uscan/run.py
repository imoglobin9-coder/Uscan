import sys
import threading
import webbrowser
import uvicorn
from app import config
from app.utils.security import auth_enabled

LOOPBACK = {"127.0.0.1", "localhost", "::1"}

if __name__ == "__main__":
    public_net = config.HOST not in LOOPBACK
    if public_net and not config.PUBLIC_MODE and not auth_enabled():
        sys.exit(f"Refusing to listen on {config.HOST} without a password: anyone on the network could read your documents.\n"
                 "Set APP_PASSWORD in .env, or set PUBLIC_MODE=true to give every visitor a private workspace, or keep the default 127.0.0.1.")
    if public_net and config.PUBLIC_MODE and not config.COOKIE_SECURE:
        sys.exit("PUBLIC_MODE on a network address needs COOKIE_SECURE=true and HTTPS in front (your hosting platform or a proxy such as Caddy).\n"
                 "To just try it on this computer, leave USCAN_HOST at 127.0.0.1.")
    url = f"http://{'127.0.0.1' if not public_net else config.HOST}:{config.PORT}"
    if not public_net:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    else:
        print(f"Serving on port {config.PORT} ({'public mode' if config.PUBLIC_MODE else 'password mode'}).")
    # One process only: sessions, the job queue and rate limits live in memory.
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, server_header=False, workers=1,
                proxy_headers=True, forwarded_allow_ips=config.TRUSTED_PROXIES, access_log=not config.PUBLIC_MODE)
