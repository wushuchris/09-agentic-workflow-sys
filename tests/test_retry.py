import pytest

from src.executor import WorkflowExecutionError, execute_workflow
from src.registry import HandlerRegistry
from src.retry import RetryableHandlerError, should_retry
from src.schemas import (
    EventType,
    NodeDefinition,
    NodeStatus,
    NodeType,
    RetryPolicy,
    WorkflowDefinition,
    WorkflowStatus,
)


def make_workflow(node: NodeDefinition, *extra_nodes: NodeDefinition) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="retry-test-workflow",
        name="Retry Test Workflow",
        nodes=[node, *extra_nodes],
    )


def test_retry_controller_requires_explicit_signal_policy_and_remaining_attempts() -> None:
    policy = RetryPolicy(retryable=True, max_attempts=3)

    assert should_retry(
        policy,
        attempt=1,
        error=RetryableHandlerError("temporary"),
    ) is True
    assert should_retry(
        policy,
        attempt=3,
        error=RetryableHandlerError("temporary"),
    ) is False
    assert should_retry(
        policy,
        attempt=1,
        error=RuntimeError("permanent"),
    ) is False
    assert should_retry(
        RetryPolicy(),
        attempt=1,
        error=RetryableHandlerError("temporary"),
    ) is False


def test_retryable_failure_recovers_within_attempt_limit() -> None:
    registry = HandlerRegistry()
    calls = 0

    def flaky_handler(payload: dict) -> dict:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RetryableHandlerError("synthetic transient failure")
        return {"recovered": True}

    registry.register("flaky", flaky_handler)
    workflow = make_workflow(
        NodeDefinition(
            node_id="flaky-task",
            name="Flaky Task",
            node_type=NodeType.TASK,
            handler="flaky",
            retry_policy=RetryPolicy(retryable=True, max_attempts=3),
        )
    )

    run = execute_workflow(workflow, registry, run_id="retry-success")

    assert calls == 3
    assert run.status is WorkflowStatus.COMPLETED
    assert run.node_runs["flaky-task"].status is NodeStatus.COMPLETED
    assert run.node_runs["flaky-task"].attempt == 3
    assert run.node_runs["flaky-task"].error is None
    assert run.final_output == {"flaky-task": {"recovered": True}}

    assert [event.event_type for event in run.events] == [
        EventType.WORKFLOW_STARTED,
        EventType.NODE_STARTED,
        EventType.NODE_FAILED,
        EventType.RETRY_SCHEDULED,
        EventType.NODE_STARTED,
        EventType.NODE_FAILED,
        EventType.RETRY_SCHEDULED,
        EventType.NODE_STARTED,
        EventType.NODE_COMPLETED,
        EventType.WORKFLOW_COMPLETED,
    ]


def test_retry_exhaustion_fails_workflow_and_blocks_downstream_node() -> None:
    registry = HandlerRegistry()
    calls = 0
    downstream_calls = 0

    def always_transient(payload: dict) -> dict:
        nonlocal calls
        calls += 1
        raise RetryableHandlerError("service unavailable")

    def downstream(payload: dict) -> dict:
        nonlocal downstream_calls
        downstream_calls += 1
        return {"should_not_run": True}

    registry.register("always_transient", always_transient)
    registry.register("downstream", downstream)

    workflow = make_workflow(
        NodeDefinition(
            node_id="unstable",
            name="Unstable",
            node_type=NodeType.TASK,
            handler="always_transient",
            retry_policy=RetryPolicy(retryable=True, max_attempts=2),
        ),
        NodeDefinition(
            node_id="downstream",
            name="Downstream",
            node_type=NodeType.TASK,
            handler="downstream",
            depends_on=["unstable"],
        ),
    )

    with pytest.raises(WorkflowExecutionError, match="service unavailable") as exc_info:
        execute_workflow(workflow, registry, run_id="retry-exhausted")

    run = exc_info.value.run
    assert calls == 2
    assert downstream_calls == 0
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["unstable"].status is NodeStatus.FAILED
    assert run.node_runs["unstable"].attempt == 2
    assert run.node_runs["downstream"].status is NodeStatus.PENDING
    assert run.node_runs["downstream"].attempt == 0

    retry_events = [
        event for event in run.events if event.event_type is EventType.RETRY_SCHEDULED
    ]
    assert len(retry_events) == 1
    assert retry_events[0].details == {
        "attempt": 1,
        "next_attempt": 2,
        "max_attempts": 2,
    }
    assert run.events[-1].event_type is EventType.WORKFLOW_FAILED


def test_retryable_error_is_not_retried_when_policy_disables_retries() -> None:
    registry = HandlerRegistry()
    calls = 0

    def transient_handler(payload: dict) -> dict:
        nonlocal calls
        calls += 1
        raise RetryableHandlerError("temporary but policy forbids retry")

    registry.register("transient", transient_handler)
    workflow = make_workflow(
        NodeDefinition(
            node_id="task",
            name="Task",
            node_type=NodeType.TASK,
            handler="transient",
        )
    )

    with pytest.raises(WorkflowExecutionError) as exc_info:
        execute_workflow(workflow, registry)

    run = exc_info.value.run
    assert calls == 1
    assert run.node_runs["task"].attempt == 1
    assert EventType.RETRY_SCHEDULED not in [event.event_type for event in run.events]


def test_generic_exception_is_not_retried_even_when_policy_allows_retries() -> None:
    registry = HandlerRegistry()
    calls = 0

    def permanent_handler(payload: dict) -> dict:
        nonlocal calls
        calls += 1
        raise RuntimeError("permanent failure")

    registry.register("permanent", permanent_handler)
    workflow = make_workflow(
        NodeDefinition(
            node_id="task",
            name="Task",
            node_type=NodeType.TASK,
            handler="permanent",
            retry_policy=RetryPolicy(retryable=True, max_attempts=3),
        )
    )

    with pytest.raises(WorkflowExecutionError, match="permanent failure") as exc_info:
        execute_workflow(workflow, registry)

    run = exc_info.value.run
    assert calls == 1
    assert run.node_runs["task"].attempt == 1
    assert run.events[-2].event_type is EventType.NODE_FAILED
    assert run.events[-2].details["will_retry"] is False
    assert run.events[-1].event_type is EventType.WORKFLOW_FAILED


def test_invalid_handler_output_is_permanent_even_with_retry_policy() -> None:
    registry = HandlerRegistry()
    calls = 0

    def malformed_handler(payload: dict):
        nonlocal calls
        calls += 1
        return "not-a-dictionary"

    registry.register("malformed", malformed_handler)
    workflow = make_workflow(
        NodeDefinition(
            node_id="task",
            name="Task",
            node_type=NodeType.TASK,
            handler="malformed",
            retry_policy=RetryPolicy(retryable=True, max_attempts=3),
        )
    )

    with pytest.raises(WorkflowExecutionError, match="must be a dictionary") as exc_info:
        execute_workflow(workflow, registry)

    assert calls == 1
    assert exc_info.value.run.node_runs["task"].attempt == 1
    assert EventType.RETRY_SCHEDULED not in [
        event.event_type for event in exc_info.value.run.events
    ]
