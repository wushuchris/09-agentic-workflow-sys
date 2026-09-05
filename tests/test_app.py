import os
import tempfile
from pathlib import Path

import gradio as gr

# Set a test-only database path before importing app because app creates its store at import.
IMPORT_DB = Path(tempfile.gettempdir()) / "agent9-gradio-import-test.db"
if IMPORT_DB.exists():
    IMPORT_DB.unlink()
os.environ["WORKFLOW_DB_PATH"] = str(IMPORT_DB)

import app  # noqa: E402

from src.persistence import SQLiteStateStore  # noqa: E402
from src.schemas import WorkflowStatus  # noqa: E402


def test_gradio_app_builds_as_blocks() -> None:
    assert isinstance(app.demo, gr.Blocks)


def test_run_and_refresh_callbacks_use_persisted_sqlite_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = SQLiteStateStore(tmp_path / "ui.db")
    monkeypatch.setattr(app, "STATE_STORE", store)

    bundle = app.run_request_ui(
        "UI-CALLBACK-NORMAL",
        "ACCESS",
        "Provision synthetic access for a fictional demo user.",
        "NORMAL",
        "LOW",
        125.0,
        "NONE",
    )
    run_id = bundle[1]

    assert run_id
    assert store.load(run_id).status is WorkflowStatus.COMPLETED
    assert "COMPLETED" in bundle[0]

    refreshed = app.refresh_run_ui(run_id)
    assert refreshed[1] == run_id
    assert refreshed[2] == bundle[2]
    assert refreshed[3] == bundle[3]


def test_high_risk_callback_pauses_then_approves_without_replaying_upstream(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = SQLiteStateStore(tmp_path / "human.db")
    monkeypatch.setattr(app, "STATE_STORE", store)

    paused_bundle = app.run_request_ui(
        "UI-CALLBACK-HIGH",
        "ACCESS",
        "Provision synthetic access for a fictional demo user.",
        "HIGH",
        "HIGH",
        1_500.0,
        "NONE",
    )
    run_id = paused_bundle[1]
    paused = store.load(run_id)

    assert paused.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert paused.node_runs["validate_request"].attempt == 1
    assert paused.node_runs["risk_gate"].attempt == 1
    assert len(paused.human_reviews) == 1

    completed_bundle = app.submit_human_decision_ui(run_id, "APPROVE")
    completed = store.load(run_id)

    assert completed.status is WorkflowStatus.COMPLETED
    assert completed.node_runs["validate_request"].attempt == 1
    assert completed.node_runs["risk_gate"].attempt == 1
    assert completed.node_runs["high_risk_finalize"].attempt == 1
    assert "COMPLETED" in completed_bundle[0]


def test_evaluation_callback_returns_ten_passing_cases() -> None:
    summary, metrics, cases = app.run_evaluation_ui()

    assert "10/10 passed" in summary
    assert ["total_cases", "10"] in metrics
    assert len(cases) == 10
    assert all(row[2] == "PASS" for row in cases)


def test_missing_run_id_returns_safe_ui_message(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(app, "STATE_STORE", SQLiteStateStore(tmp_path / "missing.db"))

    bundle = app.refresh_run_ui("does-not-exist")

    assert bundle[1] == "does-not-exist"
    assert "No persisted workflow run was found" in bundle[0]
    assert bundle[2:] == ([], [], [], {})
