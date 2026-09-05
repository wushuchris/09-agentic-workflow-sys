from pathlib import Path

import pytest

from src.events import record_event
from src.executor import (
    WorkflowResumeError,
    execute_workflow,
    resume_workflow,
)
from src.persistence import (
    InMemoryStateStore,
    RunNotFoundError,
    SQLiteStateStore,
)
from src.registry import HandlerRegistry
from src.schemas import (
    EventType,
    NodeDefinition,
    NodeRun,
    NodeStatus,
    NodeType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
)


def make_two_step_workflow(*, version: str = "1.0") -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="persistence-workflow",
        name="Persistence Workflow",
        version=version,
        nodes=[
            NodeDefinition(
                node_id="first",
                name="First",
                node_type=NodeType.TASK,
                handler="first_handler",
            ),
            NodeDefinition(
                node_id="second",
                name="Second",
                node_type=NodeType.TASK,
                handler="second_handler",
                depends_on=["first"],
            ),
        ],
    )


def test_in_memory_store_returns_detached_snapshot() -> None:
    store = InMemoryStateStore()
    run = WorkflowRun(
        run_id="run-1",
        workflow_id="workflow-1",
        context={"value": 1},
    )

    store.save(run)
    run.context["value"] = 99

    loaded = store.load("run-1")

    assert loaded.context == {"value": 1}
    loaded.context["value"] = 7
    assert store.load("run-1").context == {"value": 1}


def test_in_memory_store_rejects_unknown_run() -> None:
    store = InMemoryStateStore()

    with pytest.raises(RunNotFoundError, match="was not found"):
        store.load("missing")


def test_sqlite_store_round_trips_nested_workflow_state(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "workflow.db")
    run = WorkflowRun(
        run_id="sqlite-run",
        workflow_id="workflow-1",
        workflow_version="2.1",
        status=WorkflowStatus.RUNNING,
        node_runs={
            "task": NodeRun(
                node_id="task",
                status=NodeStatus.COMPLETED,
                attempt=1,
                output={"ok": True},
            )
        },
        context={"request": "synthetic"},
    )
    record_event(run, EventType.WORKFLOW_STARTED)
    record_event(run, EventType.NODE_COMPLETED, node_id="task")

    store.save(run)
    loaded = store.load("sqlite-run")

    assert loaded == run
    assert loaded.events[0].event_type is EventType.WORKFLOW_STARTED
    assert loaded.node_runs["task"].output == {"ok": True}


def test_sqlite_store_upserts_latest_checkpoint(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "workflow.db")
    run = WorkflowRun(run_id="run-1", workflow_id="workflow-1")

    store.save(run)
    run.status = WorkflowStatus.COMPLETED
    run.final_output = {"done": True}
    store.save(run)

    loaded = store.load("run-1")

    assert loaded.status is WorkflowStatus.COMPLETED
    assert loaded.final_output == {"done": True}


def test_sqlite_store_rejects_unknown_run(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "workflow.db")

    with pytest.raises(RunNotFoundError, match="was not found"):
        store.load("missing")


class SimulatedProcessStop(BaseException):
    pass


class StopAfterFirstCompletionStore:
    """Save a safe checkpoint, then simulate process termination once."""

    def __init__(self) -> None:
        self.inner = InMemoryStateStore()
        self.triggered = False

    def save(self, run: WorkflowRun) -> None:
        self.inner.save(run)
        first = run.node_runs.get("first")
        second = run.node_runs.get("second")
        if (
            not self.triggered
            and first is not None
            and second is not None
            and first.status is NodeStatus.COMPLETED
            and second.status is NodeStatus.PENDING
        ):
            self.triggered = True
            raise SimulatedProcessStop()

    def load(self, run_id: str) -> WorkflowRun:
        return self.inner.load(run_id)


def test_safe_checkpoint_resume_skips_completed_node_after_process_stop() -> None:
    registry = HandlerRegistry()
    first_calls = 0
    second_calls = 0

    def first_handler(payload: dict) -> dict:
        nonlocal first_calls
        first_calls += 1
        return {"first": "done"}

    def second_handler(payload: dict) -> dict:
        nonlocal second_calls
        second_calls += 1
        assert payload["dependencies"] == {"first": {"first": "done"}}
        return {"second": "done"}

    registry.register("first_handler", first_handler)
    registry.register("second_handler", second_handler)
    workflow = make_two_step_workflow()
    store = StopAfterFirstCompletionStore()

    with pytest.raises(SimulatedProcessStop):
        execute_workflow(
            workflow,
            registry,
            run_id="resume-run",
            state_store=store,
        )

    checkpoint = store.load("resume-run")
    assert checkpoint.status is WorkflowStatus.RUNNING
    assert checkpoint.node_runs["first"].status is NodeStatus.COMPLETED
    assert checkpoint.node_runs["second"].status is NodeStatus.PENDING
    assert first_calls == 1
    assert second_calls == 0

    resumed = resume_workflow(
        workflow,
        registry,
        run_id="resume-run",
        state_store=store,
    )

    assert resumed.status is WorkflowStatus.COMPLETED
    assert resumed.node_runs["first"].attempt == 1
    assert resumed.node_runs["second"].attempt == 1
    assert first_calls == 1
    assert second_calls == 1
    assert EventType.WORKFLOW_RESUMED in [event.event_type for event in resumed.events]
    assert resumed.final_output == {"second": {"second": "done"}}


def test_completed_run_resume_is_idempotent() -> None:
    registry = HandlerRegistry()
    calls = 0

    def handler(payload: dict) -> dict:
        nonlocal calls
        calls += 1
        return {"ok": True}

    registry.register("first_handler", handler)
    registry.register("second_handler", handler)
    workflow = make_two_step_workflow()
    store = InMemoryStateStore()

    original = execute_workflow(
        workflow,
        registry,
        run_id="completed-run",
        state_store=store,
    )
    original_event_ids = [event.event_id for event in original.events]

    resumed = resume_workflow(
        workflow,
        registry,
        run_id="completed-run",
        state_store=store,
    )

    assert calls == 2
    assert resumed.status is WorkflowStatus.COMPLETED
    assert [event.event_id for event in resumed.events] == original_event_ids


def test_resume_rejects_changed_workflow_version() -> None:
    store = InMemoryStateStore()
    run = WorkflowRun(
        run_id="run-1",
        workflow_id="persistence-workflow",
        workflow_version="1.0",
        status=WorkflowStatus.RUNNING,
        node_runs={
            "first": NodeRun(node_id="first", status=NodeStatus.COMPLETED),
            "second": NodeRun(node_id="second", status=NodeStatus.PENDING),
        },
    )
    store.save(run)

    with pytest.raises(WorkflowResumeError, match="version"):
        resume_workflow(
            make_two_step_workflow(version="2.0"),
            HandlerRegistry(),
            run_id="run-1",
            state_store=store,
        )


def test_resume_rejects_ambiguous_in_flight_node() -> None:
    store = InMemoryStateStore()
    run = WorkflowRun(
        run_id="run-1",
        workflow_id="persistence-workflow",
        workflow_version="1.0",
        status=WorkflowStatus.RUNNING,
        node_runs={
            "first": NodeRun(node_id="first", status=NodeStatus.COMPLETED),
            "second": NodeRun(node_id="second", status=NodeStatus.RUNNING, attempt=1),
        },
    )
    store.save(run)

    with pytest.raises(WorkflowResumeError, match="ambiguous or non-resumable"):
        resume_workflow(
            make_two_step_workflow(),
            HandlerRegistry(),
            run_id="run-1",
            state_store=store,
        )
