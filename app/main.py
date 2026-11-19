"""FolioLib: personal investment dashboard. `serve` (default); `passwd` creates or changes the account; `report` prints a text summary.

    docker exec -it foliolib python main.py passwd     username + password (typed in the terminal)
    docker exec foliolib python main.py report         value and positions as text
    python main.py demo                                load synthetic demo data into an empty database
"""
import html
import json
import os
import signal
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import auth
import engine
import i18n
import parsers
import store
from i18n import t

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 8 * 1024 * 1024
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
job = {"running": False, "step": "", "started": 0, "done": 0, "notes": []}
job_lock = threading.Lock()


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def run_refresh():
    with job_lock:
        if job["running"]:
            return False
        job.update(running=True, step=("Starting", {}), started=time.time(), notes=[])

    def work():
        try:
            db = store.connect()
            job["notes"] = engine.refresh(db, store.DATA, lambda text, params=None: job.update(step=(text, params or {})))
        except Exception as e:                                   # a bug must not block the page
            job["notes"] = ["internal error: " + type(e).__name__]
            log("refresh : " + repr(e))
        finally:
            job.update(running=False, done=time.time(), step="")
    threading.Thread(target=work, daemon=True).start()
    return True


LOGIN = """<!doctype html><html lang="%(lang)s"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FolioLib</title><link rel="stylesheet" href="/static/login.css"><body class="login"><main>
<h1>FolioLib</h1><p class="muted">%(msg)s</p>
<form method="post" action="/login"><label>%(user)s<input name="user" autocomplete="username" autofocus required></label>
<label>%(password)s<input name="password" type="password" autocomplete="current-password" required></label>
<button>%(sign_in)s</button></form><p class="langs">%(langs)s</p></main></body></html>"""
LANG_COOKIE_AGE = 365 * 24 * 3600


