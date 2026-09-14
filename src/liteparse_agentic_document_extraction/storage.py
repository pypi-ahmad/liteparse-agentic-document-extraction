"""Bounded SQLite history for derived document artifacts.

Stores only derived Markdown/JSON output plus a source hash, never source
bytes (see DocumentArtifact.source_bytes in models.py). Every public method
re-runs initialize(), so this module never assumes the schema/retention pass
has already happened this process. Next: ui.py, the only caller.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import DocumentArtifact, ProcessingOptions, RunStatus
from .settings import HISTORY_RETENTION_DAYS, MAX_HISTORY_BYTES

SCHEMA_VERSION = 1
APP_DATA_DIRECTORY = "LiteParseAgenticDocumentExtraction"
DATABASE_FILENAME = "history.sqlite3"


class HistoryError(RuntimeError):
    """Safe, user-facing history failure.

    Every method below catches the underlying sqlite3/OSError/JSON exception
    and re-raises this instead, so callers (ui.py) only need to handle one
    exception type and never see a raw driver error message.
    """


@dataclass(frozen=True, slots=True)
class HistorySummary:
    """Small record used to render the history selector."""

    artifact_id: str
    source_name: str
    status: RunStatus
    created_at: int
    expires_at: int
    retained_bytes: int


@dataclass(frozen=True, slots=True)
class SavedArtifact:
    """Restored artifact and the options used to create it."""

    artifact: DocumentArtifact
    options: ProcessingOptions
    created_at: int
    expires_at: int


def default_database_path() -> Path:
    """Return the database location in the Windows user profile."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise HistoryError("Local application data directory is unavailable")
    return Path(local_app_data) / APP_DATA_DIRECTORY / DATABASE_FILENAME


