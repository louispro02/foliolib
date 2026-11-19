"""SQLite database (WAL): imported records, instruments, prices, rates, settings. Everything lives in the data directory (/data in Docker, ~/.foliolib on a computer; mode 700)."""
import json
import os
import sqlite3
import time
from pathlib import Path



def _default_data_dir():
    """FOLIOLIB_DATA if set; else /data when it exists and is writable (the Docker image); else ~/.foliolib (a computer)."""
    env = os.environ.get("FOLIOLIB_DATA")
    if env:
        return Path(env)
    root = Path("/data")
    if root.is_dir() and os.access(root, os.W_OK):
        return root
    return Path.home() / ".foliolib"


DATA = _default_data_dir()
DB_PATH = DATA / "foliolib.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, n INTEGER, added INTEGER, new INTEGER, sha TEXT);
CREATE TABLE IF NOT EXISTS records(key TEXT PRIMARY KEY, kind TEXT, file_id INTEGER, body TEXT);
CREATE TABLE IF NOT EXISTS instruments(isin TEXT PRIMARY KEY, symbol TEXT, ccy TEXT, manual INTEGER DEFAULT 0, tried INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS prices(symbol TEXT, day TEXT, close REAL, PRIMARY KEY(symbol, day));
CREATE TABLE IF NOT EXISTS quote(symbol TEXT PRIMARY KEY, price REAL, ccy TEXT, at INTEGER, source TEXT);
CREATE TABLE IF NOT EXISTS fx(ccy TEXT, day TEXT, rate REAL, PRIMARY KEY(ccy, day));
CREATE TABLE IF NOT EXISTS aliases(label TEXT PRIMARY KEY, isin TEXT);
"""


def connect(path=None):
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(p, timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    if "sha" not in [r[1] for r in db.execute("PRAGMA table_info(files)")]:
        db.execute("ALTER TABLE files ADD COLUMN sha TEXT")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return db


def meta_get(db, k, default=""):
    r = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def meta_set(db, k, v):
    db.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
    db.commit()


UPLOADS = DATA / "uploads"


def save_raw(raw):
    """Keep the uploaded file (mode 600): a future parser fix can then re-read everything without re-uploading."""
    import hashlib
    sha = hashlib.sha256(raw).hexdigest()[:20]
    UPLOADS.mkdir(parents=True, exist_ok=True)
    os.chmod(UPLOADS, 0o700)
    p = UPLOADS / (sha + ".csv")
    if not p.exists():
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    return sha


def add_file(db, name, kind, records, sha=None):
    """Add the new records; returns (number in the file, number of new ones)."""
    cur = db.execute("INSERT INTO files(name,kind,n,added,new,sha) VALUES(?,?,?,?,0,?)", (name[:120], kind, len(records), int(time.time()), sha))
    fid, new = cur.lastrowid, 0
    for r in records:
        k = r.pop("key")
        cur = db.execute("INSERT OR IGNORE INTO records(key,kind,file_id,body) VALUES(?,?,?,?)", (k, kind, fid, json.dumps(r, ensure_ascii=False)))
        new += cur.rowcount
    db.execute("UPDATE files SET new=? WHERE id=?", (new, fid))
    db.commit()
    return len(records), new


def all_records(db):
    return [json.loads(b) for (b,) in db.execute("SELECT body FROM records")]


def aliases(db):
    return dict(db.execute("SELECT label, isin FROM aliases"))


def wipe(db):
    """Erase imported data (not prices, which can be fetched again; a demo database is erased completely). Irreversible."""
    db.execute("DELETE FROM records")
    db.execute("DELETE FROM files")
    db.execute("DELETE FROM aliases")
    if meta_get(db, "demo"):      # demo database: its prices are synthetic too, so leave nothing behind
        for table in ("prices", "quote", "instruments", "fx"):
            db.execute(f"DELETE FROM {table}")
        db.execute("DELETE FROM meta WHERE k IN ('demo', 'last_refresh', 'last_error', 'reimport')")
    db.commit()


def migrate(db):
    """Re-read records whose parser has changed. Preserved files are re-read automatically; files uploaded before
    preservation must be re-uploaded (the page says so). Returns the list of kinds to re-upload."""
    import parsers
    done = int(meta_get(db, "parser_version", "1") or 1)
    if done >= parsers.PARSER_VERSION:
        return []
    kinds = {k for v in range(done + 1, parsers.PARSER_VERSION + 1) for k in parsers.AFFECTED.get(v, ())}
    need = set()
    for kind in sorted(kinds):
        files = db.execute("SELECT id, name, sha FROM files WHERE kind=? ORDER BY id", (kind,)).fetchall()
        db.execute("DELETE FROM records WHERE kind=?", (kind,))
        db.execute("DELETE FROM files WHERE kind=?", (kind,))
        db.commit()
        for _fid, name, sha in files:
            raw = (UPLOADS / (sha + ".csv")) if sha else None
            if raw and raw.exists():
                k, recs = parsers.parse(raw.read_bytes())
                add_file(db, name, k, recs, sha)
            else:
                need.add(kind)
    meta_set(db, "parser_version", str(parsers.PARSER_VERSION))
    meta_set(db, "reimport", ",".join(sorted(need)))
    return sorted(need)