class Handler(BaseHTTPRequestHandler):
    server_version = "foliolib"

    def log_message(self, *a):
        pass

    # ----- helpers
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _cookie(self, name):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def _authed(self):
        return auth.valid_cookie(self._cookie("sid"))

    def _query_lang(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("lang", [""])[0]

    def _lang(self):
        """The language to answer in: `?lang=` first, then the `lang` cookie, then the browser's own preference."""
        return i18n.pick(self._query_lang() or self._cookie("lang"), self.headers.get("Accept-Language", ""))

    def _error(self, code, text, **params):
        self._json({"error": t(self._lang(), text, **params)}, code)

    def _same_origin(self):
        """Protection against requests coming from another site: `Sec-Fetch-Site` (sent by all recent browsers),
        otherwise the `Origin` header must point to this same address. A SameSite=Strict cookie doubles the protection."""
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None:
            return site == "same-origin"
        origin = self.headers.get("Origin", "")
        return bool(origin) and urllib.parse.urlparse(origin).netloc == self.headers.get("Host", "")

    def _redirect(self, to, extra=None):
        self._send(303, b"", extra={"Location": to, **(extra or {})})

    # ----- GET
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/healthz":
            return self._send(200, "ok")
        if path == "/static/login.css":
            return self._file("login.css")
        if path == "/login":
            return self._login_page()
        if not self._authed():
            return self._redirect("/login") if not path.startswith("/api/") else self._error(401, "sign-in required")
        if path == "/":
            return self._file("index.html")
        if path.startswith("/static/"):
            return self._file(path[len("/static/"):])
        if path == "/api/data":
            return self._json(engine.compute(store.connect(), store.DATA, self._lang()))
        if path == "/api/i18n":
            lang = self._lang()
            return self._json({"lang": lang, "messages": i18n.messages(lang)})
        if path == "/api/status":
            lang, step = self._lang(), job["step"]
            return self._json({"running": job["running"], "step": t(lang, step[0], **step[1]) if step else "", "notes": job["notes"], "done": job.get("done", 0)})
        self._send(404, "not found")

    def _file(self, name):
        p = (STATIC / urllib.parse.unquote(name)).resolve()
        if STATIC.resolve() not in p.parents or not p.is_file() or p.suffix not in TYPES:
            return self._send(404, "not found")
        self._send(200, p.read_bytes(), TYPES[p.suffix])

    def _login_html(self, text):
        lang = self._lang()
        current = ' aria-current="true"'
        links = " · ".join(f'<a href="/login?lang={code}"{current if code == lang else ""}>{html.escape(name)}</a>' for code, name in i18n.LANGUAGES.items())
        return LOGIN % {"lang": lang, "msg": html.escape(t(lang, text)), "user": t(lang, "Username"), "password": t(lang, "Password"),
                        "sign_in": t(lang, "Sign in"), "langs": links}

    def _login_page(self, text=""):
        if not auth.configured():
            text = "No account: run \"docker exec -it foliolib python main.py passwd\"."
        chosen = self._query_lang()      # an explicit choice made with the links of the page is remembered
        extra = {"Set-Cookie": f"lang={chosen}; Path=/; Max-Age={LANG_COOKIE_AGE}; SameSite=Strict"} if chosen in i18n.LANGUAGES else None
        self._send(200, self._login_html(text or "Private access."), "text/html; charset=utf-8", extra)

    # ----- POST
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._same_origin():
            return self._send(403, "origin refused")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            return self._send(413, "file too large")
        body = self.rfile.read(n)
        if path == "/login":
            return self._login(body)
        if not self._authed():
            return self._error(401, "sign-in required")
        db = store.connect()
        if path == "/logout":
            return self._redirect("/login", {"Set-Cookie": "sid=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Strict"})
        if path == "/api/refresh":
            return self._json({"started": run_refresh()})
        if path == "/api/upload":
            if store.meta_get(db, "demo"):
                return self._error(400, "Demo data is loaded: erase it first (Data Management) before importing your own files.")
            name = urllib.parse.unquote(self.headers.get("X-Filename", "export.csv"))[:120]
            try:
                kind, recs = parsers.parse(body)
            except ValueError as e:
                return self._json({"error": e.text(self._lang()) if isinstance(e, i18n.Msg) else str(e)}, 400)
            total, new = store.add_file(db, name, kind, recs, store.save_raw(body))
            return self._json({"kind": kind, "lines": total, "new": new, "started": run_refresh()})
        if path == "/api/alias":
            d = json.loads(body or b"{}")
            label, isin = " ".join(str(d.get("label", "")).lower().split()), str(d.get("isin", "")).strip().upper()
            if not label or len(isin) != 12:
                return self._error(400, "Invalid ISIN (12 characters)")
            db.execute("INSERT OR REPLACE INTO aliases(label,isin) VALUES(?,?)", (label, isin))
            db.commit()
            return self._json({"ok": True, "started": run_refresh()})
        if path == "/api/symbol":
            d = json.loads(body or b"{}")
            isin, sym = str(d.get("isin", "")).strip().upper(), str(d.get("symbol", "")).strip().upper()
            if len(isin) != 12 or not sym or len(sym) > 20:
                return self._error(400, "Invalid ISIN or symbol")
            db.execute("INSERT INTO instruments(isin,symbol,manual,tried) VALUES(?,?,1,0) ON CONFLICT(isin) DO UPDATE SET symbol=?, manual=1", (isin, sym, sym))
            db.commit()
            return self._json({"ok": True, "started": run_refresh()})
        if path == "/api/wipe":
            if json.loads(body or b"{}").get("confirm") != "WIPE":
                return self._error(400, "confirmation missing")
            store.wipe(db)
            return self._json({"ok": True})
        self._send(404, "not found")

    def _login(self, body):
        form = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        user, pw = (form.get("user") or [""])[0], (form.get("password") or [""])[0]
        if auth.locked():
            return self._send(429, self._login_html("Too many attempts: try again in a few minutes."), "text/html; charset=utf-8")
        if auth.check(user, pw):
            return self._redirect("/", {"Set-Cookie": f"sid={auth.make_cookie()}; Max-Age={auth.SESSION_SECONDS}; Path=/; HttpOnly; Secure; SameSite=Strict"})
        self._send(401, self._login_html("Incorrect username or password."), "text/html; charset=utf-8")

    def do_PUT(self):
        self._send(405, "method not allowed")
    do_DELETE = do_PATCH = do_PUT


def serve():
    store.DATA.mkdir(parents=True, exist_ok=True)
    db = store.connect()
    need = store.migrate(db)
    if need:
        log("parser fixed, re-upload needed: " + ", ".join(need))
    db.close()
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else int(os.environ.get("FOLIOLIB_PORT", "8080"))
    host = os.environ.get("FOLIOLIB_HOST", "0.0.0.0")
    srv = ThreadingHTTPServer((host, port), Handler)
    # As PID 1 of a container, Python ignores SIGTERM unless told otherwise: `docker stop` would wait 10 s, then kill us.
    # shutdown() blocks until the loop exits, so it must not run in the thread that runs the loop.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=srv.shutdown, daemon=True).start())
    log("foliolib ready on %s:%d (account configured: %s)" % (host, port, auth.configured()))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        log("foliolib stopped")


def import_file():
    """docker exec foliolib python main.py import /data/file.csv: same path as the upload in the page."""
    path = Path(sys.argv[2])
    raw = path.read_bytes()
    kind, recs = parsers.parse(raw)
    db = store.connect()
    total, new = store.add_file(db, path.name, kind, recs, store.save_raw(raw))
    print(f"{path.name}: {kind}, {new} new line(s) out of {total}")


def load_demo():
    """python main.py demo: fill an EMPTY database with synthetic data (see demo.py)."""
    import demo
    store.DATA.mkdir(parents=True, exist_ok=True)
    db = store.connect()
    n = demo.load(db)
    print(f"Demo data loaded into {store.DB_PATH}: {n['orders']} orders, {n['account_lines']} account lines, {n['instruments']} instruments.")
    print("Next: `python main.py passwd` to create a login, then `python main.py serve` (add --port N to change the port).")


def report():
    d = engine.compute(store.connect(), store.DATA)
    k = d["kpi"]
    print(f"Value: {k['value']:.2f} € | Invested: {k['invested']:.2f} € | Gain: {k['gain']:+.2f} € ({(k['gain_pct'] or 0) * 100:+.1f} %) | IRR: {(k['irr'] or 0) * 100:.1f} %/yr")
    for p in d["positions"]:
        print(f"{p['account_short'][:8]:8} {p['name'][:34]:34} {p['value']:9.2f} € {((p['gain_pct'] or 0) * 100):+7.1f} %  [{p['source']}]")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    {"serve": serve, "passwd": auth.cli_passwd, "report": report, "import": import_file, "demo": load_demo}.get(cmd, serve)()
