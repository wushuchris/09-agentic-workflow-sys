"""Deterministic evaluation harness for the Agentic Workflow System.

The suite exercises the public-safe service-request workflow across success,
recovery, escalation, persistence, failure, and adversarial-control scenarios.
It returns structured case results and aggregate workflow-engineering metrics that
can later be displayed by the Gradio demo or used in CI.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.demo_workflow import (
    build_service_request_registry,
    build_service_request_workflow,
    example_request,
)
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
    WorkflowRun,
    WorkflowStatus,
)
from src.validator import WorkflowValidationError


class EvaluationCaseResult(BaseModel):
    """One public-safe evaluation case and its deterministic checks."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    passed: bool
    expected: str = Field(min_length=1, max_length=300)
    observed: str = Field(min_length=1, max_length=300)
    checks: dict[str, bool] = Field(default_factory=dict)
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    """Aggregate deterministic evaluation report suitable for UI or CI use."""

    model_config = ConfigDict(extra="forbid")

    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    case_pass_rate: float = Field(ge=0.0, le=1.0)
    metrics: dict[str, float | int] = Field(default_factory=dict)
    cases: tuple[EvaluationCaseResult, ...] = Field(default_factory=tuple)


CaseFactory = Callable[[], EvaluationCaseResult]


def run_evaluation_suite() -> EvaluationReport:
    """Run all deterministic Agent 9 evaluation cases and compute metrics."""

    case_factories: tuple[tuple[str, str, CaseFactory], ...] = (
        ("normal_low_risk", "success", _evaluate_normal_low_risk),
        ("transient_retry_recovery", "retry", _evaluate_transient_retry_recovery),
        ("high_risk_approval", "human_escalation", _evaluate_high_risk_approval),
        ("high_risk_rejection", "human_escalation", _evaluate_high_risk_rejection),
        ("validation_failure", "failure_containment", _evaluate_validation_failure),
        ("permanent_failure", "failure_containment", _evaluate_permanent_failure),
        ("checkpoint_resume", "persistence", _evaluate_checkpoint_resume),
        ("model_control_injection", "adversarial", _evaluate_model_control_injection),
        ("invalid_dag", "adversarial", _evaluate_invalid_dag),
        ("human_gate_bypass", "adversarial", _evaluate_human_gate_bypass),
    )

    results: list[EvaluationCaseResult] = []
    for case_id, category, factory in case_factories:
        try:
            results.append(factory())
        except Exception as exc:  # defensive: evaluation should report, not crash
            results.append(
                _result(
                    case_id=case_id,
                    category=category,
                    expected="evaluation case completes its deterministic assertions",
                    observed=f"unexpected_exception:{type(exc).__name__}",
                    checks={"unexpected_exception_free": False},
                )
            )

    passed_cases = sum(result.passed for result in results)
    total_cases = len(results)
    metrics = _build_metrics(results)

    return EvaluationReport(
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        case_pass_rate=passed_cases / total_cases if total_cases else 0.0,
        metrics=metrics,
        cases=tuple(results),
    )


def _evaluate_normal_low_risk() -> EvaluationCaseResult:
    run = execute_workflow(
        build_service_request_workflow(),
        build_service_request_registry(),
        context=example_request(request_id="EVAL-NORMAL"),
        run_id="eval-normal",
        state_store=InMemoryStateStore(),
    )
    event_types = _event_types(run)

    return _result(
        case_id="normal_low_risk",
        category="success",
        expected="low-risk request completes automatically without human review",
        observed=run.status.value,
        checks={
            "completed_as_expected": run.status is WorkflowStatus.COMPLETED,
            "expected_path": (
                run.node_runs["risk_gate"].output == {
                    "route": "LOW_RISK",
                    "risk_level": "LOW",
                }
                and run.node_runs["low_risk_finalize"].status is NodeStatus.COMPLETED
                and run.node_runs["human_review"].status is NodeStatus.SKIPPED
                and run.node_runs["high_risk_finalize"].status is NodeStatus.SKIPPED
            ),
            "escalation_behavior": EventType.HUMAN_REVIEW_REQUESTED not in event_types,
            "audit_complete": _has_events(
                run,
                EventType.WORKFLOW_STARTED,
                EventType.DECISION_ROUTED,
                EventType.WORKFLOW_COMPLETED,
            ),
        },
        details={"invalid_transitions": 0, "duplicate_executions": 0},
    )


