import pytest

from src.executor import (
    WorkflowExecutionError,
    WorkflowHumanDecisionError,
    WorkflowResumeError,
    execute_workflow,
    resume_workflow,
    submit_human_decision,
)
from src.persistence import InMemoryStateStore
from src.registry import HandlerRegistry
from src.schemas import (
    EventType,
    HumanDecision,
    NodeDefinition,
    NodeStatus,
    NodeType,
    WorkflowDefinition,
    WorkflowStatus,
)


def make_human_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="human-workflow",
        name="Human Workflow",
        nodes=[
            NodeDefinition(
                node_id="prepare",
                name="Prepare",
                node_type=NodeType.TASK,
                handler="prepare_handler",
            ),
            NodeDefinition(
                node_id="review",
                name="Risk Review",
                node_type=NodeType.HUMAN_GATE,
                depends_on=["prepare"],
                config={"reason": "Risk threshold requires human approval."},
            ),
            NodeDefinition(
                node_id="finalize",
                name="Finalize",
                node_type=NodeType.TASK,
                handler="finalize_handler",
                depends_on=["review"],
            ),
        ],
    )


def build_registry(counters: dict[str, int]) -> HandlerRegistry:
    registry = HandlerRegistry()

    def prepare(payload: dict) -> dict:
        counters["prepare"] += 1
        return {"prepared": True}

    def finalize(payload: dict) -> dict:
        counters["finalize"] += 1
        assert payload["dependencies"]["review"]["decision"] == "APPROVE"
        return {"finalized": True}

    registry.register("prepare_handler", prepare)
    registry.register("finalize_handler", finalize)
    return registry


def test_human_gate_pauses_and_persists_review_without_running_downstream() -> None:
    counters = {"prepare": 0, "finalize": 0}
    registry = build_registry(counters)
    store = InMemoryStateStore()

    run = execute_workflow(
        make_human_workflow(),
        registry,
        run_id="human-pause",
        state_store=store,
    )

    assert run.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert run.node_runs["prepare"].status is NodeStatus.COMPLETED
    assert run.node_runs["review"].status is NodeStatus.WAITING_FOR_HUMAN
    assert run.node_runs["finalize"].status is NodeStatus.PENDING
    assert counters == {"prepare": 1, "finalize": 0}
    assert len(run.human_reviews) == 1
    assert run.human_reviews[0].reason == "Risk threshold requires human approval."
    assert run.human_reviews[0].decision is None

    loaded = store.load("human-pause")
    assert loaded == run
    assert EventType.HUMAN_REVIEW_REQUESTED in [
        event.event_type for event in run.events
    ]
    audit_text = repr([event.details for event in run.events])
    assert "Risk threshold requires human approval." not in audit_text


def test_approve_completes_gate_and_resumes_without_replaying_upstream() -> None:
    counters = {"prepare": 0, "finalize": 0}
    registry = build_registry(counters)
    store = InMemoryStateStore()
    workflow = make_human_workflow()

    paused = execute_workflow(
        workflow,
        registry,
        run_id="human-approve",
        state_store=store,
    )
    review_id = paused.human_reviews[0].review_id

    completed = submit_human_decision(
        workflow,
        registry,
        run_id="human-approve",
        review_id=review_id,
        decision=HumanDecision.APPROVE,
        state_store=store,
    )

    assert completed.status is WorkflowStatus.COMPLETED
    assert completed.node_runs["review"].status is NodeStatus.COMPLETED
    assert completed.node_runs["review"].output == {
        "decision": "APPROVE",
        "review_id": review_id,
    }
    assert completed.human_reviews[0].decision is HumanDecision.APPROVE
    assert completed.human_reviews[0].decided_at is not None
    assert counters == {"prepare": 1, "finalize": 1}
    assert completed.final_output == {"finalize": {"finalized": True}}

    event_types = [event.event_type for event in completed.events]
    assert EventType.HUMAN_APPROVED in event_types
    assert EventType.WORKFLOW_RESUMED in event_types
    assert event_types[-1] is EventType.WORKFLOW_COMPLETED


