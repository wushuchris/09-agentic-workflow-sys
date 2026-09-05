"""Tests for the workflow system's structured domain contracts."""

from datetime import timezone

import pytest
from pydantic import ValidationError

from src.schemas import (
    HumanDecision,
    HumanReviewRequest,
    NodeDefinition,
    NodeRun,
    NodeStatus,
    NodeType,
    RetryPolicy,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStatus,
)


def test_valid_workflow_definition_is_accepted() -> None:
    workflow = WorkflowDefinition(
        workflow_id="service-request-v1",
        name="Service Request Workflow",
        nodes=[
            NodeDefinition(
                node_id="validate",
                name="Validate Request",
                node_type=NodeType.TASK,
                handler="validate_request",
            ),
            NodeDefinition(
                node_id="review",
                name="Human Review",
                node_type=NodeType.HUMAN_GATE,
                depends_on=["validate"],
            ),
        ],
    )

    assert workflow.workflow_id == "service-request-v1"
    assert workflow.nodes[0].node_type is NodeType.TASK
    assert workflow.nodes[1].depends_on == ["validate"]


def test_retryable_policy_allows_bounded_multiple_attempts() -> None:
    policy = RetryPolicy(retryable=True, max_attempts=3)

    assert policy.retryable is True
    assert policy.max_attempts == 3


@pytest.mark.parametrize("max_attempts", [0, 11])
def test_retry_attempts_outside_bounds_are_rejected(max_attempts: int) -> None:
    with pytest.raises(ValidationError):
        RetryPolicy(retryable=True, max_attempts=max_attempts)


def test_non_retryable_policy_cannot_request_multiple_attempts() -> None:
    with pytest.raises(ValidationError, match="non-retryable nodes"):
        RetryPolicy(retryable=False, max_attempts=2)


def test_unknown_node_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NodeDefinition(
            node_id="mystery",
            name="Mystery Node",
            node_type="ARBITRARY_CODE",
        )


def test_unknown_workflow_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowRun(
            run_id="run-1",
            workflow_id="workflow-1",
            status="MODEL_INVENTED_STATE",
        )


def test_empty_workflow_definition_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition(
            workflow_id="workflow-1",
            name="Empty Workflow",
            nodes=[],
        )


def test_blank_identifier_is_rejected_after_whitespace_stripping() -> None:
    with pytest.raises(ValidationError):
        NodeDefinition(
            node_id="   ",
            name="Invalid Node",
            node_type=NodeType.TASK,
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RetryPolicy(
            retryable=True,
            max_attempts=2,
            unlimited_retries=True,
        )


def test_negative_node_attempt_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NodeRun(node_id="validate", attempt=-1)


def test_human_decision_is_bounded_to_known_actions() -> None:
    review = HumanReviewRequest(
        review_id="review-1",
        run_id="run-1",
        node_id="human-review",
        reason="Risk threshold exceeded.",
        decision=HumanDecision.APPROVE,
    )

    assert review.decision is HumanDecision.APPROVE

    with pytest.raises(ValidationError):
        HumanReviewRequest(
            review_id="review-2",
            run_id="run-1",
            node_id="human-review",
            reason="Risk threshold exceeded.",
            decision="BYPASS",
        )


def test_runtime_defaults_are_safe_and_timezone_aware() -> None:
    run = WorkflowRun(run_id="run-1", workflow_id="workflow-1")
    event = WorkflowEvent(
        event_id="event-1",
        run_id="run-1",
        event_type="WORKFLOW_STARTED",
    )

    assert run.status is WorkflowStatus.PENDING
    assert run.node_runs == {}
    assert run.context == {}
    assert run.created_at.tzinfo == timezone.utc
    assert event.timestamp.tzinfo == timezone.utc


def test_node_status_accepts_only_defined_runtime_states() -> None:
    node_run = NodeRun(node_id="validate", status=NodeStatus.READY)
    assert node_run.status is NodeStatus.READY

    with pytest.raises(ValidationError):
        NodeRun(node_id="validate", status="MAGICALLY_DONE")
