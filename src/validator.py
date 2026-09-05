"""Deterministic validation for workflow dependency graphs.

The schema layer validates the shape of workflow definitions. This module validates
relationships between nodes: unique identifiers, dependency references, self-
dependencies, and acyclicity.
"""

from __future__ import annotations

from heapq import heappop, heappush

from src.schemas import WorkflowDefinition


class WorkflowValidationError(ValueError):
    """Raised when a workflow definition is structurally invalid as a DAG."""


def validate_workflow(definition: WorkflowDefinition) -> None:
    """Validate cross-node graph rules for a workflow definition.

    Raises:
        WorkflowValidationError: If node identifiers are duplicated, dependencies
            are unknown, a node depends on itself, or the graph contains a cycle.
    """

    _validate_unique_node_ids(definition)
    _validate_dependencies(definition)
    _topological_order(definition)


def topological_order(definition: WorkflowDefinition) -> list[str]:
    """Return a deterministic topological ordering after validating the workflow.

    When more than one node is ready, node identifiers are used as a stable
    tie-breaker. The ordering is deterministic for testing and the MVP's future
    sequential executor; it does not imply that production workflows must execute
    independent nodes serially.
    """

    _validate_unique_node_ids(definition)
    _validate_dependencies(definition)
    return _topological_order(definition)


def _validate_unique_node_ids(definition: WorkflowDefinition) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()

    for node in definition.nodes:
        if node.node_id in seen:
            duplicates.add(node.node_id)
        seen.add(node.node_id)

    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise WorkflowValidationError(f"duplicate node_id values: {duplicate_list}")


def _validate_dependencies(definition: WorkflowDefinition) -> None:
    node_ids = {node.node_id for node in definition.nodes}

    for node in definition.nodes:
        for dependency_id in node.depends_on:
            if dependency_id == node.node_id:
                raise WorkflowValidationError(
                    f"node '{node.node_id}' cannot depend on itself"
                )
            if dependency_id not in node_ids:
                raise WorkflowValidationError(
                    f"node '{node.node_id}' depends on unknown node "
                    f"'{dependency_id}'"
                )


def _topological_order(definition: WorkflowDefinition) -> list[str]:
    """Use Kahn's algorithm to produce an order or reject a cyclic graph."""

    indegree = {node.node_id: len(node.depends_on) for node in definition.nodes}
    dependents: dict[str, list[str]] = {node.node_id: [] for node in definition.nodes}

    for node in definition.nodes:
        for dependency_id in node.depends_on:
            dependents[dependency_id].append(node.node_id)

    ready: list[str] = []
    for node_id, degree in indegree.items():
        if degree == 0:
            heappush(ready, node_id)

    order: list[str] = []

    while ready:
        node_id = heappop(ready)
        order.append(node_id)

        for dependent_id in sorted(dependents[node_id]):
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                heappush(ready, dependent_id)

    if len(order) != len(definition.nodes):
        blocked = sorted(node_id for node_id, degree in indegree.items() if degree > 0)
        blocked_list = ", ".join(blocked)
        raise WorkflowValidationError(
            f"workflow dependency graph contains a cycle; blocked nodes: {blocked_list}"
        )

    return order
