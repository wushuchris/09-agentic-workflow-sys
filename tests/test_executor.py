import pytest

from src.executor import WorkflowExecutionError, execute_workflow
from src.registry import HandlerRegistry
from src.schemas import (
    EventType,
    NodeDefinition,
    NodeStatus,
    NodeType,
    WorkflowDefinition,
    WorkflowStatus,
)


def make_workflow(nodes: list[NodeDefinition]) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="executor-test-workflow",
        name="Executor Test Workflow",
        nodes=nodes,
    )


def test_executes_task_nodes_in_dependency_order_and_passes_outputs() -> None:
    registry = HandlerRegistry()
    execution_order: list[str] = []

    def intake(payload: dict) -> dict:
        execution_order.append(payload["node_id"])
        assert payload["context"] == {"customer": "Example Co"}
        return {"request_id": "REQ-001"}

    def validate(payload: dict) -> dict:
        execution_order.append(payload["node_id"])
        assert payload["dependencies"] == {
            "intake": {"request_id": "REQ-001"}
        }
        return {"validated": True}

    registry.register("intake_handler", intake)
    registry.register("validate_handler", validate)

    workflow = make_workflow(
        [
            NodeDefinition(
                node_id="intake",
                name="Intake",
                node_type=NodeType.TASK,
                handler="intake_handler",
            ),
            NodeDefinition(
                node_id="validate",
                name="Validate",
                node_type=NodeType.TASK,
                handler="validate_handler",
                depends_on=["intake"],
            ),
        ]
    )

    run = execute_workflow(
        workflow,
        registry,
        context={"customer": "Example Co"},
        run_id="run-001",
    )

    assert execution_order == ["intake", "validate"]
    assert run.run_id == "run-001"
    assert run.status is WorkflowStatus.COMPLETED
    assert run.node_runs["intake"].status is NodeStatus.COMPLETED
    assert run.node_runs["validate"].status is NodeStatus.COMPLETED
    assert run.node_runs["intake"].attempt == 1
    assert run.node_runs["validate"].attempt == 1
    assert run.final_output == {"validate": {"validated": True}}


def test_independent_nodes_execute_in_deterministic_topological_order() -> None:
    registry = HandlerRegistry()
    execution_order: list[str] = []

    def handler(payload: dict) -> dict:
        execution_order.append(payload["node_id"])
        return {"node": payload["node_id"]}

    registry.register("handler", handler)

    workflow = make_workflow(
        [
            NodeDefinition(
                node_id="beta",
                name="Beta",
                node_type=NodeType.TASK,
                handler="handler",
            ),
            NodeDefinition(
                node_id="alpha",
                name="Alpha",
                node_type=NodeType.TASK,
                handler="handler",
            ),
        ]
    )

    run = execute_workflow(workflow, registry)

    assert execution_order == ["alpha", "beta"]
    assert run.final_output == {
        "alpha": {"node": "alpha"},
        "beta": {"node": "beta"},
    }


def test_unknown_handler_fails_node_and_preserves_failed_run() -> None:
    registry = HandlerRegistry()
    workflow = make_workflow(
        [
            NodeDefinition(
                node_id="task",
                name="Task",
                node_type=NodeType.TASK,
                handler="not_registered",
            )
        ]
    )

    with pytest.raises(WorkflowExecutionError, match="not registered") as exc_info:
        execute_workflow(workflow, registry, run_id="run-failed")

    run = exc_info.value.run
    assert run.run_id == "run-failed"
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["task"].status is NodeStatus.FAILED
    assert run.node_runs["task"].attempt == 1
    assert "not registered" in (run.node_runs["task"].error or "")


def test_handler_exception_stops_workflow_and_leaves_downstream_pending() -> None:
    registry = HandlerRegistry()

    def fail_handler(payload: dict) -> dict:
        raise RuntimeError("synthetic transient-looking failure")

    def downstream_handler(payload: dict) -> dict:
        return {"should_not_run": True}

    registry.register("fail", fail_handler)
    registry.register("downstream", downstream_handler)

    workflow = make_workflow(
        [
            NodeDefinition(
                node_id="first",
                name="First",
                node_type=NodeType.TASK,
                handler="fail",
            ),
            NodeDefinition(
                node_id="second",
                name="Second",
                node_type=NodeType.TASK,
                handler="downstream",
                depends_on=["first"],
            ),
        ]
    )

    with pytest.raises(WorkflowExecutionError, match="synthetic transient-looking failure") as exc_info:
        execute_workflow(workflow, registry)

    run = exc_info.value.run
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["first"].status is NodeStatus.FAILED
    assert run.node_runs["second"].status is NodeStatus.PENDING
    assert run.node_runs["second"].attempt == 0