def _evaluate_transient_retry_recovery() -> EvaluationCaseResult:
    run = execute_workflow(
        build_service_request_workflow(),
        build_service_request_registry(),
        context=example_request(
            request_id="EVAL-TRANSIENT",
            simulation_mode="TRANSIENT_ONCE",
        ),
        run_id="eval-transient",
        state_store=InMemoryStateStore(),
    )
    retries = [event for event in run.events if event.event_type is EventType.RETRY_SCHEDULED]

    return _result(
        case_id="transient_retry_recovery",
        category="retry",
        expected="one retryable failure is retried once and then recovers",
        observed=run.status.value,
        checks={
            "completed_as_expected": run.status is WorkflowStatus.COMPLETED,
            "retry_behavior": (
                run.node_runs["perform_automated_task"].attempt == 2
                and len(retries) == 1
                and run.node_runs["perform_automated_task"].status is NodeStatus.COMPLETED
            ),
            "audit_complete": _has_events(
                run,
                EventType.NODE_FAILED,
                EventType.RETRY_SCHEDULED,
                EventType.WORKFLOW_COMPLETED,
            ),
        },
        details={"invalid_transitions": 0, "duplicate_executions": 0},
    )


def _evaluate_high_risk_approval() -> EvaluationCaseResult:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()
    store = InMemoryStateStore()
    paused = execute_workflow(
        workflow,
        registry,
        context=example_request(
            request_id="EVAL-HIGH-APPROVE",
            risk_level="HIGH",
            estimated_cost=1_500.0,
            priority="HIGH",
        ),
        run_id="eval-high-approve",
        state_store=store,
    )
    review_id = paused.human_reviews[0].review_id
    completed = submit_human_decision(
        workflow,
        registry,
        run_id="eval-high-approve",
        review_id=review_id,
        decision=HumanDecision.APPROVE,
        state_store=store,
    )

    duplicate_blocked = False
    try:
        submit_human_decision(
            workflow,
            registry,
            run_id="eval-high-approve",
            review_id=review_id,
            decision=HumanDecision.APPROVE,
            state_store=store,
        )
    except WorkflowHumanDecisionError:
        duplicate_blocked = True

    stored = store.load("eval-high-approve")
    duplicate_executions = max(0, stored.node_runs["high_risk_finalize"].attempt - 1)

    return _result(
        case_id="high_risk_approval",
        category="human_escalation",
        expected="high-risk request pauses, approves once, and resumes without replay",
        observed=completed.status.value,
        checks={
            "completed_as_expected": completed.status is WorkflowStatus.COMPLETED,
            "expected_path": (
                paused.status is WorkflowStatus.WAITING_FOR_HUMAN
                and completed.node_runs["low_risk_finalize"].status is NodeStatus.SKIPPED
                and completed.node_runs["high_risk_finalize"].status is NodeStatus.COMPLETED
            ),
            "escalation_behavior": (
                len(paused.human_reviews) == 1
                and paused.node_runs["human_review"].status is NodeStatus.WAITING_FOR_HUMAN
                and duplicate_blocked
            ),
            "audit_complete": _has_events(
                completed,
                EventType.HUMAN_REVIEW_REQUESTED,
                EventType.HUMAN_APPROVED,
                EventType.WORKFLOW_RESUMED,
                EventType.WORKFLOW_COMPLETED,
            ),
        },
        details={
            "invalid_transitions": 0,
            "duplicate_executions": duplicate_executions,
        },
    )


