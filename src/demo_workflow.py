"""Public-safe service-request demo workflow for Agent 9.

The Controlled Service Request Workflow exercises the workflow runtime end to end
with deterministic simulated actions. Classification is deterministic by default
and can optionally be replaced by a bounded model-assisted classifier. All demo
inputs and outputs are synthetic.
"""

from __future__ import annotations

from typing import Any

from src.model_assist import ModelCall, classify_with_model
from src.registry import HandlerRegistry
from src.retry import RetryableHandlerError
from src.schemas import NodeDefinition, NodeType, RetryPolicy, WorkflowDefinition


ALLOWED_REQUEST_TYPES = {"ACCESS", "BILLING", "GENERAL"}
ALLOWED_PRIORITIES = {"LOW", "NORMAL", "HIGH"}
ALLOWED_RISK_LEVELS = {"LOW", "HIGH"}
ALLOWED_SIMULATION_MODES = {"NONE", "TRANSIENT_ONCE", "PERMANENT"}
MAX_AUTOMATED_COST = 5_000.0
HUMAN_REVIEW_COST = 1_000.0


def build_service_request_workflow() -> WorkflowDefinition:
    """Return the fixed workflow used by the public demo."""

    return WorkflowDefinition(
        workflow_id="controlled-service-request",
        name="Controlled Service Request Workflow",
        version="1.0",
        nodes=[
            NodeDefinition(
                node_id="validate_request",
                name="Validate Request",
                node_type=NodeType.TASK,
                handler="validate_request",
            ),
            NodeDefinition(
                node_id="classify_request",
                name="Classify Request",
                node_type=NodeType.TASK,
                handler="classify_request",
                depends_on=["validate_request"],
            ),
            NodeDefinition(
                node_id="policy_check",
                name="Policy Check",
                node_type=NodeType.TASK,
                handler="policy_check",
                depends_on=["classify_request"],
            ),
            NodeDefinition(
                node_id="perform_automated_task",
                name="Perform Automated Task",
                node_type=NodeType.TASK,
                handler="perform_automated_task",
                depends_on=["policy_check"],
                retry_policy=RetryPolicy(retryable=True, max_attempts=3),
            ),
            NodeDefinition(
                node_id="verify_result",
                name="Verify Result",
                node_type=NodeType.TASK,
                handler="verify_result",
                depends_on=["perform_automated_task"],
            ),
            NodeDefinition(
                node_id="risk_gate",
                name="Risk Gate",
                node_type=NodeType.DECISION,
                handler="risk_gate",
                depends_on=["verify_result"],
                routes={
                    "LOW_RISK": "low_risk_finalize",
                    "HIGH_RISK": "human_review",
                },
            ),
            NodeDefinition(
                node_id="low_risk_finalize",
                name="Low-Risk Finalize",
                node_type=NodeType.TASK,
                handler="low_risk_finalize",
                depends_on=["risk_gate"],
            ),
            NodeDefinition(
                node_id="human_review",
                name="Human Review",
                node_type=NodeType.HUMAN_GATE,
                depends_on=["risk_gate"],
                config={
                    "reason": "High-risk service request requires explicit human approval."
                },
            ),
            NodeDefinition(
                node_id="high_risk_finalize",
                name="High-Risk Finalize",
                node_type=NodeType.TASK,
                handler="high_risk_finalize",
                depends_on=["human_review"],
            ),
        ],
    )