def test_handler_output_must_be_dictionary() -> None:
    registry = HandlerRegistry()

    def bad_output_handler(payload: dict):
        return "not-a-dict"

    registry.register("bad_output", bad_output_handler)
    workflow = make_workflow(
        [
            NodeDefinition(
                node_id="task",
                name="Task",
                node_type=NodeType.TASK,
                handler="bad_output",
            )
        ]
    )

    with pytest.raises(WorkflowExecutionError, match="must be a dictionary") as exc_info:
        execute_workflow(workflow, registry)

    assert exc_info.value.run.node_runs["task"].status is NodeStatus.FAILED


def test_basic_executor_rejects_unsupported_node_type() -> None:
    registry = HandlerRegistry()
    workflow = make_workflow(
        [
            NodeDefinition(
                node_id="decision",
                name="Decision",
                node_type=NodeType.DECISION,
            )
        ]
    )

    with pytest.raises(WorkflowExecutionError, match="unsupported node type") as exc_info:
        execute_workflow(workflow, registry)

    run = exc_info.value.run
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["decision"].status is NodeStatus.FAILED
    assert run.node_runs["decision"].attempt == 0


def test_task_without_handler_is_rejected_before_execution() -> None:
    registry = HandlerRegistry()
    workflow = make_workflow(
        [
            NodeDefinition(
                node_id="task",
                name="Task",
                node_type=NodeType.TASK,
            )
        ]
    )

    with pytest.raises(WorkflowExecutionError, match="must declare a handler") as exc_info:
        execute_workflow(workflow, registry)

    run = exc_info.value.run
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["task"].status is NodeStatus.FAILED
    assert run.node_runs["task"].attempt == 0


def test_successful_execution_emits_complete_ordered_audit_history() -> None:
    registry = HandlerRegistry()

    def handler(payload: dict) -> dict:
        return {"ok": True}

    registry.register("handler", handler)
    workflow = make_workflow(
        [
            NodeDefinition(
                node_id="first",
                name="First",
                node_type=NodeType.TASK,
                handler="handler",
            ),
            NodeDefinition(
                node_id="second",
                name="Second",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["first"],
            ),
        ]
    )

    run = execute_workflow(workflow, registry, run_id="audit-success")

    assert [event.event_type for event in run.events] == [
        EventType.WORKFLOW_STARTED,
        EventType.NODE_STARTED,
        EventType.NODE_COMPLETED,
        EventType.NODE_STARTED,
        EventType.NODE_COMPLETED,
        EventType.WORKFLOW_COMPLETED,
    ]
    assert [event.node_id for event in run.events] == [
        None,
        "first",
        "first",
        "second",
        "second",
        None,
    ]
    assert all(event.run_id == "audit-success" for event in run.events)


def test_failed_execution_emits_failure_events_without_sensitive_payloads() -> None:
    registry = HandlerRegistry()

    def fail_handler(payload: dict) -> dict:
        raise RuntimeError("synthetic failure")

    registry.register("fail", fail_handler)
    workflow = make_workflow(
        [
            NodeDefinition(
                node_id="task",
                name="Task",
                node_type=NodeType.TASK,
                handler="fail",
            )
        ]
    )

    with pytest.raises(WorkflowExecutionError) as exc_info:
        execute_workflow(
            workflow,
            registry,
            context={"private_note": "do not copy into audit log"},
            run_id="audit-failure",
        )

    run = exc_info.value.run
    assert [event.event_type for event in run.events] == [
        EventType.WORKFLOW_STARTED,
        EventType.NODE_STARTED,
        EventType.NODE_FAILED,
        EventType.WORKFLOW_FAILED,
    ]
    audit_text = repr([event.details for event in run.events])
    assert "private_note" not in audit_text
    assert "do not copy into audit log" not in audit_text