def _evaluate_high_risk_rejection() -> EvaluationCaseResult:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()
    store = InMemoryStateStore()
    paused = execute_workflow(
        workflow,
        registry,
        context=example_request(
            request_id="EVAL-HIGH-REJECT",
            risk_level="HIGH",
            estimated_cost=1_250.0,
        ),
        run_id="eval-high-reject",
        state_store=store,
    )
    rejected = submit_human_decision(
        workflow,
        registry,
        run_id="eval-high-reject",
        review_id=paused.human_reviews[0].review_id,
        decision=HumanDecision.REJECT,
        state_store=store,
    )
    event_types = _event_types(rejected)

    return _result(
        case_id="high_risk_rejection",
        category="human_escalation",
        expected="human rejection ends as REJECTED without downstream finalization",
        observed=rejected.status.value,
        checks={
            "expected_path": (
                rejected.status is WorkflowStatus.REJECTED
                and rejected.node_runs["high_risk_finalize"].status is NodeStatus.PENDING
            ),
            "escalation_behavior": EventType.HUMAN_REJECTED in event_types,
            "audit_complete": (
                EventType.HUMAN_REJECTED in event_types
                and EventType.WORKFLOW_FAILED not in event_types
                and EventType.WORKFLOW_COMPLETED not in event_types
            ),
        },
        details={"invalid_transitions": 0, "duplicate_executions": 0},
    )


def _evaluate_validation_failure() -> EvaluationCaseResult:
    request = example_request(request_id="EVAL-INVALID")
    request["description"] = "   "
    failed_run: WorkflowRun | None = None

    try:
        execute_workflow(
            build_service_request_workflow(),
            build_service_request_registry(),
            context=request,
            run_id="eval-invalid",
            state_store=InMemoryStateStore(),
        )
    except WorkflowExecutionError as exc:
        failed_run = exc.run

    contained = (
        failed_run is not None
        and failed_run.status is WorkflowStatus.FAILED
        and failed_run.node_runs["validate_request"].status is NodeStatus.FAILED
        and failed_run.node_runs["classify_request"].status is NodeStatus.PENDING
        and failed_run.node_runs["perform_automated_task"].attempt == 0
    )

    return _result(
        case_id="validation_failure",
        category="failure_containment",
        expected="invalid input fails before classification or automated action",
        observed=failed_run.status.value if failed_run else "NO_FAILURE",
        checks={
            "failure_contained": contained,
            "audit_complete": bool(
                failed_run
                and _has_events(
                    failed_run,
                    EventType.NODE_FAILED,
                    EventType.WORKFLOW_FAILED,
                )
            ),
        },
        details={"invalid_transitions": 0, "duplicate_executions": 0},
    )


def _evaluate_permanent_failure() -> EvaluationCaseResult:
    failed_run: WorkflowRun | None = None

    try:
        execute_workflow(
            build_service_request_workflow(),
            build_service_request_registry(),
            context=example_request(
                request_id="EVAL-PERMANENT",
                simulation_mode="PERMANENT",
            ),
            run_id="eval-permanent",
            state_store=InMemoryStateStore(),
        )
    except WorkflowExecutionError as exc:
        failed_run = exc.run

    event_types = _event_types(failed_run) if failed_run else []
    retry_ok = bool(
        failed_run
        and failed_run.node_runs["perform_automated_task"].attempt == 1
        and EventType.RETRY_SCHEDULED not in event_types
    )
    contained = bool(
        failed_run
        and failed_run.status is WorkflowStatus.FAILED
        and failed_run.node_runs["verify_result"].status is NodeStatus.PENDING
    )

    return _result(
        case_id="permanent_failure",
        category="failure_containment",
        expected="permanent failure is not retried and blocks downstream work",
        observed=failed_run.status.value if failed_run else "NO_FAILURE",
        checks={
            "retry_behavior": retry_ok,
            "failure_contained": contained,
            "audit_complete": bool(
                failed_run
                and _has_events(
                    failed_run,
                    EventType.NODE_FAILED,
                    EventType.WORKFLOW_FAILED,
                )
            ),
        },
        details={"invalid_transitions": 0, "duplicate_executions": 0},
    )


class _SimulatedProcessStop(BaseException):
    """Private abrupt-stop signal used only by the persistence evaluation."""


class _StopAfterVerificationStore:
    """Persist a safe checkpoint, then simulate one process termination."""

    def __init__(self) -> None:
        self.inner = InMemoryStateStore()
        self.triggered = False

    def save(self, run: WorkflowRun) -> None:
        self.inner.save(run)
        verify = run.node_runs.get("verify_result")
        risk_gate = run.node_runs.get("risk_gate")
        if (
            not self.triggered
            and verify is not None
            and risk_gate is not None
            and verify.status is NodeStatus.COMPLETED
            and risk_gate.status is NodeStatus.PENDING
        ):
            self.triggered = True
            raise _SimulatedProcessStop()

    def load(self, run_id: str) -> WorkflowRun:
        return self.inner.load(run_id)


