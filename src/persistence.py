"""Persistence adapters for durable workflow checkpoints.

The workflow runtime depends on a small StateStore contract rather than a specific
database. InMemoryStateStore keeps tests deterministic, while SQLiteStateStore
provides a zero-infrastructure durable store for the portfolio demo.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from src.schemas import WorkflowRun


class StateStoreError(RuntimeError):
    """Base error for workflow state-store operations."""


class RunNotFoundError(StateStoreError):
    """Raised when a requested workflow run does not exist."""


class StateStore(Protocol):
    """Minimal persistence contract used by the workflow runtime."""

    def save(self, run: WorkflowRun) -> None:
        """Persist the latest complete checkpoint for a workflow run."""

    def load(self, run_id: str) -> WorkflowRun:
        """Load a detached workflow run snapshot by identifier."""


class InMemoryStateStore:
    """Deterministic state store for tests and local execution."""

    def __init__(self) -> None:
        self._runs: dict[str, str] = {}

    def save(self, run: WorkflowRun) -> None:
        self._runs[run.run_id] = run.model_dump_json()

    def load(self, run_id: str) -> WorkflowRun:
        try:
            payload = self._runs[run_id]
        except KeyError as exc:
            raise RunNotFoundError(f"workflow run '{run_id}' was not found") from exc
        return WorkflowRun.model_validate_json(payload)


class SQLiteStateStore:
    """SQLite-backed state store using one JSON snapshot per workflow run."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )

    def save(self, run: WorkflowRun) -> None:
        payload = run.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_runs (run_id, payload)
                VALUES (?, ?)
                ON CONFLICT(run_id) DO UPDATE SET payload = excluded.payload
                """,
                (run.run_id, payload),
            )

    def load(self, run_id: str) -> WorkflowRun:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()

        if row is None:
            raise RunNotFoundError(f"workflow run '{run_id}' was not found")

        return WorkflowRun.model_validate_json(row[0])
