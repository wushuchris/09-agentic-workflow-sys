"""Structured audit-event helpers for workflow execution.

Events complement runtime state: state answers where a workflow is now, while the
event history explains how it got there. The recorder only appends new immutable
WorkflowEvent values to the tuple stored on WorkflowRun.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.schemas import EventType, WorkflowEvent, WorkflowRun, utc_now


def record_event(
    run: WorkflowRun,
    event_type: EventType,
    *,
    node_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> WorkflowEvent:
    """Append one structured audit event to a workflow run and return it."""

    event = WorkflowEvent(
        event_id=str(uuid4()),
        run_id=run.run_id,
        event_type=event_type,
        node_id=node_id,
        details=dict(details or {}),
        timestamp=utc_now(),
    )
    run.events = (*run.events, event)
    return event
