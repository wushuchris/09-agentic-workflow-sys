import pytest

from src.schemas import NodeDefinition, NodeType, WorkflowDefinition
from src.validator import WorkflowValidationError, topological_order, validate_workflow


def make_node(
    node_id: str,
    *,
    depends_on: list[str] | None = None,
    node_type: NodeType = NodeType.TASK,
) -> NodeDefinition:
    return NodeDefinition(
        node_id=node_id,
        name=node_id.replace("_", " ").title(),
        node_type=node_type,
        depends_on=depends_on or [],
    )


def make_workflow(nodes: list[NodeDefinition]) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="test-workflow",
        name="Test Workflow",
        nodes=nodes,
    )


def test_valid_linear_dag_passes_validation() -> None:
    workflow = make_workflow(
        [
            make_node("intake"),
            make_node("validate", depends_on=["intake"]),
            make_node("finish", depends_on=["validate"], node_type=NodeType.END),
        ]
    )

    assert validate_workflow(workflow) is None
    assert topological_order(workflow) == ["intake", "validate", "finish"]


def test_valid_branching_dag_has_deterministic_order() -> None:
    workflow = make_workflow(
        [
            make_node("start"),
            make_node("beta", depends_on=["start"]),
            make_node("alpha", depends_on=["start"]),
            make_node("finish", depends_on=["alpha", "beta"], node_type=NodeType.END),
        ]
    )

    assert topological_order(workflow) == ["start", "alpha", "beta", "finish"]


def test_independent_ready_nodes_use_stable_node_id_order() -> None:
    workflow = make_workflow([make_node("beta"), make_node("alpha")])

    assert topological_order(workflow) == ["alpha", "beta"]


def test_duplicate_node_ids_are_rejected() -> None:
    workflow = make_workflow([make_node("same"), make_node("same")])

    with pytest.raises(WorkflowValidationError, match="duplicate node_id values: same"):
        validate_workflow(workflow)


def test_unknown_dependency_is_rejected() -> None:
    workflow = make_workflow(
        [make_node("intake"), make_node("validate", depends_on=["missing"])]
    )

    with pytest.raises(
        WorkflowValidationError,
        match="node 'validate' depends on unknown node 'missing'",
    ):
        validate_workflow(workflow)


def test_self_dependency_is_rejected() -> None:
    workflow = make_workflow([make_node("loop", depends_on=["loop"])])

    with pytest.raises(
        WorkflowValidationError,
        match="node 'loop' cannot depend on itself",
    ):
        validate_workflow(workflow)


def test_dependency_cycle_is_rejected() -> None:
    workflow = make_workflow(
        [
            make_node("alpha", depends_on=["beta"]),
            make_node("beta", depends_on=["alpha"]),
        ]
    )

    with pytest.raises(WorkflowValidationError, match="contains a cycle"):
        validate_workflow(workflow)
