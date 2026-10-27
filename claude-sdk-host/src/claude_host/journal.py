"""Small durable accounting journal; prompts, credentials and source never enter SQLite."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .contracts import RunFailure

TERMINAL_STATES = {
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "budget_exceeded",
    "consumer_lost",
    "interrupted",
}
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


class Journal:
    def __init__(self, path: Path, max_bytes: int = 268_435_456) -> None:
        self.path = path
        self.max_bytes = max_bytes
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, app_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    digest TEXT NOT NULL, profile TEXT NOT NULL, model TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued', stop_reason TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL,
                    last_seq INTEGER NOT NULL DEFAULT 0, ack_seq INTEGER NOT NULL DEFAULT 0,
                    accounting_complete INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    submission_seq INTEGER, UNIQUE(app_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    session_id TEXT NOT NULL REFERENCES sessions(id), seq INTEGER NOT NULL,
                    kind TEXT NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL,
                    PRIMARY KEY(session_id, seq)
                );
                """
            )
        self.interrupt_stale()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def disk_bytes(self) -> int:
        return sum(p.stat().st_size for p in (self.path, Path(str(self.path) + "-wal")) if p.exists())

    def create(
        self,
        *,
        session_id: str,
        app_id: str,
        request_id: str,
        digest: str,
        profile: str,
        model: str,
        expires_at: float,
    ) -> tuple[dict[str, Any], bool]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sessions WHERE app_id=? AND request_id=?", (app_id, request_id)).fetchone()
            if row is not None:
                if row["digest"] != digest:
                    raise RunFailure("idempotency_conflict", 409)
                return self.public(row), False
            if self.disk_bytes() >= self.max_bytes:
                raise RunFailure("journal_full", 503)
            now = time.time()
            db.execute(
                "INSERT INTO sessions(id,app_id,request_id,digest,profile,model,"
                "created_at,updated_at,expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (session_id, app_id, request_id, digest, profile, model, now, now, expires_at),
            )
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            return self.public(row), True

    @staticmethod
    def public(row: sqlite3.Row) -> dict[str, Any]:
        result = {
            key: row[key]
            for key in (
                "id",
                "profile",
                "model",
                "state",
                "stop_reason",
                "created_at",
                "updated_at",
                "expires_at",
                "last_seq",
                "ack_seq",
                "submission_seq",
            )
        }
        result["accounting_complete"] = bool(row["accounting_complete"])
        result["usage"] = {key: row[key] for key in USAGE_FIELDS}
        result["budget_tokens"] = row["input_tokens"] + row["cache_creation_input_tokens"] + row["output_tokens"]
        result["result_acknowledged"] = row["submission_seq"] is not None and row["ack_seq"] >= row["submission_seq"]
        return result

    def get(self, session_id: str, app_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND app_id=?", (session_id, app_id)).fetchone()
        if row is None:
            raise RunFailure("session_not_found", 404)
        return self.public(row)

    def find_request(self, app_id: str, request_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT id,digest FROM sessions WHERE app_id=? AND request_id=?", (app_id, request_id)
            ).fetchone()
        return dict(row) if row else None

    def set_running(self, session_id: str) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE sessions SET state='running',updated_at=? WHERE id=? AND state='queued'",
                (time.time(), session_id),
            )

    def append(self, session_id: str, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        """Assign every event a sequence; persist only a whitelisted non-content projection."""
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                raise RunFailure("session_not_found", 404)
            seq = row["last_seq"] + 1
            db.execute("UPDATE sessions SET last_seq=?,updated_at=? WHERE id=?", (seq, now, session_id))
            persisted: dict[str, Any] | None = None
            if kind == "usage":
                persisted = {key: self.counter(data.get(key, 0)) for key in USAGE_FIELDS}
                persisted["budget_tokens"] = (
                    persisted["input_tokens"] + persisted["cache_creation_input_tokens"] + persisted["output_tokens"]
                )
                for key in USAGE_FIELDS:
                    db.execute(f"UPDATE sessions SET {key}={key}+? WHERE id=?", (persisted[key], session_id))
            elif kind == "terminal":
                state = data.get("state", "failed")
                if state not in TERMINAL_STATES:
                    raise RunFailure("invalid_terminal_state")
                reason = str(data.get("stop_reason") or "")[:100]
                complete = bool(data.get("accounting_complete", False))
                persisted = {"state": state, "stop_reason": reason, "accounting_complete": complete}
                db.execute(
                    "UPDATE sessions SET state=?,stop_reason=?,accounting_complete=? WHERE id=?",
                    (state, reason, int(complete), session_id),
                )
            elif kind == "started":
                persisted = {"model": row["model"]}
            elif kind == "submission":
                db.execute("UPDATE sessions SET submission_seq=? WHERE id=?", (seq, session_id))
            if persisted is not None:
                db.execute(
                    "INSERT INTO events(session_id,seq,kind,data,created_at) VALUES (?,?,?,?,?)",
                    (session_id, seq, kind, json.dumps(persisted, separators=(",", ":")), now),
                )
        return {
            "session_id": session_id,
            "seq": seq,
            "event_id": f"{session_id}:{seq}",
            "timestamp": now,
            "type": kind,
            "data": persisted if persisted is not None else data,
        }

    @staticmethod
    def counter(value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1_000_000_000:
            raise RunFailure("invalid_usage_counter")
        return value

    def events(self, session_id: str, app_id: str, after: int = 0) -> list[dict[str, Any]]:
        self.get(session_id, app_id)
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE session_id=? AND seq>? ORDER BY seq", (session_id, after)
            ).fetchall()
        return [
            {
                "session_id": session_id,
                "seq": row["seq"],
                "event_id": f"{session_id}:{row['seq']}",
                "timestamp": row["created_at"],
                "type": row["kind"],
                "data": json.loads(row["data"]),
            }
            for row in rows
        ]

    def ack(self, session_id: str, app_id: str, seq: int) -> dict[str, Any]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sessions WHERE id=? AND app_id=?", (session_id, app_id)).fetchone()
            if row is None:
                raise RunFailure("session_not_found", 404)
            if isinstance(seq, bool) or seq < 0 or seq > row["last_seq"]:
                raise RunFailure("invalid_ack_sequence", 400)
            db.execute(
                "UPDATE sessions SET ack_seq=MAX(ack_seq,?),updated_at=? WHERE id=?",
                (seq, time.time(), session_id),
            )
        return self.get(session_id, app_id)

    def interrupt_stale(self) -> None:
        with self.connection() as db:
            rows = db.execute("SELECT id FROM sessions WHERE state IN ('queued','starting','running')").fetchall()
        for row in rows:
            self.append(
                row["id"],
                "terminal",
                {
                    "state": "interrupted",
                    "stop_reason": "host_restarted",
                    "accounting_complete": False,
                },
            )

    def cleanup(self) -> None:
        cutoff = time.time() - 7 * 86400
        with self.connection() as db:
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM sessions WHERE updated_at<? AND ack_seq>=last_seq "
                    "AND state NOT IN ('queued','starting','running')",
                    (cutoff,),
                )
            ]
            for session_id in ids:
                db.execute("DELETE FROM events WHERE session_id=?", (session_id,))
                db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
