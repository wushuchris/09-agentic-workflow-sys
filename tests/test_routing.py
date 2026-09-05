import pytest
from pydantic import ValidationError

from src.executor import WorkflowExecutionError, execute_workflow, submit_human_decision
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
from src.validator import WorkflowValidationError, validate_workflow


def make_risk_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="risk-routing-workflow",
        name="Risk Routing Workflow",
        nodes=[
            NodeDefinition(
                node_id="intake",
                name="Intake",
                node_type=NodeType.TASK,
                handler="intake_handler",
            ),
            NodeDefinition(
                node_id="risk_gate",
                name="Risk Gate",
                node_type=NodeType.DECISION,
                handler="risk_handler",
                depends_on=["intake"],
                routes={
                    "LOW_RISK": "low_finalize",
                    "HIGH_RISK": "human_review",
                },
            ),
            NodeDefinition(
                node_id="low_finalize",
                name="Low Risk Finalize",
                node_type=NodeType.TASK,
                handler="low_finalize_handler",
                depends_on=["risk_gate"],
            ),
            NodeDefinition(
                node_id="human_review",
                name="Human Review",
                node_type=NodeType.HUMAN_GATE,
                depends_on=["risk_gate"],
                config={"reason": "High-risk request requires approval."},
            ),
            NodeDefinition(
                node_id="high_finalize",
                name="High Risk Finalize",
                node_type=NodeType.TASK,
                handler="high_finalize_handler",
                depends_on=["human_review"],
            ),
        ],
    )


def build_registry(route: str, counters: dict[str, int]) -> HandlerRegistry:
    registry = HandlerRegistry()

    def intake(payload: dict) -> dict:
        counters["intake"] += 1
        return {"request_id": "REQ-001"}

    def risk(payload: dict) -> dict:
        counters["risk"] += 1
        assert payload["dependencies"] == {"intake": {"request_id": "REQ-001"}}
        return {"route": route}

    def low_finalize(payload: dict) -> dict:
        counters["low"] += 1
        assert payload["dependencies"]["risk_gate"]["route"] == "LOW_RISK"
        return {"outcome": "auto_finalized"}

    def high_finalize(payload: dict) -> dict:
        counters["high"] += 1
        assert payload["dependencies"]["human_review"]["decision"] == "APPROVE"
        return {"outcome": "human_approved"}

    registry.register("intake_handler", intake)
    registry.register("risk_handler", risk)
    registry.register("low_finalize_handler", low_finalize)
    registry.register("high_finalize_handler", high_finalize)
    return registry


def test_decision_node_requires_handler_and_multiple_routes() -> None:
    with pytest.raises(ValidationError, match="must declare a handler"):
        NodeDefinition(
            node_id="decision",
            name="Decision",
            node_type=NodeType.DECISION,
            routes={"A": "alpha", "B": "beta"},
        )

    with pytest.raises(ValidationError, match="at least two routes"):
        NodeDefinition(
            node_id="decision",
            name="Decision",
            node_type=NodeType.DECISION,
            handler="handler",
            routes={"A": "alpha"},
        )


def test_routes_are_rejected_on_non_decision_nodes() -> None:
    with pytest.raises(ValidationError, match="only allowed on DECISION"):
        NodeDefinition(
            node_id="task",
            name="Task",
            node_type=NodeType.TASK,
            handler="handler",
            routes={"A": "alpha", "B": "beta"},
        )


def test_validator_rejects_unknown_route_target() -> None:
    workflow = WorkflowDefinition(
        workflow_id="bad-route",
        name="Bad Route",
        nodes=[
            NodeDefinition(
                node_id="decision",
                name="Decision",
                node_type=NodeType.DECISION,
                handler="handler",
                routes={"A": "alpha", "B": "missing"},
            ),
            NodeDefinition(
                node_id="alpha",
                name="Alpha",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["decision"],
            ),
        ],
    )

    with pytest.raises(WorkflowValidationError, match="unknown node 'missing'"):
        validate_workflow(workflow)


def test_validator_requires_route_target_to_directly_depend_on_decision() -> None:
    workflow = WorkflowDefinition(
        workflow_id="bad-dependency",
        name="Bad Dependency",
        nodes=[
            NodeDefinition(
                node_id="decision",
                name="Decision",
                node_type=NodeType.DECISION,
                handler="handler",
                routes={"A": "alpha", "B": "beta"},
            ),
            NodeDefinition(
                node_id="alpha",
                name="Alpha",
                node_type=NodeType.TASK,
                handler="handler",
            ),
            NodeDefinition(
                node_id="beta",
                name="Beta",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["decision"],
            ),
        ],
    )

    with pytest.raises(WorkflowValidationError, match="must directly depend"):
        validate_workflow(workflow)


def test_validator_rejects_unrouted_direct_dependent() -> None:
    workflow = WorkflowDefinition(
        workflow_id="unrouted",
        name="Unrouted",
        nodes=[
            NodeDefinition(
                node_id="decision",
                name="Decision",
                node_type=NodeType.DECISION,
                handler="handler",
                routes={"A": "alpha", "B": "beta"},
            ),
            NodeDefinition(
                node_id="alpha",
                name="Alpha",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["decision"],
            ),
            NodeDefinition(
                node_id="beta",
                name="Beta",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["decision"],
            ),
            NodeDefinition(
                node_id="gamma",
                name="Gamma",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["decision"],
            ),
        ],
    )

    with pytest.raises(WorkflowValidationError, match="unrouted dependents: gamma"):
        validate_workflow(workflow)


