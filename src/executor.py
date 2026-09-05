"""Deterministic sequential workflow executor with durable checkpoints.

The executor validates the DAG, resolves only allowlisted handlers, emits structured
audit events, enforces bounded retries, resumes safe checkpoints, and pauses durably
at HUMAN_GATE nodes until an explicit human decision is submitted. Branching
semantics and live model calls are added in later layers.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.events import record_event
from src.human import HumanReviewError, create_review, decide_review
from src.persistence import StateStore
from src.registry import HandlerRegistry
from src.retry import should_retry
from src.schemas import (
    EventType,
    HumanDecision,
    HumanReviewRequest,
    NodeDefinition,
    NodeRun,
    NodeStatus,
    NodeType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
    utc_now,
)
from src.validator import topological_order


class WorkflowExecutionError(RuntimeError):
    """Raised when execution fails while preserving the failed workflow state."""

    def __init__(self, message: str, run: WorkflowRun) -> None:
        super().__init__(message)
        self.run = run


class WorkflowResumeError(RuntimeError):
    """Raised when a persisted workflow cannot be resumed safely."""

    def __init__(self, message: str, run: WorkflowRun) -> None:
        super().__init__(message)
        self.run = run


class WorkflowHumanDecisionError(RuntimeError):
    """Raised when a human decision cannot be applied safely."""

    def __init__(self, message: str, run: WorkflowRun) -> None:
        super().__init__(message)
        self.run = run


def execute_workflow(
    definition: WorkflowDefinition,
    registry: HandlerRegistry,
    *,
    context: dict[str, Any] | None = None,
    run_id: str | None = None,
    state_store: StateStore | None = None,
) -> WorkflowRun:
    """Start and execute a validated workflow until completion or a human gate."""

    order = topological_order(definition)
    node_by_id = {node.node_id: node for node in definition.nodes}

    run = WorkflowRun(
        run_id=run_id or str(uuid4()),
        workflow_id=definition.workflow_id,
        workflow_version=definition.version,
        status=WorkflowStatus.RUNNING,
        node_runs={
            node.node_id: NodeRun(node_id=node.node_id, status=NodeStatus.PENDING)
            for node in definition.nodes
        },
        context=dict(context or {}),
    )
    record_event(
        run,
        EventType.WORKFLOW_STARTED,
        details={"workflow_id": definition.workflow_id, "version": definition.version},
    )
    _checkpoint(state_store, run)

    return _run_remaining_nodes(
        definition,
        registry,
        run,
        order=order,
        node_by_id=node_by_id,
        state_store=state_store,
    )


def resume_workflow(
    definition: WorkflowDefinition,
    registry: HandlerRegistry,
    *,
    run_id: str,
    state_store: StateStore,
) -> WorkflowRun:
    """Resume a safe non-human checkpoint without repeating completed nodes.

    Completed runs are returned unchanged, making resume idempotent. A run waiting
    at a HUMAN_GATE must use submit_human_decision instead of this function. A node
    persisted as RUNNING is deliberately not replayed automatically because its
    handler may have produced side effects before the process stopped.
    """

    order = topological_order(definition)
    node_by_id = {node.node_id: node for node in definition.nodes}
    run = state_store.load(run_id)

    _validate_resume_checkpoint(definition, run)

    if run.status is WorkflowStatus.COMPLETED:
        return run

    previous_status = run.status
    run.status = WorkflowStatus.RUNNING
    run.updated_at = utc_now()
    record_event(
        run,
        EventType.WORKFLOW_RESUMED,
        details={"previous_status": previous_status.value},
    )
    _checkpoint(state_store, run)

    return _run_remaining_nodes(
        definition,
        registry,
        run,
        order=order,
        node_by_id=node_by_id,
        state_store=state_store,
    )


def submit_human_decision(
    definition: WorkflowDefinition,
    registry: HandlerRegistry,
    *,
    run_id: str,
    review_id: str,
    decision: HumanDecision | str,
    state_store: StateStore,
) -> WorkflowRun:
    """Apply one explicit decision to a durable HUMAN_GATE checkpoint.

    APPROVE completes the gate and resumes downstream execution. REJECT completes
    the gate but terminates the overall workflow as REJECTED. RETRY records the
    decision and opens a fresh review request for the same gate without replaying
    upstream tasks.
    """

    order = topological_order(definition)
    node_by_id = {node.node_id: node for node in definition.nodes}
    run = state_store.load(run_id)

    try:
        normalized_decision = HumanDecision(decision)
    except ValueError as exc:
        raise WorkflowHumanDecisionError(
            f"unknown human decision '{decision}'",
            run,
        ) from exc

    try:
        review = _validate_human_checkpoint(definition, run, review_id)
        decided_review = decide_review(
            run,
            review_id=review_id,
            decision=normalized_decision,
        )
    except (HumanReviewError, WorkflowResumeError) as exc:
        raise WorkflowHumanDecisionError(str(exc), run) from exc

    node = node_by_id[decided_review.node_id]
    node_run = run.node_runs[node.node_id]
    now = utc_now()

    if normalized_decision is HumanDecision.RETRY:
        retry_review = create_review(
            run,
            node_id=node.node_id,
            reason=decided_review.reason,
            retry_of=decided_review.review_id,
        )
        run.status = WorkflowStatus.WAITING_FOR_HUMAN
        run.updated_at = now
        _checkpoint(state_store, run)
        return run

    node_run.status = NodeStatus.COMPLETED
    node_run.output = {
        "decision": normalized_decision.value,
        "review_id": decided_review.review_id,
    }
    node_run.error = None
    node_run.completed_at = now
    run.updated_at = now

    if normalized_decision is HumanDecision.REJECT:
        record_event(
            run,
            EventType.HUMAN_REJECTED,
            node_id=node.node_id,
            details={"review_id": decided_review.review_id},
        )
        record_event(
            run,
            EventType.NODE_COMPLETED,
            node_id=node.node_id,
            details={"human_decision": HumanDecision.REJECT.value},
        )
        run.status = WorkflowStatus.REJECTED
        _checkpoint(state_store, run)
        return run

    record_event(
        run,
        EventType.HUMAN_APPROVED,
        node_id=node.node_id,
        details={"review_id": decided_review.review_id},
    )
    record_event(
        run,
        EventType.NODE_COMPLETED,
        node_id=node.node_id,
        details={"human_decision": HumanDecision.APPROVE.value},
    )
    run.status = WorkflowStatus.RUNNING
    record_event(
        run,
        EventType.WORKFLOW_RESUMED,
        details={
            "previous_status": WorkflowStatus.WAITING_FOR_HUMAN.value,
            "review_id": decided_review.review_id,
        },
    )
    _checkpoint(state_store, run)

    return _run_remaining_nodes(
        definition,
        registry,
        run,
        order=order,
        node_by_id=node_by_id,
        state_store=state_store,
    )


def _run_remaining_nodes(
    definition: WorkflowDefinition,
    registry: HandlerRegistry,
    run: WorkflowRun,
    *,
    order: list[str],
    node_by_id: dict[str, NodeDefinition],
    state_store: StateStore | None,
) -> WorkflowRun:
    for node_id in order:
        node_run = run.node_runs[node_id]
        if node_run.status is NodeStatus.COMPLETED:
            continue
        if node_run.status not in {
            NodeStatus.PENDING,
            NodeStatus.READY,
            NodeStatus.RETRY_SCHEDULED,
        }:
            raise WorkflowResumeError(
                f"node '{node_id}' is in non-resumable state '{node_run.status.value}'",
                run,
            )

        node = node_by_id[node_id]
        if node.node_type is NodeType.TASK:
            _execute_task_node(node, run, registry, state_store)
            continue
        if node.node_type is NodeType.HUMAN_GATE:
            return _pause_for_human_review(node, run, state_store)

        _mark_preexecution_failure(
            run,
            node_run,
            f"node '{node.node_id}' uses unsupported node type '{node.node_type.value}' "
            "in the current executor",
            state_store,
        )

    run.status = WorkflowStatus.COMPLETED
    run.updated_at = utc_now()
    run.final_output = _build_final_output(definition, run)
    record_event(
        run,
        EventType.WORKFLOW_COMPLETED,
        details={"terminal_nodes": sorted(run.final_output)},
    )
    _checkpoint(state_store, run)
    return run


def _pause_for_human_review(
    node: NodeDefinition,
    run: WorkflowRun,
    state_store: StateStore | None,
) -> WorkflowRun:
    node_run = run.node_runs[node.node_id]

    if state_store is None:
        _mark_preexecution_failure(
            run,
            node_run,
            f"HUMAN_GATE node '{node.node_id}' requires a state_store",
            state_store,
        )

    reason = node.config.get("reason", node.name)
    if not isinstance(reason, str) or not reason.strip():
        _mark_preexecution_failure(
            run,
            node_run,
            f"HUMAN_GATE node '{node.node_id}' requires a non-blank string reason",
            state_store,
        )

    now = utc_now()
    node_run.status = NodeStatus.WAITING_FOR_HUMAN
    node_run.started_at = node_run.started_at or now
    node_run.error = None
    run.status = WorkflowStatus.WAITING_FOR_HUMAN
    run.updated_at = now
    record_event(
        run,
        EventType.NODE_STARTED,
        node_id=node.node_id,
        details={"node_type": NodeType.HUMAN_GATE.value},
    )
    create_review(run, node_id=node.node_id, reason=reason.strip())
    _checkpoint(state_store, run)
    return run


def _execute_task_node(
    node: NodeDefinition,
    run: WorkflowRun,
    registry: HandlerRegistry,
    state_store: StateStore | None,
) -> None:
    node_run = run.node_runs[node.node_id]

    if node.handler is None:
        _mark_preexecution_failure(
            run,
            node_run,
            f"TASK node '{node.node_id}' must declare a handler",
            state_store,
        )

    dependency_outputs = {
        dependency_id: run.node_runs[dependency_id].output
        for dependency_id in node.depends_on
    }
    payload = {
        "context": dict(run.context),
        "dependencies": dependency_outputs,
        "config": dict(node.config),
        "node_id": node.node_id,
    }

    while True:
        node_run.status = NodeStatus.RUNNING
        node_run.attempt += 1
        node_run.error = None
        node_run.completed_at = None
        node_run.started_at = utc_now()
        run.status = WorkflowStatus.RUNNING
        run.updated_at = node_run.started_at
        record_event(
            run,
            EventType.NODE_STARTED,
            node_id=node.node_id,
            details={"handler": node.handler, "attempt": node_run.attempt},
        )
        _checkpoint(state_store, run)

        try:
            handler = registry.resolve(node.handler)
            output = handler(payload)
            if not isinstance(output, dict):
                raise TypeError("handler output must be a dictionary")
        except Exception as exc:
            retry = should_retry(
                node.retry_policy,
                attempt=node_run.attempt,
                error=exc,
            )
            node_run.error = str(exc)
            run.updated_at = utc_now()
            record_event(
                run,
                EventType.NODE_FAILED,
                node_id=node.node_id,
                details={
                    "attempt": node_run.attempt,
                    "error": str(exc),
                    "will_retry": retry,
                },
            )

            if retry:
                node_run.status = NodeStatus.RETRY_SCHEDULED
                run.status = WorkflowStatus.RETRY_SCHEDULED
                record_event(
                    run,
                    EventType.RETRY_SCHEDULED,
                    node_id=node.node_id,
                    details={
                        "attempt": node_run.attempt,
                        "next_attempt": node_run.attempt + 1,
                        "max_attempts": node.retry_policy.max_attempts,
                    },
                )
                _checkpoint(state_store, run)
                continue

            node_run.status = NodeStatus.FAILED
            node_run.completed_at = utc_now()
            run.status = WorkflowStatus.FAILED
            run.updated_at = node_run.completed_at
            record_event(
                run,
                EventType.WORKFLOW_FAILED,
                details={"failed_node": node.node_id},
            )
            _checkpoint(state_store, run)
            raise WorkflowExecutionError(
                f"node '{node.node_id}' failed: {exc}",
                run,
            ) from exc

        node_run.output = output
        node_run.error = None
        node_run.status = NodeStatus.COMPLETED
        node_run.completed_at = utc_now()
        run.updated_at = node_run.completed_at
        record_event(
            run,
            EventType.NODE_COMPLETED,
            node_id=node.node_id,
            details={"attempt": node_run.attempt},
        )
        _checkpoint(state_store, run)
        return


def _mark_preexecution_failure(
    run: WorkflowRun,
    node_run: NodeRun,
    message: str,
    state_store: StateStore | None,
) -> None:
    node_run.status = NodeStatus.FAILED
    node_run.error = message
    node_run.completed_at = utc_now()
    run.status = WorkflowStatus.FAILED
    run.updated_at = node_run.completed_at
    record_event(
        run,
        EventType.NODE_FAILED,
        node_id=node_run.node_id,
        details={"attempt": node_run.attempt, "error": message, "will_retry": False},
    )
    record_event(
        run,
        EventType.WORKFLOW_FAILED,
        details={"failed_node": node_run.node_id},
    )
    _checkpoint(state_store, run)
    raise WorkflowExecutionError(message, run)


def _validate_checkpoint_identity(
    definition: WorkflowDefinition,
    run: WorkflowRun,
) -> None:
    if run.workflow_id != definition.workflow_id:
        raise WorkflowResumeError(
            f"checkpoint workflow_id '{run.workflow_id}' does not match "
            f"definition '{definition.workflow_id}'",
            run,
        )
    if run.workflow_version != definition.version:
        raise WorkflowResumeError(
            f"checkpoint workflow version '{run.workflow_version}' does not match "
            f"definition version '{definition.version}'",
            run,
        )

    expected_node_ids = {node.node_id for node in definition.nodes}
    actual_node_ids = set(run.node_runs)
    if actual_node_ids != expected_node_ids:
        raise WorkflowResumeError(
            "checkpoint node set does not match the workflow definition",
            run,
        )


def _validate_resume_checkpoint(
    definition: WorkflowDefinition,
    run: WorkflowRun,
) -> None:
    _validate_checkpoint_identity(definition, run)

    if run.status is WorkflowStatus.COMPLETED:
        return
    if run.status is WorkflowStatus.WAITING_FOR_HUMAN:
        raise WorkflowResumeError(
            "workflow is waiting for a human decision; use submit_human_decision",
            run,
        )
    if run.status not in {
        WorkflowStatus.PENDING,
        WorkflowStatus.RUNNING,
        WorkflowStatus.RETRY_SCHEDULED,
    }:
        raise WorkflowResumeError(
            f"workflow run is in non-resumable state '{run.status.value}'",
            run,
        )

    resumable_node_states = {
        NodeStatus.PENDING,
        NodeStatus.READY,
        NodeStatus.RETRY_SCHEDULED,
        NodeStatus.COMPLETED,
    }
    for node in definition.nodes:
        node_status = run.node_runs[node.node_id].status
        if node_status not in resumable_node_states:
            raise WorkflowResumeError(
                f"node '{node.node_id}' is in ambiguous or non-resumable state "
                f"'{node_status.value}'",
                run,
            )
        if node_status is NodeStatus.COMPLETED:
            for dependency_id in node.depends_on:
                if run.node_runs[dependency_id].status is not NodeStatus.COMPLETED:
                    raise WorkflowResumeError(
                        f"completed node '{node.node_id}' has incomplete dependency "
                        f"'{dependency_id}'",
                        run,
                    )


def _validate_human_checkpoint(
    definition: WorkflowDefinition,
    run: WorkflowRun,
    review_id: str,
) -> HumanReviewRequest:
    _validate_checkpoint_identity(definition, run)

    if run.status is not WorkflowStatus.WAITING_FOR_HUMAN:
        raise WorkflowResumeError(
            f"workflow run is not waiting for a human decision; status is "
            f"'{run.status.value}'",
            run,
        )

    review = next(
        (item for item in run.human_reviews if item.review_id == review_id),
        None,
    )
    if review is None:
        raise HumanReviewError(f"human review '{review_id}' was not found")
    if review.decision is not None:
        raise HumanReviewError(
            f"human review '{review_id}' already has decision '{review.decision.value}'"
        )

    node_by_id = {node.node_id: node for node in definition.nodes}
    node = node_by_id[review.node_id]
    if node.node_type is not NodeType.HUMAN_GATE:
        raise WorkflowResumeError(
            f"human review '{review_id}' does not reference a HUMAN_GATE node",
            run,
        )

    node_run = run.node_runs[review.node_id]
    if node_run.status is not NodeStatus.WAITING_FOR_HUMAN:
        raise WorkflowResumeError(
            f"human gate node '{review.node_id}' is not waiting for human input",
            run,
        )

    for dependency_id in node.depends_on:
        if run.node_runs[dependency_id].status is not NodeStatus.COMPLETED:
            raise WorkflowResumeError(
                f"human gate '{node.node_id}' has incomplete dependency "
                f"'{dependency_id}'",
                run,
            )

    return review


def _checkpoint(state_store: StateStore | None, run: WorkflowRun) -> None:
    if state_store is not None:
        state_store.save(run)


def _build_final_output(
    definition: WorkflowDefinition,
    run: WorkflowRun,
) -> dict[str, Any]:
    dependents = {node.node_id: 0 for node in definition.nodes}
    for node in definition.nodes:
        for dependency_id in node.depends_on:
            dependents[dependency_id] += 1

    terminal_node_ids = sorted(
        node_id for node_id, dependent_count in dependents.items() if dependent_count == 0
    )

    return {
        node_id: run.node_runs[node_id].output
        for node_id in terminal_node_ids
    }
