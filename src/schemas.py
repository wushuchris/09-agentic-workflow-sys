"""Structured domain models for the Agentic Workflow System.

These schemas define the valid vocabulary for workflow definitions, runtime state,
events, retries, and human review. They intentionally do not perform graph-level
DAG validation; that belongs to the workflow validator layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    """Base model that rejects unknown fields and strips string whitespace."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class NodeType(str, Enum):
    TASK = "TASK"
    DECISION = "DECISION"
    HUMAN_GATE = "HUMAN_GATE"
    END = "END"


class EventType(str, Enum):
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    NODE_STARTED = "NODE_STARTED"
    NODE_COMPLETED = "NODE_COMPLETED"
    NODE_FAILED = "NODE_FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    HUMAN_REVIEW_REQUESTED = "HUMAN_REVIEW_REQUESTED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_REJECTED = "HUMAN_REJECTED"
    WORKFLOW_RESUMED = "WORKFLOW_RESUMED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"


class HumanDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETRY = "RETRY"


class RetryPolicy(StrictModel):
    """Bounded retry policy for a workflow node."""

    retryable: bool = False
    max_attempts: int = Field(default=1, ge=1, le=10)

    @model_validator(mode="after")
    def non_retryable_nodes_have_one_attempt(self) -> "RetryPolicy":
        if not self.retryable and self.max_attempts != 1:
            raise ValueError("non-retryable nodes must use max_attempts=1")
        return self


class NodeDefinition(StrictModel):
    """Static definition of one node in a workflow."""

    node_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    node_type: NodeType
    handler: str | None = Field(default=None, min_length=1, max_length=200)
    depends_on: list[str] = Field(default_factory=list)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinition(StrictModel):
    """Static workflow definition supplied to the future DAG validator/executor."""

    workflow_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1.0", min_length=1, max_length=50)
    nodes: list[NodeDefinition] = Field(min_length=1)


class NodeRun(StrictModel):
    """Runtime state for one node execution within a workflow run."""

    node_id: str = Field(min_length=1, max_length=100)
    status: NodeStatus = NodeStatus.PENDING
    attempt: int = Field(default=0, ge=0, le=10)
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkflowEvent(StrictModel):
    """Structured audit event emitted when workflow state changes."""

    event_id: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=100)
    event_type: EventType
    node_id: str | None = Field(default=None, min_length=1, max_length=100)
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class WorkflowRun(StrictModel):
    """Durable runtime state and append-only audit history for one workflow run."""

    run_id: str = Field(min_length=1, max_length=100)
    workflow_id: str = Field(min_length=1, max_length=100)
    workflow_version: str = Field(default="1.0", min_length=1, max_length=50)
    status: WorkflowStatus = WorkflowStatus.PENDING
    node_runs: dict[str, NodeRun] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    events: tuple[WorkflowEvent, ...] = Field(default_factory=tuple)
    final_output: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class HumanReviewRequest(StrictModel):
    """Structured checkpoint requiring an explicit human decision."""

    review_id: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=100)
    node_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)
    decision: HumanDecision | None = None
    requested_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None