def test_reject_ends_business_process_as_rejected_without_downstream_execution() -> None:
    counters = {"prepare": 0, "finalize": 0}
    registry = build_registry(counters)
    store = InMemoryStateStore()
    workflow = make_human_workflow()

    paused = execute_workflow(
        workflow,
        registry,
        run_id="human-reject",
        state_store=store,
    )
    review_id = paused.human_reviews[0].review_id

    rejected = submit_human_decision(
        workflow,
        registry,
        run_id="human-reject",
        review_id=review_id,
        decision=HumanDecision.REJECT,
        state_store=store,
    )

    assert rejected.status is WorkflowStatus.REJECTED
    assert rejected.node_runs["review"].status is NodeStatus.COMPLETED
    assert rejected.node_runs["finalize"].status is NodeStatus.PENDING
    assert rejected.human_reviews[0].decision is HumanDecision.REJECT
    assert counters == {"prepare": 1, "finalize": 0}

    event_types = [event.event_type for event in rejected.events]
    assert EventType.HUMAN_REJECTED in event_types
    assert EventType.WORKFLOW_FAILED not in event_types
    assert EventType.WORKFLOW_COMPLETED not in event_types


def test_retry_reopens_same_gate_without_replaying_upstream_or_advancing() -> None:
    counters = {"prepare": 0, "finalize": 0}
    registry = build_registry(counters)
    store = InMemoryStateStore()
    workflow = make_human_workflow()

    paused = execute_workflow(
        workflow,
        registry,
        run_id="human-retry",
        state_store=store,
    )
    first_review_id = paused.human_reviews[0].review_id

    retried = submit_human_decision(
        workflow,
        registry,
        run_id="human-retry",
        review_id=first_review_id,
        decision=HumanDecision.RETRY,
        state_store=store,
    )

    assert retried.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert retried.node_runs["review"].status is NodeStatus.WAITING_FOR_HUMAN
    assert counters == {"prepare": 1, "finalize": 0}
    assert len(retried.human_reviews) == 2
    assert retried.human_reviews[0].decision is HumanDecision.RETRY
    assert retried.human_reviews[1].decision is None
    assert retried.human_reviews[1].review_id != first_review_id

    retry_request_event = retried.events[-1]
    assert retry_request_event.event_type is EventType.HUMAN_REVIEW_REQUESTED
    assert retry_request_event.details["retry_of"] == first_review_id


def test_stale_review_cannot_be_decided_twice_after_retry() -> None:
    counters = {"prepare": 0, "finalize": 0}
    registry = build_registry(counters)
    store = InMemoryStateStore()
    workflow = make_human_workflow()

    paused = execute_workflow(
        workflow,
        registry,
        run_id="human-stale",
        state_store=store,
    )
    review_id = paused.human_reviews[0].review_id
    submit_human_decision(
        workflow,
        registry,
        run_id="human-stale",
        review_id=review_id,
        decision=HumanDecision.RETRY,
        state_store=store,
    )

    with pytest.raises(WorkflowHumanDecisionError, match="already has decision"):
        submit_human_decision(
            workflow,
            registry,
            run_id="human-stale",
            review_id=review_id,
            decision=HumanDecision.APPROVE,
            state_store=store,
        )


def test_plain_resume_refuses_to_bypass_human_gate() -> None:
    counters = {"prepare": 0, "finalize": 0}
    registry = build_registry(counters)
    store = InMemoryStateStore()
    workflow = make_human_workflow()

    execute_workflow(
        workflow,
        registry,
        run_id="human-no-bypass",
        state_store=store,
    )

    with pytest.raises(WorkflowResumeError, match="use submit_human_decision"):
        resume_workflow(
            workflow,
            registry,
            run_id="human-no-bypass",
            state_store=store,
        )


def test_human_gate_requires_durable_state_store() -> None:
    counters = {"prepare": 0, "finalize": 0}
    registry = build_registry(counters)

    with pytest.raises(WorkflowExecutionError, match="requires a state_store") as exc_info:
        execute_workflow(
            make_human_workflow(),
            registry,
            run_id="human-no-store",
        )

    run = exc_info.value.run
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["prepare"].status is NodeStatus.COMPLETED
    assert run.node_runs["review"].status is NodeStatus.FAILED
    assert counters == {"prepare": 1, "finalize": 0}


def test_unknown_human_decision_is_rejected_without_changing_checkpoint() -> None:
    counters = {"prepare": 0, "finalize": 0}
    registry = build_registry(counters)
    store = InMemoryStateStore()
    workflow = make_human_workflow()

    paused = execute_workflow(
        workflow,
        registry,
        run_id="human-invalid-decision",
        state_store=store,
    )
    review_id = paused.human_reviews[0].review_id

    with pytest.raises(WorkflowHumanDecisionError, match="unknown human decision"):
        submit_human_decision(
            workflow,
            registry,
            run_id="human-invalid-decision",
            review_id=review_id,
            decision="BYPASS",
            state_store=store,
        )

    unchanged = store.load("human-invalid-decision")
    assert unchanged.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert unchanged.human_reviews[0].decision is None
