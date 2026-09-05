"""Deterministic sequential workflow executor with durable checkpoints.

The executor validates the DAG, resolves only allowlisted handlers, emits structured
audit events, enforces bounded retries, and can resume safe persisted checkpoints
without re-running completed nodes. Human gates, branching semantics, and live model
calls are added in later layers.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.events import record_event
from src.persistence import StateStore
from src.registry import HandlerRegistry
from src.retry import should_retry
from src.schemas import (
    EventType,
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


def execute_workflow(
    definition: WorkflowDefinition,
    registry: HandlerRegistry,
    *,
    context: dict[str, Any] | None = None,
    run_id: str | None = None,
    state_store: StateStore | None = None,
) -> WorkflowRun:
    """Start and execute a validated TASK-only workflow sequentially."""

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
    """Resume a safe persisted checkpoint without repeating completed nodes.

    Completed runs are returned unchanged, making resume idempotent. A node persisted
    as RUNNING is deliberately not replayed automatically because its handler may
    have produced side effects before the process stopped. That ambiguous case must
    wait for a future idempotency/reconciliation layer or explicit human handling.
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

        _execute_task_node(node_by_id[node_id], run, registry, state_store)

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


def _execute_task_node(
    node: NodeDefinition,
    run: WorkflowRun,
    registry: HandlerRegistry,
    state_store: StateStore | None,
) -> None:
    node_run = run.node_runs[node.node_id]

    if node.node_type is not NodeType.TASK:
        _mark_preexecution_failure(
            run,
            node_run,
            f"node '{node.node_id}' uses unsupported node type '{node.node_type.value}' "
            "in the basic executor",
            state_store,
        )

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


def _validate_resume_checkpoint(
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

    if run.status is WorkflowStatus.COMPLETED:
        return
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
