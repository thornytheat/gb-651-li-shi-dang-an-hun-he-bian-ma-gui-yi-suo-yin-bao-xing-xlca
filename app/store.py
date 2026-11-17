from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SESSION_COLUMNS = (
    "session_id", "file_name", "version", "total_length", "declared_sha256",
    "status", "confirmed_length", "created_at", "completed_at", "encoding",
    "receipt_id", "reason",
)


class Store:
    """SQLite 持久化。

    分段接收把每个已确认片段单独落库，并在数据库层禁止改写或删除，
    因此旧回执指向的字节即使在新修订接替之后也保持原样。
    """

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS runs (digest TEXT PRIMARY KEY, run_id TEXT NOT NULL, result TEXT NOT NULL)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS intake_sessions (
                    session_id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    total_length INTEGER NOT NULL,
                    declared_sha256 TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    confirmed_length INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    encoding TEXT,
                    receipt_id TEXT,
                    reason TEXT,
                    UNIQUE (file_name, version)
                )
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(intake_sessions)")}
            if "reason" not in columns:
                db.execute("ALTER TABLE intake_sessions ADD COLUMN reason TEXT")
            db.execute("""
                CREATE TABLE IF NOT EXISTS intake_chunks (
                    session_id TEXT NOT NULL,
                    chunk_offset INTEGER NOT NULL,
                    chunk_length INTEGER NOT NULL,
                    chunk_sha256 TEXT NOT NULL,
                    data BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, chunk_offset)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS intake_receipts (
                    session_id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL UNIQUE,
                    file_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    byte_length INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    encoding TEXT NOT NULL,
                    receipt TEXT NOT NULL,
                    archive TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (file_name, version)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS intake_receipts_file ON intake_receipts(file_name, version)")
            # 已确认字节与回执只允许写入一次；任何 UPDATE/DELETE 在数据库层直接失败。
            for table in ("intake_chunks", "intake_receipts"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"""
                        CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()}
                        BEFORE {action} ON {table}
                        BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END
                    """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS intake_sessions_no_rewind
                BEFORE UPDATE OF confirmed_length ON intake_sessions
                WHEN NEW.confirmed_length < OLD.confirmed_length
                BEGIN SELECT RAISE(ABORT, 'confirmed_length cannot decrease'); END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS intake_sessions_complete_sealed
                BEFORE UPDATE ON intake_sessions
                WHEN OLD.status = 'COMPLETE'
                 AND (NEW.status <> 'COMPLETE'
                      OR NEW.confirmed_length <> OLD.confirmed_length
                      OR NEW.receipt_id IS NOT OLD.receipt_id)
                BEGIN SELECT RAISE(ABORT, 'completed intake session is sealed'); END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS intake_sessions_no_delete_complete
                BEFORE DELETE ON intake_sessions
                WHEN OLD.status = 'COMPLETE'
                BEGIN SELECT RAISE(ABORT, 'completed intake session cannot be deleted'); END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS intake_sessions_no_reidentify
                BEFORE UPDATE OF file_name, version, total_length, declared_sha256 ON intake_sessions
                WHEN NEW.file_name <> OLD.file_name
                  OR NEW.version <> OLD.version
                  OR NEW.total_length <> OLD.total_length
                  OR (OLD.declared_sha256 IS NOT NULL AND NEW.declared_sha256 IS NOT OLD.declared_sha256)
                BEGIN SELECT RAISE(ABORT, 'intake identity is immutable'); END
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @contextmanager
    def write_tx(self):
        """写事务：BEGIN IMMEDIATE 让并发续传串行化，避免互相覆盖。"""
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        started = False
        try:
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("BEGIN IMMEDIATE")
            started = True
            yield db
            db.execute("COMMIT")
        except BaseException:
            if started:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    # ---- 既有批次运行记录 ----

    def record(self, digest: str, run_id: str, result: dict) -> dict:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?)",
                       (digest, run_id, json.dumps(result, ensure_ascii=False, sort_keys=True)))
            row = db.execute("SELECT run_id, result FROM runs WHERE digest=?", (digest,)).fetchone()
        return {"run_id": row[0], "result": json.loads(row[1])}

    def count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def all(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT run_id, digest, result FROM runs ORDER BY run_id").fetchall()
        return [{"run_id": r[0], "digest": r[1], "result": json.loads(r[2])} for r in rows]

    # ---- 分段接收 ----

    @staticmethod
    def _session_dict(row) -> dict | None:
        if row is None:
            return None
        value = dict(zip(SESSION_COLUMNS, row))
        value["next_offset"] = value["confirmed_length"]
        return value

    def intake_session(self, session_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                f"SELECT {', '.join(SESSION_COLUMNS)} FROM intake_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        return self._session_dict(row)

    def intake_session_in(self, db, session_id: str) -> dict | None:
        row = db.execute(
            f"SELECT {', '.join(SESSION_COLUMNS)} FROM intake_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return self._session_dict(row)

    def intake_sessions(self, file_name: str | None = None, db=None) -> list[dict]:
        own = db is None
        conn = self.connect() if own else db
        try:
            if file_name is None:
                rows = conn.execute(
                    f"SELECT {', '.join(SESSION_COLUMNS)} FROM intake_sessions ORDER BY file_name, version"
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {', '.join(SESSION_COLUMNS)} FROM intake_sessions WHERE file_name=? ORDER BY version",
                    (file_name,),
                ).fetchall()
        finally:
            if own:
                conn.close()
        return [self._session_dict(row) for row in rows]

    def find_intake_session(self, db, file_name: str, declared_sha256: str | None,
                            total_length: int) -> dict | None:
        if declared_sha256 is None:
            row = db.execute(
                f"SELECT {', '.join(SESSION_COLUMNS)} FROM intake_sessions "
                "WHERE file_name=? AND declared_sha256 IS NULL AND total_length=? "
                "ORDER BY version LIMIT 1",
                (file_name, total_length),
            ).fetchone()
        else:
            row = db.execute(
                f"SELECT {', '.join(SESSION_COLUMNS)} FROM intake_sessions "
                "WHERE file_name=? AND declared_sha256=? AND total_length=? "
                "ORDER BY version LIMIT 1",
                (file_name, declared_sha256, total_length),
            ).fetchone()
        return self._session_dict(row)

    def intake_max_version(self, db, file_name: str) -> int:
        row = db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM intake_sessions WHERE file_name=?",
            (file_name,),
        ).fetchone()
        return int(row[0])

    def insert_intake_session(self, db, values: dict) -> None:
        db.execute(
            """
            INSERT INTO intake_sessions
                (session_id, file_name, version, total_length, declared_sha256,
                 status, confirmed_length, created_at, completed_at, encoding, receipt_id, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["session_id"], values["file_name"], values["version"],
                values["total_length"], values["declared_sha256"],
                values.get("status", "OPEN"), values.get("confirmed_length", 0),
                values["created_at"], values.get("completed_at"),
                values.get("encoding"), values.get("receipt_id"), values.get("reason"),
            ),
        )

    def chunk_count(self, session_id: str) -> int:
        with self.connect() as db:
            return db.execute(
                "SELECT COUNT(*) FROM intake_chunks WHERE session_id=?", (session_id,)
            ).fetchone()[0]

    def intake_chunks(self, session_id: str, db=None) -> list[dict]:
        own = db is None
        conn = self.connect() if own else db
        try:
            rows = conn.execute(
                "SELECT chunk_offset, chunk_length, chunk_sha256, data, created_at "
                "FROM intake_chunks WHERE session_id=? ORDER BY chunk_offset",
                (session_id,),
            ).fetchall()
        finally:
            if own:
                conn.close()
        return [
            {"offset": r[0], "length": r[1], "sha256": r[2],
             "chunk_length": r[1], "chunk_sha256": r[2],
             "data": bytes(r[3]), "created_at": r[4]}
            for r in rows
        ]

    def intake_chunk(self, db, session_id: str, offset: int) -> dict | None:
        row = db.execute(
            "SELECT chunk_offset, chunk_length, chunk_sha256, data, created_at "
            "FROM intake_chunks WHERE session_id=? AND chunk_offset=?",
            (session_id, offset),
        ).fetchone()
        if row is None:
            return None
        return {"offset": row[0], "length": row[1], "sha256": row[2],
                "chunk_length": row[1], "chunk_sha256": row[2],
                "data": bytes(row[3]), "created_at": row[4]}

    def insert_intake_chunk(self, db, session_id: str, offset: int, data: bytes,
                            sha256: str, created_at: str) -> None:
        db.execute(
            "INSERT INTO intake_chunks (session_id, chunk_offset, chunk_length, chunk_sha256, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, offset, len(data), sha256, sqlite3.Binary(data), created_at),
        )

    def set_confirmed_length(self, db, session_id: str, confirmed_length: int) -> None:
        db.execute(
            "UPDATE intake_sessions SET confirmed_length=? WHERE session_id=?",
            (confirmed_length, session_id),
        )

    def mark_complete(self, db, session_id: str, encoding: str, receipt_id: str,
                      completed_at: str, reason: str = "OK") -> None:
        db.execute(
            "UPDATE intake_sessions SET status='COMPLETE', encoding=?, receipt_id=?, "
            "completed_at=?, reason=? WHERE session_id=?",
            (encoding, receipt_id, completed_at, reason, session_id),
        )

    def insert_intake_receipt(self, db, *, session_id: str, receipt_id: str, file_name: str,
                              version: int, byte_length: int, sha256: str, encoding: str,
                              receipt: dict, archive: dict, created_at: str) -> None:
        db.execute(
            "INSERT INTO intake_receipts "
            "(session_id, receipt_id, file_name, version, byte_length, sha256, encoding, receipt, archive, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, receipt_id, file_name, version, byte_length, sha256, encoding,
                json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                json.dumps(archive, ensure_ascii=False, sort_keys=True),
                created_at,
            ),
        )

    def intake_receipt(self, session_id: str) -> dict | None:
        with self.connect() as db:
            return self.intake_receipt_in(db, session_id)

    def intake_receipt_in(self, db, session_id: str) -> dict | None:
        row = db.execute(
            "SELECT session_id, receipt_id, file_name, version, byte_length, sha256, "
            "encoding, receipt, archive, created_at FROM intake_receipts WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return self._receipt_dict(row)

    def intake_receipts(self, file_name: str | None = None) -> list[dict]:
        with self.connect() as db:
            if file_name is None:
                rows = db.execute(
                    "SELECT session_id, receipt_id, file_name, version, byte_length, sha256, "
                    "encoding, receipt, archive, created_at FROM intake_receipts "
                    "ORDER BY file_name, version"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT session_id, receipt_id, file_name, version, byte_length, sha256, "
                    "encoding, receipt, archive, created_at FROM intake_receipts "
                    "WHERE file_name=? ORDER BY version",
                    (file_name,),
                ).fetchall()
        return [self._receipt_dict(row) for row in rows]

    @staticmethod
    def _receipt_dict(row) -> dict | None:
        if row is None:
            return None
        return {
            "session_id": row[0], "receipt_id": row[1], "file_name": row[2],
            "version": row[3], "byte_length": row[4], "sha256": row[5],
            "encoding": row[6], "receipt": json.loads(row[7]),
            "archive": json.loads(row[8]), "created_at": row[9],
        }

    def bytes_between(self, db, session_id: str, start: int, end: int) -> bytes | None:
        """返回 [start, end) 的已确认字节；覆盖不连续时返回 None。"""
        rows = db.execute(
            "SELECT chunk_offset, chunk_length, data FROM intake_chunks "
            "WHERE session_id=? AND chunk_offset < ? AND chunk_offset + chunk_length > ? "
            "ORDER BY chunk_offset",
            (session_id, end, start),
        ).fetchall()
        cursor = start
        parts: list[bytes] = []
        for offset, length, data in rows:
            if offset > cursor:
                return None
            blob = bytes(data)
            local = cursor - offset
            take = min(length - local, end - cursor)
            if take <= 0:
                continue
            parts.append(blob[local:local + take])
            cursor += take
            if cursor >= end:
                break
        return b"".join(parts) if cursor == end else None

    def assembled_bytes(self, session_id: str, db=None) -> bytes:
        chunks = self.intake_chunks(session_id, db)
        return b"".join(chunk["data"] for chunk in chunks)