def test_validator_rejects_branch_reconvergence_in_current_mvp() -> None:
    workflow = WorkflowDefinition(
        workflow_id="reconverge",
        name="Reconverge",
        nodes=[
            NodeDefinition(
                node_id="decision",
                name="Decision",
                node_type=NodeType.DECISION,
                handler="handler",
                routes={"A": "alpha", "B": "beta"},
            ),
            NodeDefinition(
                node_id="alpha",
                name="Alpha",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["decision"],
            ),
            NodeDefinition(
                node_id="beta",
                name="Beta",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["decision"],
            ),
            NodeDefinition(
                node_id="join",
                name="Join",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["alpha", "beta"],
            ),
        ],
    )

    with pytest.raises(WorkflowValidationError, match="reconvergence is not supported"):
        validate_workflow(workflow)


def test_low_risk_route_executes_only_selected_branch_and_skips_other_branch() -> None:
    counters = {"intake": 0, "risk": 0, "low": 0, "high": 0}
    run = execute_workflow(
        make_risk_workflow(),
        build_registry("LOW_RISK", counters),
        run_id="low-risk",
        state_store=InMemoryStateStore(),
    )

    assert run.status is WorkflowStatus.COMPLETED
    assert counters == {"intake": 1, "risk": 1, "low": 1, "high": 0}
    assert run.node_runs["risk_gate"].output == {"route": "LOW_RISK"}
    assert run.node_runs["low_finalize"].status is NodeStatus.COMPLETED
    assert run.node_runs["human_review"].status is NodeStatus.SKIPPED
    assert run.node_runs["high_finalize"].status is NodeStatus.SKIPPED
    assert run.final_output == {"low_finalize": {"outcome": "auto_finalized"}}

    routed = [event for event in run.events if event.event_type is EventType.DECISION_ROUTED]
    assert len(routed) == 1
    assert routed[0].details == {
        "route": "LOW_RISK",
        "selected_target": "low_finalize",
    }
    assert EventType.HUMAN_REVIEW_REQUESTED not in [
        event.event_type for event in run.events
    ]


def test_high_risk_route_pauses_for_human_then_resumes_without_replaying_decision() -> None:
    counters = {"intake": 0, "risk": 0, "low": 0, "high": 0}
    workflow = make_risk_workflow()
    registry = build_registry("HIGH_RISK", counters)
    store = InMemoryStateStore()

    paused = execute_workflow(
        workflow,
        registry,
        run_id="high-risk",
        state_store=store,
    )

    assert paused.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert counters == {"intake": 1, "risk": 1, "low": 0, "high": 0}
    assert paused.node_runs["low_finalize"].status is NodeStatus.SKIPPED
    assert paused.node_runs["human_review"].status is NodeStatus.WAITING_FOR_HUMAN
    review_id = paused.human_reviews[0].review_id

    completed = submit_human_decision(
        workflow,
        registry,
        run_id="high-risk",
        review_id=review_id,
        decision=HumanDecision.APPROVE,
        state_store=store,
    )

    assert completed.status is WorkflowStatus.COMPLETED
    assert counters == {"intake": 1, "risk": 1, "low": 0, "high": 1}
    assert completed.node_runs["risk_gate"].attempt == 1
    assert completed.node_runs["low_finalize"].status is NodeStatus.SKIPPED
    assert completed.node_runs["human_review"].status is NodeStatus.COMPLETED
    assert completed.node_runs["high_finalize"].status is NodeStatus.COMPLETED
    assert completed.final_output == {"high_finalize": {"outcome": "human_approved"}}


def test_unknown_decision_route_fails_safely_before_any_branch_executes() -> None:
    counters = {"intake": 0, "risk": 0, "low": 0, "high": 0}

    with pytest.raises(WorkflowExecutionError, match="unknown route 'UNAPPROVED'") as exc_info:
        execute_workflow(
            make_risk_workflow(),
            build_registry("UNAPPROVED", counters),
            run_id="bad-route-output",
            state_store=InMemoryStateStore(),
        )

    run = exc_info.value.run
    assert run.status is WorkflowStatus.FAILED
    assert counters == {"intake": 1, "risk": 1, "low": 0, "high": 0}
    assert run.node_runs["risk_gate"].status is NodeStatus.FAILED
    assert run.node_runs["low_finalize"].status is NodeStatus.PENDING
    assert run.node_runs["human_review"].status is NodeStatus.PENDING
    assert EventType.DECISION_ROUTED not in [event.event_type for event in run.events]


def test_decision_route_must_be_string() -> None:
    counters = {"intake": 0, "risk": 0, "low": 0, "high": 0}
    registry = build_registry("LOW_RISK", counters)

    def malformed_route(payload: dict) -> dict:
        counters["risk"] += 1
        return {"route": 42}

    registry = HandlerRegistry()

    def intake(payload: dict) -> dict:
        counters["intake"] += 1
        return {"request_id": "REQ-001"}

    registry.register("intake_handler", intake)
    registry.register("risk_handler", malformed_route)
    registry.register("low_finalize_handler", lambda payload: {"outcome": "low"})
    registry.register("high_finalize_handler", lambda payload: {"outcome": "high"})

    with pytest.raises(WorkflowExecutionError, match="non-blank string route"):
        execute_workflow(
            make_risk_workflow(),
            registry,
            state_store=InMemoryStateStore(),
        )
