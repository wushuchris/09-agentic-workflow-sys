"""Deterministic validation for workflow dependency graphs and decision routes.

The schema layer validates the shape of workflow definitions. This module validates
relationships between nodes: unique identifiers, dependency references, decision
route targets, branch separation, self-dependencies, and acyclicity.
"""

from __future__ import annotations

from heapq import heappop, heappush

from src.schemas import NodeType, WorkflowDefinition


class WorkflowValidationError(ValueError):
    """Raised when a workflow definition is structurally invalid as a DAG."""


def validate_workflow(definition: WorkflowDefinition) -> None:
    """Validate cross-node graph and deterministic routing rules."""

    _validate_unique_node_ids(definition)
    _validate_dependencies(definition)
    _validate_decision_routes(definition)
    _topological_order(definition)


def topological_order(definition: WorkflowDefinition) -> list[str]:
    """Return a deterministic topological ordering after validating the workflow.

    When more than one node is ready, node identifiers are used as a stable
    tie-breaker. The ordering is deterministic for testing and the MVP's sequential
    executor; it does not imply that production workflows must execute independent
    nodes serially.
    """

    _validate_unique_node_ids(definition)
    _validate_dependencies(definition)
    _validate_decision_routes(definition)
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


def _validate_decision_routes(definition: WorkflowDefinition) -> None:
    node_by_id = {node.node_id: node for node in definition.nodes}
    dependents: dict[str, set[str]] = {node.node_id: set() for node in definition.nodes}
    for node in definition.nodes:
        for dependency_id in node.depends_on:
            dependents[dependency_id].add(node.node_id)

    for decision in definition.nodes:
        if decision.node_type is not NodeType.DECISION:
            continue

        route_targets = set(decision.routes.values())
        for route_label, target_node_id in decision.routes.items():
            target = node_by_id.get(target_node_id)
            if target is None:
                raise WorkflowValidationError(
                    f"DECISION node '{decision.node_id}' route '{route_label}' targets "
                    f"unknown node '{target_node_id}'"
                )
            if target_node_id == decision.node_id:
                raise WorkflowValidationError(
                    f"DECISION node '{decision.node_id}' cannot route to itself"
                )
            if decision.node_id not in target.depends_on:
                raise WorkflowValidationError(
                    f"route target '{target_node_id}' must directly depend on "
                    f"DECISION node '{decision.node_id}'"
                )

        direct_dependents = dependents[decision.node_id]
        if direct_dependents != route_targets:
            unrouted = sorted(direct_dependents - route_targets)
            extra = sorted(route_targets - direct_dependents)
            details: list[str] = []
            if unrouted:
                details.append(f"unrouted dependents: {', '.join(unrouted)}")
            if extra:
                details.append(f"invalid route targets: {', '.join(extra)}")
            detail_text = "; ".join(details)
            raise WorkflowValidationError(
                f"DECISION node '{decision.node_id}' must route all direct dependents"
                + (f" ({detail_text})" if detail_text else "")
            )

        branch_reach: dict[str, set[str]] = {}
        for target_node_id in sorted(route_targets):
            reachable = _reachable_nodes(target_node_id, dependents)
            for other_target, other_reachable in branch_reach.items():
                overlap = sorted(reachable & other_reachable)
                if overlap:
                    raise WorkflowValidationError(
                        f"DECISION node '{decision.node_id}' branch reconvergence is "
                        f"not supported; routes through '{other_target}' and "
                        f"'{target_node_id}' both reach: {', '.join(overlap)}"
                    )
            branch_reach[target_node_id] = reachable


def _reachable_nodes(start_node_id: str, dependents: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    stack = [start_node_id]

    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(sorted(dependents[node_id], reverse=True))

    return reachable


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
