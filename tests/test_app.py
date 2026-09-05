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


def test_one_click_standard_household_explains_ready_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = SQLiteStateStore(tmp_path / "standard-story.db")
    monkeypatch.setattr(app, "STATE_STORE", store)

    bundle = app.run_story_ui("Straightforward household — package becomes ready")
    run = store.load(bundle[1])

    assert run.status is WorkflowStatus.COMPLETED
    assert "ready for advisor review" in bundle[6].lower()
    assert "What happened, step by step" in bundle[7]
    assert "AI Intake Organizer" in bundle[7]
    assert "Standard package ready" in bundle[7]


def test_one_click_retry_story_explains_automatic_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = SQLiteStateStore(tmp_path / "retry-story.db")
    monkeypatch.setattr(app, "STATE_STORE", store)

    bundle = app.run_story_ui("Temporary service problem — retries and recovers")
    run = store.load(bundle[1])

    assert run.status is WorkflowStatus.COMPLETED
    assert run.node_runs["create_onboarding_package"].attempt == 2
    assert "temporary onboarding-service problem" in bundle[6].lower()
    assert "Recovered on attempt 2" in bundle[7]


def test_run_and_refresh_callbacks_use_persisted_sqlite_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = SQLiteStateStore(tmp_path / "ui.db")
    monkeypatch.setattr(app, "STATE_STORE", store)

    bundle = app.run_request_ui(
        "HH-CALLBACK-STANDARD",
        "JOINT",
        "Synthetic household seeking a standard advisory relationship.",
        True,
        "VERIFIED",
        "STANDARD",
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
    assert refreshed[6] == bundle[6]
    assert refreshed[7] == bundle[7]


def test_exception_callback_pauses_then_approves_without_replaying_upstream(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = SQLiteStateStore(tmp_path / "human.db")
    monkeypatch.setattr(app, "STATE_STORE", store)

    paused_bundle = app.run_request_ui(
        "HH-CALLBACK-EXCEPTION",
        "TRUST",
        "Synthetic trust household requiring additional review.",
        True,
        "VERIFIED",
        "COMPLEX",
        "NONE",
    )
    run_id = paused_bundle[1]
    paused = store.load(run_id)

    assert paused.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert paused.node_runs["validate_intake"].attempt == 1
    assert paused.node_runs["review_gate"].attempt == 1
    assert len(paused.human_reviews) == 1
    assert "needs a person" in paused_bundle[6]
    assert "Waiting for a person" in paused_bundle[7]

    completed_bundle = app.submit_human_decision_ui(run_id, "APPROVE")
    completed = store.load(run_id)

    assert completed.status is WorkflowStatus.COMPLETED
    assert completed.node_runs["validate_intake"].attempt == 1
    assert completed.node_runs["review_gate"].attempt == 1
    assert completed.node_runs["reviewed_onboarding"].attempt == 1
    assert "COMPLETED" in completed_bundle[0]
    assert "ready after human review" in completed_bundle[6].lower()
    assert "Approved by a person" in completed_bundle[7]


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
    assert bundle[2:6] == ([], [], [], {})
    assert "Choose a fictional household story" in bundle[6]


def test_unknown_story_returns_safe_explanation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(app, "STATE_STORE", SQLiteStateStore(tmp_path / "unknown-story.db"))

    bundle = app.run_story_ui("invented story")

    assert "Choose one of the four onboarding stories" in bundle[0]
    assert bundle[1] == ""
