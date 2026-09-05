"""Allowlisted handler registry for workflow task execution.

The registry is the application-controlled boundary between a workflow definition
and executable Python code. Workflow data may name a handler, but only handlers
explicitly registered here can ever be resolved for execution.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeAlias


Handler: TypeAlias = Callable[[dict[str, Any]], dict[str, Any]]


class HandlerRegistryError(ValueError):
    """Base error for invalid handler-registry operations."""


class DuplicateHandlerError(HandlerRegistryError):
    """Raised when code tries to register the same handler identifier twice."""


class UnknownHandlerError(HandlerRegistryError):
    """Raised when a workflow requests a handler that is not allowlisted."""


class HandlerRegistry:
    """Explicit allowlist mapping stable handler IDs to Python callables."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, handler_id: str, handler: Handler) -> None:
        """Register one approved handler under a stable application-owned ID."""

        normalized_id = handler_id.strip()
        if not normalized_id:
            raise HandlerRegistryError("handler_id must not be blank")
        if not callable(handler):
            raise HandlerRegistryError("handler must be callable")
        if normalized_id in self._handlers:
            raise DuplicateHandlerError(
                f"handler '{normalized_id}' is already registered"
            )

        self._handlers[normalized_id] = handler

    def resolve(self, handler_id: str) -> Handler:
        """Return an approved handler or reject an unknown identifier."""

        normalized_id = handler_id.strip()
        if not normalized_id:
            raise UnknownHandlerError("handler_id must not be blank")

        try:
            return self._handlers[normalized_id]
        except KeyError as exc:
            raise UnknownHandlerError(
                f"handler '{normalized_id}' is not registered"
            ) from exc

    def contains(self, handler_id: str) -> bool:
        """Return whether a handler identifier is currently allowlisted."""

        normalized_id = handler_id.strip()
        return bool(normalized_id) and normalized_id in self._handlers

    def registered_ids(self) -> tuple[str, ...]:
        """Return registered handler IDs in deterministic sorted order."""

        return tuple(sorted(self._handlers))