class HistoryStore:
    """Create, query, and bound a local document history database."""

    def __init__(
        self,
        path: Path,
        *,
        retention_days: int = HISTORY_RETENTION_DAYS,
        max_bytes: int = MAX_HISTORY_BYTES,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.path = path
        self.retention_seconds = retention_days * 24 * 60 * 60
        self.max_bytes = max_bytes

    @classmethod
    def default(cls) -> HistoryStore:
        """Create a store for the current Windows user."""
        return cls(default_database_path())

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        # busy_timeout: retry instead of failing immediately on the lock
        # contention a single-file SQLite DB can see from concurrent
        # Streamlit sessions/reruns.
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        # Hardening: disallow schema constructs (e.g. views/triggers backed by
        # attached databases) that trusted_schema=ON would otherwise permit.
        connection.execute("PRAGMA trusted_schema = OFF")
        return connection

    def initialize(self, *, now: int | None = None) -> None:
        """Create the schema and remove expired or over-capacity rows."""
        timestamp = int(time.time()) if now is None else now
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("PRAGMA journal_mode = WAL")
                # 0 means a fresh/empty file; anything else must match exactly.
                # There is no migration path here - an older or newer schema
                # version is refused rather than guessed at.
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version not in {0, SCHEMA_VERSION}:
                    raise HistoryError("History database version is unsupported")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS document_history (
                        artifact_id TEXT PRIMARY KEY,
                        source_name TEXT NOT NULL,
                        source_hash TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ('complete', 'partial', 'failed')),
                        processing_options TEXT NOT NULL,
                        markdown TEXT NOT NULL,
                        output_json TEXT NOT NULL,
                        error TEXT,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL,
                        retained_bytes INTEGER NOT NULL CHECK (retained_bytes >= 0)
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_document_history_created "
                    "ON document_history(created_at DESC)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_document_history_expires "
                    "ON document_history(expires_at)"
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self._purge_expired(connection, timestamp)
                self._prune(connection)
        except HistoryError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise HistoryError("History database is unavailable") from exc

    def save(
        self,
        artifact: DocumentArtifact,
        options: ProcessingOptions,
        *,
        now: int | None = None,
    ) -> None:
        """Save one derived result without retaining its source bytes."""
        timestamp = int(time.time()) if now is None else now
        expires_at = timestamp + self.retention_seconds
        try:
            options_json = json.dumps(asdict(options), ensure_ascii=False, separators=(",", ":"))
            output_json = json.dumps(artifact.output, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise HistoryError("Result could not be serialized for history") from exc
        retained_bytes = sum(
            len(value.encode("utf-8"))
            for value in (
                artifact.artifact_id,
                artifact.source_name,
                artifact.source_hash,
                artifact.status.value,
                options_json,
                artifact.markdown,
                output_json,
                artifact.error or "",
            )
        )
        if retained_bytes > self.max_bytes:
            raise HistoryError("Result exceeds the saved-history capacity")

        self.initialize(now=timestamp)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO document_history (
                        artifact_id, source_name, source_hash, status, processing_options,
                        markdown, output_json, error, created_at, expires_at, retained_bytes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(artifact_id) DO UPDATE SET
                        source_name = excluded.source_name,
                        source_hash = excluded.source_hash,
                        status = excluded.status,
                        processing_options = excluded.processing_options,
                        markdown = excluded.markdown,
                        output_json = excluded.output_json,
                        error = excluded.error,
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at,
                        retained_bytes = excluded.retained_bytes
                    """,
                    (
                        artifact.artifact_id,
                        artifact.source_name,
                        artifact.source_hash,
                        artifact.status.value,
                        options_json,
                        artifact.markdown,
                        output_json,
                        artifact.error,
                        timestamp,
                        expires_at,
                        retained_bytes,
                    ),
                )
                self._purge_expired(connection, timestamp)
                self._prune(connection, protected_id=artifact.artifact_id)
        except (OSError, sqlite3.Error) as exc:
            raise HistoryError("Result could not be saved to history") from exc

    def list_recent(self, *, limit: int) -> list[HistorySummary]:
        """Return newest-first history metadata without loading document content."""
        if limit < 1:
            raise ValueError("limit must be positive")
        self.initialize()
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT artifact_id, source_name, status, created_at, expires_at, retained_bytes
                    FROM document_history
                    ORDER BY created_at DESC, artifact_id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [
                HistorySummary(
                    artifact_id=row["artifact_id"],
                    source_name=row["source_name"],
                    status=RunStatus(row["status"]),
                    created_at=row["created_at"],
                    expires_at=row["expires_at"],
                    retained_bytes=row["retained_bytes"],
                )
                for row in rows
            ]
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise HistoryError("Saved history could not be read") from exc

    def load(self, artifact_id: str) -> SavedArtifact | None:
        """Restore one result with an empty source-byte field."""
        self.initialize()
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM document_history WHERE artifact_id = ?", (artifact_id,)
                ).fetchone()
            if row is None:
                return None
            output = json.loads(row["output_json"])
            option_values = json.loads(row["processing_options"])
            if not isinstance(output, dict) or not isinstance(option_values, dict):
                raise ValueError("invalid saved JSON")
            artifact = DocumentArtifact(
                source_name=row["source_name"],
                source_bytes=b"",
                source_hash=row["source_hash"],
                artifact_id=row["artifact_id"],
                status=RunStatus(row["status"]),
                markdown=row["markdown"],
                output=output,
                error=row["error"],
            )
            return SavedArtifact(
                artifact=artifact,
                options=ProcessingOptions(**option_values),
                created_at=row["created_at"],
                expires_at=row["expires_at"],
            )
        except (json.JSONDecodeError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise HistoryError("Saved history record is corrupt") from exc

    def delete(self, artifact_id: str) -> bool:
        """Delete one saved record by its generated artifact ID."""
        self.initialize()
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    "DELETE FROM document_history WHERE artifact_id = ?", (artifact_id,)
                )
                return cursor.rowcount > 0
        except (OSError, sqlite3.Error) as exc:
            raise HistoryError("Saved history record could not be deleted") from exc

    @staticmethod
    def _purge_expired(connection: sqlite3.Connection, now: int) -> None:
        connection.execute("DELETE FROM document_history WHERE expires_at <= ?", (now,))

    def _prune(self, connection: sqlite3.Connection, protected_id: str | None = None) -> None:
        """Evict oldest rows first until under max_bytes.

        protected_id excludes the row `save()` just wrote so a fresh result
        is never evicted to make room for itself.
        """
        total = int(
            connection.execute(
                "SELECT COALESCE(SUM(retained_bytes), 0) FROM document_history"
            ).fetchone()[0]
        )
        while total > self.max_bytes:
            if protected_id is None:
                row = connection.execute(
                    """
                    SELECT artifact_id, retained_bytes FROM document_history
                    ORDER BY created_at, artifact_id LIMIT 1
                    """
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT artifact_id, retained_bytes FROM document_history
                    WHERE artifact_id <> ? ORDER BY created_at, artifact_id LIMIT 1
                    """,
                    (protected_id,),
                ).fetchone()
            if row is None:
                raise HistoryError("Saved-history capacity could not be enforced")
            connection.execute(
                "DELETE FROM document_history WHERE artifact_id = ?", (row["artifact_id"],)
            )
            total -= int(row["retained_bytes"])


__all__ = [
    "HistoryError",
    "HistoryStore",
    "HistorySummary",
    "SavedArtifact",
    "default_database_path",
]
