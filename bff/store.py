"""Persistent opaque sessions, atomic login throttling, and a private audit journal."""

import hashlib
import os
import secrets
import sqlite3
import stat
import time
from contextlib import contextmanager

from bff.config import Settings


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, settings: Settings, clock=time.time):
        self.settings, self.clock = settings, clock
        path = settings.database
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.exists():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        # Validate metadata only; never load the full session database into memory.
        self._check_empty(path)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    hash TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL, credential TEXT NOT NULL,
                    created REAL NOT NULL, touched REAL NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS throttle (key TEXT PRIMARY KEY, started REAL NOT NULL,
                    attempts INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at REAL NOT NULL,
                    operation TEXT NOT NULL, resource TEXT NOT NULL, outcome TEXT NOT NULL,
                    status INTEGER NOT NULL, duration_ms INTEGER NOT NULL);
            """)

    @staticmethod
    def _check_empty(path):
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid not in (0, os.geteuid())
        ):
            raise ValueError("Unsafe database permissions")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.settings.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def attempt(self, peer: str) -> bool:
        now = self.clock()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM throttle WHERE started<=?", (now - self.settings.login_window,))
            # Global cap protects against address rotation; peer keys are hashed, no raw IP stored.
            for key, cap in (
                ("global", self.settings.login_attempts * 5),
                (digest(peer), self.settings.login_attempts),
            ):
                row = db.execute("SELECT attempts FROM throttle WHERE key=?", (key,)).fetchone()
                if row and row[0] >= cap:
                    return False
            for key in ("global", digest(peer)):
                db.execute(
                    "INSERT INTO throttle VALUES (?,?,1) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1",
                    (key, now),
                )
        return True

    def create(self, credential: str, old: str | None):
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), self.clock()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM sessions WHERE expires<=? OR touched<=? OR credential!=?",
                (now, now - self.settings.idle_seconds, credential),
            )
            if old:
                db.execute("DELETE FROM sessions WHERE hash=?", (digest(old),))
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                (
                    digest(token),
                    digest(csrf),
                    credential,
                    now,
                    now,
                    now + self.settings.absolute_seconds,
                ),
            )
            db.execute(
                "DELETE FROM sessions WHERE hash NOT IN (SELECT hash FROM sessions ORDER BY created DESC, rowid DESC LIMIT ?)",
                (self.settings.max_sessions,),
            )
            db.execute(
                "INSERT INTO audit(at,operation,resource,outcome,status,duration_ms) VALUES (?,?,?,?,?,?)",
                (now, "session.create", "", "allow", 200, 0),
            )
        return token, csrf

    def session(self, token: str | None, credential: str):
        if not token or len(token) > 128:
            return None
        now = self.clock()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM sessions WHERE expires<=? OR touched<=? OR credential!=?",
                (now, now - self.settings.idle_seconds, credential),
            )
            row = db.execute("SELECT * FROM sessions WHERE hash=?", (digest(token),)).fetchone()
            if row:
                db.execute("UPDATE sessions SET touched=? WHERE hash=?", (now, row["hash"]))
            return row

    def csrf(self, token: str):
        csrf = secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute(
                "UPDATE sessions SET csrf_hash=? WHERE hash=?", (digest(csrf), digest(token))
            )
        return csrf

    def revoke(self, token: str | None = None):
        with self.connection() as db:
            if token:
                db.execute("DELETE FROM sessions WHERE hash=?", (digest(token),))
            else:
                db.execute("DELETE FROM sessions")
            db.execute(
                "INSERT INTO audit(at,operation,resource,outcome,status,duration_ms) VALUES (?,?,?,?,?,?)",
                (self.clock(), "session.revoke", "", "allow", 200, 0),
            )

    def audit(self, operation: str, resource: str, status: int, duration: int):
        with self.connection() as db:
            db.execute(
                "INSERT INTO audit(at,operation,resource,outcome,status,duration_ms) VALUES (?,?,?,?,?,?)",
                (
                    self.clock(),
                    operation,
                    resource,
                    "allow" if status < 400 else "deny",
                    status,
                    duration,
                ),
            )