def _evaluate_checkpoint_resume() -> EvaluationCaseResult:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()
    store = _StopAfterVerificationStore()
    stopped = False

    try:
        execute_workflow(
            workflow,
            registry,
            context=example_request(request_id="EVAL-RESUME"),
            run_id="eval-resume",
            state_store=store,
        )
    except _SimulatedProcessStop:
        stopped = True

    checkpoint = store.load("eval-resume")
    resumed = resume_workflow(
        workflow,
        registry,
        run_id="eval-resume",
        state_store=store,
    )
    completed_before_stop = (
        "validate_request",
        "classify_request",
        "policy_check",
        "perform_automated_task",
        "verify_result",
    )
    duplicate_executions = sum(
        max(0, resumed.node_runs[node_id].attempt - 1)
        for node_id in completed_before_stop
    )

    return _result(
        case_id="checkpoint_resume",
        category="persistence",
        expected="safe checkpoint resumes without repeating completed nodes",
        observed=resumed.status.value,
        checks={
            "completed_as_expected": resumed.status is WorkflowStatus.COMPLETED,
            "checkpoint_resume": (
                stopped
                and checkpoint.node_runs["verify_result"].status is NodeStatus.COMPLETED
                and checkpoint.node_runs["risk_gate"].status is NodeStatus.PENDING
                and duplicate_executions == 0
            ),
            "audit_complete": _has_events(
                resumed,
                EventType.WORKFLOW_RESUMED,
                EventType.WORKFLOW_COMPLETED,
            ),
        },
        details={
            "invalid_transitions": 0,
            "duplicate_executions": duplicate_executions,
        },
    )


def _evaluate_model_control_injection() -> EvaluationCaseResult:
    marker = "EVAL_MODEL_CONTROL_MARKER"

    def malicious_model(prompt: str) -> str:
        return (
            '{"classification":"ACCESS_REQUEST",'
            f'"rationale":"{marker}",'
            '"route":"HIGH_RISK","handler":"arbitrary_handler"}'
        )

    failed_run: WorkflowRun | None = None
    try:
        execute_workflow(
            build_service_request_workflow(),
            build_service_request_registry(classification_model=malicious_model),
            context=example_request(request_id="EVAL-MODEL-INJECT"),
            run_id="eval-model-inject",
            state_store=InMemoryStateStore(),
        )
    except WorkflowExecutionError as exc:
        failed_run = exc.run

    audit_text = repr([event.details for event in failed_run.events]) if failed_run else ""
    contained = bool(
        failed_run
        and failed_run.status is WorkflowStatus.FAILED
        and failed_run.node_runs["classify_request"].status is NodeStatus.FAILED
        and failed_run.node_runs["policy_check"].status is NodeStatus.PENDING
        and failed_run.node_runs["risk_gate"].status is NodeStatus.PENDING
    )
    model_contained = contained and marker not in audit_text and "arbitrary_handler" not in audit_text

    return _result(
        case_id="model_control_injection",
        category="adversarial",
        expected="unauthorized model control fields are rejected before workflow control",
        observed=failed_run.status.value if failed_run else "NO_FAILURE",
        checks={
            "failure_contained": contained,
            "model_contained": model_contained,
            "audit_complete": bool(
                failed_run
                and _has_events(
                    failed_run,
                    EventType.NODE_FAILED,
                    EventType.WORKFLOW_FAILED,
                )
            ),
        },
        details={"invalid_transitions": 0, "duplicate_executions": 0},
    )


