"""Feedback persistence and retrieval for transaction classification."""

from __future__ import annotations

import json
import sqlite3
from array import array
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Sequence

from .models import Transaction

DEFAULT_FEEDBACK_DB = Path("budget_feedback.sqlite3")


@dataclass(slots=True)
class StoredLabel:
    """Represents a previously labelled transaction."""

    transaction: Transaction
    suggested_category: Optional[str]
    final_category: str
    accepted: bool
    overwritten: bool
    similarity: float
    timestamp: datetime


class FeedbackStore:
    """SQLite-backed persistence for transaction feedback and embeddings."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.path = Path(db_path) if db_path else DEFAULT_FEEDBACK_DB
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread`` is disabled so the store can be shared by the
        # Tkinter UI thread and the worker thread that calls the OpenAI API.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._initialise_schema()

    # ------------------------------------------------------------------ #
    # Schema management
    # ------------------------------------------------------------------ #
    def _initialise_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS txn_labels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    normalized_key TEXT,
                    features_json TEXT NOT NULL,
                    suggested_category TEXT,
                    final_category TEXT NOT NULL,
                    accepted INTEGER NOT NULL,
                    overwritten INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS txn_embeddings (
                    label_id INTEGER PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    FOREIGN KEY(label_id) REFERENCES txn_labels(id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_txn_labels_normalized_key ON txn_labels(normalized_key)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_txn_labels_timestamp ON txn_labels(timestamp DESC)"
            )

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #
    def add_label(
        self,
        *,
        normalized_key: str | None,
        features: dict,
        suggested_category: Optional[str],
        final_category: str,
        accepted: bool,
        overwritten: bool,
        embedding: Optional[Sequence[float]],
    ) -> None:
        """Store feedback details and their optional embedding."""

        payload = json.dumps(features, ensure_ascii=False)
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO txn_labels (
                    normalized_key,
                    features_json,
                    suggested_category,
                    final_category,
                    accepted,
                    overwritten
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_key,
                    payload,
                    suggested_category,
                    final_category,
                    int(accepted),
                    int(overwritten),
                ),
            )
            label_id = cursor.lastrowid
            if embedding is not None:
                blob = array("f", embedding).tobytes()
                self._conn.execute(
                    "INSERT OR REPLACE INTO txn_embeddings (label_id, embedding) VALUES (?, ?)",
                    (label_id, blob),
                )

    # ------------------------------------------------------------------ #
    # Retrieval helpers
    # ------------------------------------------------------------------ #
    def iter_recent(self, limit: int = 50) -> Iterator[StoredLabel]:
        """Yield recent feedback entries ordered by recency."""

        rows = self._conn.execute(
            """
            SELECT id, features_json, suggested_category, final_category,
                   accepted, overwritten, timestamp
            FROM txn_labels
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        for row in rows:
            yield StoredLabel(
                transaction=self._transaction_from_payload(row[1]),
                suggested_category=row[2],
                final_category=row[3],
                accepted=bool(row[4]),
                overwritten=bool(row[5]),
                similarity=0.0,
                timestamp=self._parse_timestamp(row[6]),
            )

    def lookup_similar(
        self, embedding: Sequence[float], *, limit: int = 10
    ) -> list[StoredLabel]:
        """Return the feedback entries whose embeddings are closest."""

        rows = list(
            self._conn.execute(
                """
                SELECT l.features_json, l.suggested_category, l.final_category,
                       l.accepted, l.overwritten, l.timestamp, e.embedding
                FROM txn_labels AS l
                JOIN txn_embeddings AS e ON e.label_id = l.id
                """
            )
        )
        if not rows:
            return []

        # Compute cosine similarity in Python; the dataset is expected to be small.
        target = list(embedding)
        target_norm = self._vector_norm(target)
        scored: list[StoredLabel] = []
        for features_json, suggested, final, accepted, overwritten, ts, blob in rows:
            vector = self._vector_from_blob(blob)
            similarity = 0.0
            denom = target_norm * self._vector_norm(vector)
            if denom:
                similarity = self._dot_product(target, vector) / denom
            scored.append(
                StoredLabel(
                    transaction=self._transaction_from_payload(features_json),
                    suggested_category=suggested,
                    final_category=final,
                    accepted=bool(accepted),
                    overwritten=bool(overwritten),
                    similarity=similarity,
                    timestamp=self._parse_timestamp(ts),
                )
            )
        scored.sort(
            key=lambda item: (
                not item.overwritten,
                -item.similarity,
                -item.timestamp.timestamp(),
            )
        )
        return scored[:limit]

    # ------------------------------------------------------------------ #
    # Vector math helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _vector_from_blob(blob: bytes) -> list[float]:
        buffer = array("f")
        buffer.frombytes(blob)
        return buffer.tolist()

    @staticmethod
    def _dot_product(a: Sequence[float], b: Sequence[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    @staticmethod
    def _vector_norm(values: Sequence[float]) -> float:
        return sum(component * component for component in values) ** 0.5

    # ------------------------------------------------------------------ #
    # Payload helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _transaction_from_payload(payload: str) -> Transaction:
        data = json.loads(payload)
        return Transaction(
            description=data.get("description", ""),
            amount=data.get("amount", "0"),
            occurred_on=data.get("occurred_on", ""),
            account_name=data.get("account_name"),
            account_id=data.get("account_id"),
            counterparty=data.get("counterparty"),
            reference=data.get("reference"),
        )

    @staticmethod
    def _parse_timestamp(raw: str) -> datetime:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return datetime.utcnow()


__all__ = ["FeedbackStore", "StoredLabel", "DEFAULT_FEEDBACK_DB"]
