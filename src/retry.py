"""Deterministic retry policy helpers for workflow task execution.

A handler may explicitly signal a transient failure by raising
RetryableHandlerError. The workflow runtime still owns the final decision: a retry
occurs only when the node's RetryPolicy allows retries and attempts remain.
"""

from __future__ import annotations

from src.schemas import RetryPolicy


class RetryableHandlerError(RuntimeError):
    """Explicit signal that a handler failure may be safe to retry."""


def should_retry(
    policy: RetryPolicy,
    *,
    attempt: int,
    error: Exception,
) -> bool:
    """Return whether another attempt is permitted for this failure.

    Retries are intentionally opt-in twice: the handler must raise the explicit
    transient-failure type, and the workflow definition must enable retries with
    remaining attempts.
    """

    return (
        isinstance(error, RetryableHandlerError)
        and policy.retryable
        and attempt < policy.max_attempts
    )