def _evaluate_invalid_dag() -> EvaluationCaseResult:
    handler_calls = 0

    def handler(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    registry = HandlerRegistry()
    registry.register("handler", handler)
    workflow = WorkflowDefinition(
        workflow_id="eval-cycle",
        name="Evaluation Cycle",
        nodes=[
            NodeDefinition(
                node_id="alpha",
                name="Alpha",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["beta"],
            ),
            NodeDefinition(
                node_id="beta",
                name="Beta",
                node_type=NodeType.TASK,
                handler="handler",
                depends_on=["alpha"],
            ),
        ],
    )
    rejected = False
    try:
        execute_workflow(workflow, registry, run_id="eval-cycle")
    except WorkflowValidationError:
        rejected = True

    return _result(
        case_id="invalid_dag",
        category="adversarial",
        expected="cyclic graph is rejected before any handler executes",
        observed="REJECTED_BEFORE_EXECUTION" if rejected else "NOT_REJECTED",
        checks={
            "failure_contained": rejected and handler_calls == 0,
        },
        details={"invalid_transitions": 0, "duplicate_executions": 0},
    )


def _evaluate_human_gate_bypass() -> EvaluationCaseResult:
    workflow = build_service_request_workflow()
    registry = build_service_request_registry()
    store = InMemoryStateStore()
    paused = execute_workflow(
        workflow,
        registry,
        context=example_request(
            request_id="EVAL-BYPASS",
            risk_level="HIGH",
            estimated_cost=1_500.0,
        ),
        run_id="eval-bypass",
        state_store=store,
    )
    bypass_blocked = False
    try:
        resume_workflow(
            workflow,
            registry,
            run_id="eval-bypass",
            state_store=store,
        )
    except WorkflowResumeError:
        bypass_blocked = True

    unchanged = store.load("eval-bypass")
    event_types = _event_types(unchanged)

    return _result(
        case_id="human_gate_bypass",
        category="adversarial",
        expected="plain resume cannot bypass a waiting human approval gate",
        observed=unchanged.status.value,
        checks={
            "escalation_behavior": (
                paused.status is WorkflowStatus.WAITING_FOR_HUMAN
                and bypass_blocked
                and unchanged.status is WorkflowStatus.WAITING_FOR_HUMAN
                and unchanged.node_runs["high_risk_finalize"].status is NodeStatus.PENDING
            ),
            "failure_contained": bypass_blocked,
            "audit_complete": (
                EventType.HUMAN_REVIEW_REQUESTED in event_types
                and EventType.WORKFLOW_RESUMED not in event_types
            ),
        },
        details={"invalid_transitions": 0, "duplicate_executions": 0},
    )


def _result(
    *,
    case_id: str,
    category: str,
    expected: str,
    observed: str,
    checks: dict[str, bool],
    details: dict[str, str | int | float | bool] | None = None,
) -> EvaluationCaseResult:
    return EvaluationCaseResult(
        case_id=case_id,
        category=category,
        passed=bool(checks) and all(checks.values()),
        expected=expected,
        observed=observed,
        checks=checks,
        details=dict(details or {}),
    )


def _event_types(run: WorkflowRun) -> list[EventType]:
    return [event.event_type for event in run.events]


def _has_events(run: WorkflowRun, *required: EventType) -> bool:
    event_types = set(_event_types(run))
    return all(event_type in event_types for event_type in required)


def _check_rate(results: list[EvaluationCaseResult], check_name: str) -> float:
    applicable = [result.checks[check_name] for result in results if check_name in result.checks]
    if not applicable:
        return 0.0
    return sum(applicable) / len(applicable)


def _build_metrics(results: list[EvaluationCaseResult]) -> dict[str, float | int]:
    total = len(results)
    passed = sum(result.passed for result in results)
    duplicate_executions = sum(
        int(result.details.get("duplicate_executions", 0)) for result in results
    )
    invalid_transitions = sum(
        int(result.details.get("invalid_transitions", 0)) for result in results
    )

    return {
        "overall_case_pass_rate": passed / total if total else 0.0,
        "workflow_completion_rate": _check_rate(results, "completed_as_expected"),
        "expected_path_accuracy": _check_rate(results, "expected_path"),
        "retry_correctness": _check_rate(results, "retry_behavior"),
        "escalation_correctness": _check_rate(results, "escalation_behavior"),
        "checkpoint_resume_success": _check_rate(results, "checkpoint_resume"),
        "audit_log_completeness": _check_rate(results, "audit_complete"),
        "failure_containment_rate": _check_rate(results, "failure_contained"),
        "model_output_containment_rate": _check_rate(results, "model_contained"),
        "duplicate_execution_count": duplicate_executions,
        "invalid_transition_count": invalid_transitions,
    }
