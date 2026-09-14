"""Tests for bounded local SQLite history."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest

from liteparse_agentic_document_extraction.models import (
    DocumentArtifact,
    ProcessingOptions,
    RunStatus,
)
from liteparse_agentic_document_extraction.storage import (
    HistoryError,
    HistoryStore,
    default_database_path,
)


def artifact(identifier: str, *, name: str = "invoice.pdf") -> DocumentArtifact:
    return DocumentArtifact(
        source_name=name,
        source_bytes=b"sensitive source bytes",
        source_hash=identifier * 64,
        artifact_id=identifier,
        status=RunStatus.COMPLETE,
        markdown=f"# Invoice {identifier}",
        output={"schema_version": "2.1", "status": "complete"},
    )


def test_default_database_path_uses_local_app_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert (
        default_database_path() == tmp_path / "LiteParseAgenticDocumentExtraction/history.sqlite3"
    )


def test_round_trip_excludes_source_bytes_and_deletes(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    source = artifact("a")
    options = ProcessingOptions(
        "Extract invoice number", schema={"type": "object"}, extract_data=True
    )

    store.save(source, options)
    summaries = store.list_recent(limit=10)
    restored = store.load(source.artifact_id)

    assert [item.artifact_id for item in summaries] == [source.artifact_id]
    assert restored is not None
    assert restored.artifact.source_bytes == b""
    assert restored.artifact.markdown == source.markdown
    assert restored.artifact.output == source.output
    assert restored.options == options
    assert store.delete(source.artifact_id)
    assert store.load(source.artifact_id) is None
    assert not store.delete(source.artifact_id)


def test_expiry_and_capacity_prune_oldest_records(tmp_path: Path) -> None:
    now = int(time.time())
    store = HistoryStore(tmp_path / "history.sqlite3", retention_days=1, max_bytes=10_000)
    store.save(artifact("a"), ProcessingOptions(), now=now)
    first_size = store.list_recent(limit=10)[0].retained_bytes
    store.max_bytes = first_size + 10
    store.save(artifact("b"), ProcessingOptions(), now=now + 1)

    assert [item.artifact_id for item in store.list_recent(limit=10)] == ["b"]

    store.initialize(now=now + 1 + 24 * 60 * 60)
    assert store.list_recent(limit=10) == []


def test_oversized_result_is_not_saved(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3", max_bytes=10)
    with pytest.raises(HistoryError, match="capacity"):
        store.save(artifact("a"), ProcessingOptions())


def test_parameterized_values_and_corrupt_rows_are_safe(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    store = HistoryStore(path)
    malicious_name = "'; DROP TABLE document_history; --.pdf"
    source = artifact("a", name=malicious_name)
    store.save(source, ProcessingOptions())

    assert store.load("a") is not None
    assert store.list_recent(limit=10)[0].source_name == malicious_name

    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "UPDATE document_history SET output_json = ? WHERE artifact_id = ?",
            ("not-json", "a"),
        )
    with pytest.raises(HistoryError, match="corrupt"):
        store.load("a")


def test_unavailable_database_has_safe_error(tmp_path: Path) -> None:
    directory = tmp_path / "not-a-database"
    directory.mkdir()
    store = HistoryStore(directory)
    with pytest.raises(HistoryError, match="unavailable"):
        store.initialize()
