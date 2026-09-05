import pytest

from src.demo_workflow import (
    build_service_request_registry,
    build_service_request_workflow,
    example_request,
)
from src.executor import WorkflowExecutionError, execute_workflow, submit_human_decision
from src.persistence import InMemoryStateStore
from src.schemas import EventType, HumanDecision, NodeStatus, WorkflowStatus
from src.validator import validate_workflow


def test_demo_workflow_is_structurally_valid() -> None:
    workflow = build_service_request_workflow()

    assert validate_workflow(workflow) is None
    assert workflow.workflow_id == "controlled-service-request"
    assert len(workflow.nodes) == 9


def test_normal_low_risk_request_completes_automatically() -> None:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()
    store = InMemoryStateStore()

    run = execute_workflow(
        workflow,
        registry,
        context=example_request(request_id="REQ-NORMAL"),
        run_id="demo-normal",
        state_store=store,
    )

    assert run.status is WorkflowStatus.COMPLETED
    assert run.node_runs["perform_automated_task"].attempt == 1
    assert run.node_runs["risk_gate"].output["route"] == "LOW_RISK"
    assert run.node_runs["low_risk_finalize"].status is NodeStatus.COMPLETED
    assert run.node_runs["human_review"].status is NodeStatus.SKIPPED
    assert run.node_runs["high_risk_finalize"].status is NodeStatus.SKIPPED
    assert run.final_output == {
        "low_risk_finalize": {
            "outcome": "AUTO_FINALIZED",
            "approved_by": "WORKFLOW_POLICY",
        }
    }


def test_transient_failure_retries_once_then_recovers() -> None:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()

    run = execute_workflow(
        workflow,
        registry,
        context=example_request(
            request_id="REQ-TRANSIENT",
            simulation_mode="TRANSIENT_ONCE",
        ),
        run_id="demo-transient",
        state_store=InMemoryStateStore(),
    )

    automated = run.node_runs["perform_automated_task"]
    assert run.status is WorkflowStatus.COMPLETED
    assert automated.status is NodeStatus.COMPLETED
    assert automated.attempt == 2
    assert automated.output["service_attempt"] == 2
    assert EventType.RETRY_SCHEDULED in [event.event_type for event in run.events]


def test_invalid_request_fails_before_classification_or_action() -> None:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()
    request = example_request(request_id="REQ-INVALID")
    request["description"] = "   "

    with pytest.raises(WorkflowExecutionError, match="description must be a non-blank string") as exc_info:
        execute_workflow(
            workflow,
            registry,
            context=request,
            run_id="demo-invalid",
            state_store=InMemoryStateStore(),
        )

    run = exc_info.value.run
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["validate_request"].status is NodeStatus.FAILED
    assert run.node_runs["classify_request"].status is NodeStatus.PENDING
    assert run.node_runs["perform_automated_task"].attempt == 0


def test_high_risk_request_pauses_for_human_then_approval_completes() -> None:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()
    store = InMemoryStateStore()

    paused = execute_workflow(
        workflow,
        registry,
        context=example_request(
            request_id="REQ-HIGH",
            risk_level="HIGH",
            estimated_cost=1_500.0,
            priority="HIGH",
        ),
        run_id="demo-high",
        state_store=store,
    )

    assert paused.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert paused.node_runs["risk_gate"].output["route"] == "HIGH_RISK"
    assert paused.node_runs["low_risk_finalize"].status is NodeStatus.SKIPPED
    assert paused.node_runs["human_review"].status is NodeStatus.WAITING_FOR_HUMAN
    assert paused.node_runs["high_risk_finalize"].status is NodeStatus.PENDING
    assert len(paused.human_reviews) == 1

    review_id = paused.human_reviews[0].review_id
    completed = submit_human_decision(
        workflow,
        registry,
        run_id="demo-high",
        review_id=review_id,
        decision=HumanDecision.APPROVE,
        state_store=store,
    )

    assert completed.status is WorkflowStatus.COMPLETED
    assert completed.node_runs["human_review"].status is NodeStatus.COMPLETED
    assert completed.node_runs["high_risk_finalize"].status is NodeStatus.COMPLETED
    assert completed.node_runs["validate_request"].attempt == 1
    assert completed.node_runs["risk_gate"].attempt == 1
    assert completed.final_output == {
        "high_risk_finalize": {
            "outcome": "HUMAN_APPROVED_FINALIZATION",
            "approved_by": "HUMAN_REVIEW",
        }
    }


def test_high_risk_human_rejection_ends_as_rejected_not_failed() -> None:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()
    store = InMemoryStateStore()

    paused = execute_workflow(
        workflow,
        registry,
        context=example_request(
            request_id="REQ-REJECT",
            risk_level="HIGH",
            estimated_cost=1_250.0,
        ),
        run_id="demo-reject",
        state_store=store,
    )

    rejected = submit_human_decision(
        workflow,
        registry,
        run_id="demo-reject",
        review_id=paused.human_reviews[0].review_id,
        decision=HumanDecision.REJECT,
        state_store=store,
    )

    assert rejected.status is WorkflowStatus.REJECTED
    assert rejected.node_runs["human_review"].status is NodeStatus.COMPLETED
    assert rejected.node_runs["high_risk_finalize"].status is NodeStatus.PENDING
    assert EventType.HUMAN_REJECTED in [event.event_type for event in rejected.events]
    assert EventType.WORKFLOW_FAILED not in [event.event_type for event in rejected.events]


def test_permanent_failure_is_not_retried_even_though_node_allows_retries() -> None:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()

    with pytest.raises(WorkflowExecutionError, match="synthetic permanent service failure") as exc_info:
        execute_workflow(
            workflow,
            registry,
            context=example_request(
                request_id="REQ-PERMANENT",
                simulation_mode="PERMANENT",
            ),
            run_id="demo-permanent",
            state_store=InMemoryStateStore(),
        )

    run = exc_info.value.run
    automated = run.node_runs["perform_automated_task"]
    assert run.status is WorkflowStatus.FAILED
    assert automated.status is NodeStatus.FAILED
    assert automated.attempt == 1
    assert EventType.RETRY_SCHEDULED not in [event.event_type for event in run.events]
    assert run.node_runs["verify_result"].status is NodeStatus.PENDING


def test_audit_log_does_not_copy_request_description_or_supporting_info() -> None:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()
    request = example_request(request_id="REQ-PRIVACY")
    request["description"] = "Synthetic but intentionally private-looking demo text."
    request["supporting_info"] = {"note": "Do not duplicate me into audit events."}

    run = execute_workflow(
        workflow,
        registry,
        context=request,
        run_id="demo-privacy",
        state_store=InMemoryStateStore(),
    )

    audit_text = repr([event.details for event in run.events])
    assert "Synthetic but intentionally private-looking demo text." not in audit_text
    assert "Do not duplicate me into audit events." not in audit_text
