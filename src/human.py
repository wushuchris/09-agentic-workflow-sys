"""Human-in-the-loop helpers for durable workflow gates.

A HUMAN_GATE pauses execution and persists a HumanReviewRequest. Decisions are
recorded structurally so the workflow can later approve, reject, or re-open the
review without replaying upstream work.
"""

from __future__ import annotations

from uuid import uuid4

from src.events import record_event
from src.schemas import (
    EventType,
    HumanDecision,
    HumanReviewRequest,
    WorkflowRun,
    utc_now,
)


class HumanReviewError(RuntimeError):
    """Raised when a human-review operation is invalid or ambiguous."""


def create_review(
    run: WorkflowRun,
    *,
    node_id: str,
    reason: str,
    retry_of: str | None = None,
) -> HumanReviewRequest:
    """Create and append one open human review request."""

    review = HumanReviewRequest(
        review_id=str(uuid4()),
        run_id=run.run_id,
        node_id=node_id,
        reason=reason,
    )
    run.human_reviews = (*run.human_reviews, review)

    details: dict[str, str] = {
        "review_id": review.review_id,
        "reason": reason,
    }
    if retry_of is not None:
        details["retry_of"] = retry_of

    record_event(
        run,
        EventType.HUMAN_REVIEW_REQUESTED,
        node_id=node_id,
        details=details,
    )
    return review


def get_open_review(run: WorkflowRun, review_id: str) -> HumanReviewRequest:
    """Return the requested open review or reject stale/unknown review IDs."""

    for review in run.human_reviews:
        if review.review_id == review_id:
            if review.decision is not None:
                raise HumanReviewError(
                    f"human review '{review_id}' already has decision "
                    f"'{review.decision.value}'"
                )
            return review

    raise HumanReviewError(f"human review '{review_id}' was not found")


def decide_review(
    run: WorkflowRun,
    *,
    review_id: str,
    decision: HumanDecision,
) -> HumanReviewRequest:
    """Persist a decision by replacing the immutable review value in history."""

    review = get_open_review(run, review_id)
    decided = review.model_copy(
        update={"decision": decision, "decided_at": utc_now()}
    )
    run.human_reviews = tuple(
        decided if item.review_id == review_id else item
        for item in run.human_reviews
    )
    return decided