def build_service_request_registry(
    *,
    classification_model: ModelCall | None = None,
) -> HandlerRegistry:
    """Return allowlisted handlers for the synthetic demo.

    When classification_model is omitted, classification remains deterministic.
    When supplied, only the classification handler delegates to the bounded model
    adapter; all workflow control and all other handlers remain deterministic.

    The simulated automated-task handler keeps per-request attempt counters only so
    the TRANSIENT_ONCE demo mode can deterministically fail once and then recover.
    It never calls an external service or performs a real side effect.
    """

    registry = HandlerRegistry()
    automated_attempts: dict[str, int] = {}

    def validate_request(payload: dict[str, Any]) -> dict[str, Any]:
        context = payload["context"]
        required_strings = (
            "request_id",
            "request_type",
            "description",
            "priority",
            "risk_level",
        )
        normalized: dict[str, Any] = {}

        for field in required_strings:
            value = context.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-blank string")
            normalized[field] = value.strip()

        normalized["request_type"] = normalized["request_type"].upper()
        normalized["priority"] = normalized["priority"].upper()
        normalized["risk_level"] = normalized["risk_level"].upper()

        if normalized["request_type"] not in ALLOWED_REQUEST_TYPES:
            raise ValueError(
                f"request_type must be one of: {', '.join(sorted(ALLOWED_REQUEST_TYPES))}"
            )
        if normalized["priority"] not in ALLOWED_PRIORITIES:
            raise ValueError(
                f"priority must be one of: {', '.join(sorted(ALLOWED_PRIORITIES))}"
            )
        if normalized["risk_level"] not in ALLOWED_RISK_LEVELS:
            raise ValueError(
                f"risk_level must be one of: {', '.join(sorted(ALLOWED_RISK_LEVELS))}"
            )

        estimated_cost = context.get("estimated_cost")
        if isinstance(estimated_cost, bool) or not isinstance(estimated_cost, (int, float)):
            raise ValueError("estimated_cost must be a non-negative number")
        if estimated_cost < 0:
            raise ValueError("estimated_cost must be a non-negative number")
        normalized["estimated_cost"] = float(estimated_cost)

        simulation_mode = context.get("simulation_mode", "NONE")
        if not isinstance(simulation_mode, str):
            raise ValueError("simulation_mode must be a string")
        simulation_mode = simulation_mode.strip().upper()
        if simulation_mode not in ALLOWED_SIMULATION_MODES:
            raise ValueError(
                "simulation_mode must be one of: "
                + ", ".join(sorted(ALLOWED_SIMULATION_MODES))
            )
        normalized["simulation_mode"] = simulation_mode
        normalized["supporting_info_present"] = bool(context.get("supporting_info"))
        return normalized

    def classify_request(payload: dict[str, Any]) -> dict[str, Any]:
        validated = payload["dependencies"]["validate_request"]

        if classification_model is not None:
            proposal = classify_with_model(
                classification_model,
                request_type=validated["request_type"],
                description=validated["description"],
            )
            return {
                **proposal,
                "priority": validated["priority"],
            }

        classification_by_type = {
            "ACCESS": "ACCESS_REQUEST",
            "BILLING": "BILLING_REQUEST",
            "GENERAL": "GENERAL_SERVICE_REQUEST",
        }
        return {
            "classification": classification_by_type[validated["request_type"]],
            "priority": validated["priority"],
            "source": "DETERMINISTIC",
        }

    def policy_check(payload: dict[str, Any]) -> dict[str, Any]:
        validated = payload["dependencies"]["classify_request"]
        request = payload["context"]
        estimated_cost = float(request["estimated_cost"])
        if estimated_cost > MAX_AUTOMATED_COST:
            raise RuntimeError(
                f"estimated cost exceeds automated policy limit of {MAX_AUTOMATED_COST:.0f}"
            )
        return {
            "allowed": True,
            "classification": validated["classification"],
            "policy_limit": MAX_AUTOMATED_COST,
        }

    def perform_automated_task(payload: dict[str, Any]) -> dict[str, Any]:
        context = payload["context"]
        request_id = str(context["request_id"]).strip()
        simulation_mode = str(context.get("simulation_mode", "NONE")).strip().upper()
        attempt = automated_attempts.get(request_id, 0) + 1
        automated_attempts[request_id] = attempt

        if simulation_mode == "TRANSIENT_ONCE" and attempt == 1:
            raise RetryableHandlerError("synthetic temporary service interruption")
        if simulation_mode == "PERMANENT":
            raise RuntimeError("synthetic permanent service failure")

        return {
            "action": "SIMULATED_SERVICE_ACTION",
            "status": "SUCCESS",
            "service_attempt": attempt,
        }

    def verify_result(payload: dict[str, Any]) -> dict[str, Any]:
        result = payload["dependencies"]["perform_automated_task"]
        if result.get("status") != "SUCCESS":
            raise RuntimeError("automated task result failed verification")
        return {
            "verified": True,
            "action": result["action"],
        }

    def risk_gate(payload: dict[str, Any]) -> dict[str, Any]:
        context = payload["context"]
        risk_level = str(context["risk_level"]).strip().upper()
        estimated_cost = float(context["estimated_cost"])
        priority = str(context["priority"]).strip().upper()

        requires_human = (
            risk_level == "HIGH"
            or estimated_cost >= HUMAN_REVIEW_COST
            or (priority == "HIGH" and estimated_cost >= 500.0)
        )
        return {
            "route": "HIGH_RISK" if requires_human else "LOW_RISK",
            "risk_level": risk_level,
        }

    def low_risk_finalize(payload: dict[str, Any]) -> dict[str, Any]:
        decision = payload["dependencies"]["risk_gate"]
        if decision.get("route") != "LOW_RISK":
            raise RuntimeError("low-risk finalizer received the wrong route")
        return {
            "outcome": "AUTO_FINALIZED",
            "approved_by": "WORKFLOW_POLICY",
        }

    def high_risk_finalize(payload: dict[str, Any]) -> dict[str, Any]:
        review = payload["dependencies"]["human_review"]
        if review.get("decision") != "APPROVE":
            raise RuntimeError("high-risk finalizer requires human approval")
        return {
            "outcome": "HUMAN_APPROVED_FINALIZATION",
            "approved_by": "HUMAN_REVIEW",
        }

    registry.register("validate_request", validate_request)
    registry.register("classify_request", classify_request)
    registry.register("policy_check", policy_check)
    registry.register("perform_automated_task", perform_automated_task)
    registry.register("verify_result", verify_result)
    registry.register("risk_gate", risk_gate)
    registry.register("low_risk_finalize", low_risk_finalize)
    registry.register("high_risk_finalize", high_risk_finalize)
    return registry


def example_request(
    *,
    request_id: str = "REQ-DEMO-001",
    risk_level: str = "LOW",
    estimated_cost: float = 125.0,
    priority: str = "NORMAL",
    simulation_mode: str = "NONE",
) -> dict[str, Any]:
    """Return one public-safe synthetic request suitable for demos and tests."""

    return {
        "request_id": request_id,
        "request_type": "ACCESS",
        "description": "Provision synthetic access for a fictional demo user.",
        "priority": priority,
        "risk_level": risk_level,
        "estimated_cost": estimated_cost,
        "supporting_info": {"source": "synthetic-demo"},
        "simulation_mode": simulation_mode,
    }
