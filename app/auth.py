"""Username and password sign-in. The password is entered by the administrator in a terminal
(`docker exec -it <container> python main.py passwd`), never written in a chat or in a readable file: only its `scrypt` hash is kept."""
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import time

import store

PATH = store.DATA / "auth.json"
SESSION_SECONDS = 14 * 24 * 3600
_fails = []          # timestamps of recent failures (global: a single user, a single door)
MAX_FAILS, WINDOW = 5, 600


def _hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def _load():
    try:
        return json.loads(PATH.read_text())
    except (OSError, ValueError):
        return None


def configured():
    return _load() is not None


def set_password(user, password):
    salt = secrets.token_bytes(16)
    old = _load()
    conf = {"user": user, "salt": salt.hex(), "hash": _hash(password, salt).hex(),
            "secret": (old or {}).get("secret") or secrets.token_hex(32)}
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(conf, f)
    os.replace(tmp, PATH)
    # new session secret: open sessions are invalidated when the password changes
    conf["secret"] = secrets.token_hex(32)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(conf, f)
    os.replace(tmp, PATH)


def cli_passwd():
    user = input("Username: ").strip()
    p1 = getpass.getpass("Password (min 12 characters): ")
    if len(p1) < 12 or not user:
        raise SystemExit("Empty username or password too short: nothing was saved.")
    if p1 != getpass.getpass("Confirm password: "):
        raise SystemExit("The two entries differ: nothing was saved.")
    set_password(user, p1)
    print("Account saved successfully. Open sessions have been closed.")


def locked():
    now = time.time()
    _fails[:] = [t for t in _fails if now - t < WINDOW]
    return len(_fails) >= MAX_FAILS


def check(user, password):
    conf = _load()
    if not conf or locked():
        return False
    ok_user = hmac.compare_digest(user.encode(), conf["user"].encode())
    ok_pw = hmac.compare_digest(_hash(password, bytes.fromhex(conf["salt"])), bytes.fromhex(conf["hash"]))
    if ok_user and ok_pw:
        _fails.clear()
        return True
    _fails.append(time.time())
    time.sleep(1.0)
    return False


def _sign(msg, secret):
    return hmac.new(bytes.fromhex(secret), msg.encode(), hashlib.sha256).hexdigest()


def make_cookie():
    conf = _load()
    exp = str(int(time.time()) + SESSION_SECONDS)
    body = base64.urlsafe_b64encode(exp.encode()).decode()
    return f"{body}.{_sign(body, conf['secret'])}"


def valid_cookie(value):
    conf = _load()
    if not conf or not value or "." not in value:
        return False
    body, sig = value.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(body, conf["secret"])):
        return False
    try:
        return int(base64.urlsafe_b64decode(body.encode()).decode()) > time.time()
    except (ValueError, UnicodeDecodeError):
        return False
