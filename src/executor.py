"""Basic deterministic workflow executor for TASK-only MVP execution.

This executor intentionally supports only sequential TASK-node execution. Retry
handling, persistence, human gates, branching semantics, and live model calls are
added in later layers. Structured audit events are emitted for every meaningful
state transition.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.events import record_event
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
    utc_now,
)
from src.validator import topological_order


class WorkflowExecutionError(RuntimeError):
    """Raised when execution fails while preserving the failed workflow state."""

    def __init__(self, message: str, run: WorkflowRun) -> None:
        super().__init__(message)
        self.run = run


def execute_workflow(
    definition: WorkflowDefinition,
    registry: HandlerRegistry,
    *,
    context: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> WorkflowRun:
    """Execute a validated TASK-only workflow sequentially.

    Each handler receives a structured payload containing the node configuration,
    shared workflow context, and outputs from declared dependencies. The handler
    must return a dictionary. Any execution failure marks the workflow FAILED and
    raises WorkflowExecutionError carrying the failed WorkflowRun for inspection.

    Audit events intentionally contain control metadata rather than full context or
    handler outputs, reducing the chance that the audit trail becomes a data leak.
    """

    order = topological_order(definition)
    node_by_id = {node.node_id: node for node in definition.nodes}

    run = WorkflowRun(
        run_id=run_id or str(uuid4()),
        workflow_id=definition.workflow_id,
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

    for node_id in order:
        node = node_by_id[node_id]
        _execute_task_node(node, run, registry)

    run.status = WorkflowStatus.COMPLETED
    run.updated_at = utc_now()
    run.final_output = _build_final_output(definition, run)
    record_event(
        run,
        EventType.WORKFLOW_COMPLETED,
        details={"terminal_nodes": sorted(run.final_output)},
    )
    return run


def _execute_task_node(
    node: NodeDefinition,
    run: WorkflowRun,
    registry: HandlerRegistry,
) -> None:
    node_run = run.node_runs[node.node_id]

    if node.node_type is not NodeType.TASK:
        _mark_preexecution_failure(
            run,
            node_run,
            f"node '{node.node_id}' uses unsupported node type '{node.node_type.value}' "
            "in the basic executor",
        )

    if node.handler is None:
        _mark_preexecution_failure(
            run,
            node_run,
            f"TASK node '{node.node_id}' must declare a handler",
        )

    node_run.status = NodeStatus.RUNNING
    node_run.attempt = 1
    node_run.started_at = utc_now()
    run.updated_at = node_run.started_at
    record_event(
        run,
        EventType.NODE_STARTED,
        node_id=node.node_id,
        details={"handler": node.handler, "attempt": node_run.attempt},
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

    try:
        handler = registry.resolve(node.handler)
        output = handler(payload)
        if not isinstance(output, dict):
            raise TypeError("handler output must be a dictionary")
    except Exception as exc:
        node_run.status = NodeStatus.FAILED
        node_run.error = str(exc)
        node_run.completed_at = utc_now()
        run.status = WorkflowStatus.FAILED
        run.updated_at = node_run.completed_at
        record_event(
            run,
            EventType.NODE_FAILED,
            node_id=node.node_id,
            details={"attempt": node_run.attempt, "error": str(exc)},
        )
        record_event(
            run,
            EventType.WORKFLOW_FAILED,
            details={"failed_node": node.node_id},
        )
        raise WorkflowExecutionError(
            f"node '{node.node_id}' failed: {exc}",
            run,
        ) from exc

    node_run.output = output
    node_run.status = NodeStatus.COMPLETED
    node_run.completed_at = utc_now()
    run.updated_at = node_run.completed_at
    record_event(
        run,
        EventType.NODE_COMPLETED,
        node_id=node.node_id,
        details={"attempt": node_run.attempt},
    )


def _mark_preexecution_failure(
    run: WorkflowRun,
    node_run: NodeRun,
    message: str,
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
        details={"attempt": node_run.attempt, "error": message},
    )
    record_event(
        run,
        EventType.WORKFLOW_FAILED,
        details={"failed_node": node_run.node_id},
    )
    raise WorkflowExecutionError(message, run)


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
