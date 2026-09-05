"""Public-safe wealth-management onboarding demo for Agent 9.

The fictional Household Onboarding Workflow exercises the workflow runtime end to end
with deterministic simulated actions. AI assistance is optional and bounded to intake
organization; workflow control, exception routing, retries, persistence, and human
approval remain deterministic. All households, notes, and outputs are synthetic.
"""

from __future__ import annotations

from typing import Any

from src.model_assist import ModelCall, organize_onboarding_with_model
from src.registry import HandlerRegistry
from src.retry import RetryableHandlerError
from src.schemas import NodeDefinition, NodeType, RetryPolicy, WorkflowDefinition


ALLOWED_HOUSEHOLD_TYPES = {"INDIVIDUAL", "JOINT", "TRUST", "ENTITY"}
ALLOWED_IDENTITY_STATUSES = {"VERIFIED", "REVIEW_REQUIRED"}
ALLOWED_COMPLEXITY_LEVELS = {"STANDARD", "COMPLEX"}
ALLOWED_SIMULATION_MODES = {"NONE", "TRANSIENT_ONCE", "PERMANENT"}
SPECIAL_STRUCTURE_TYPES = {"TRUST", "ENTITY"}


def build_onboarding_workflow() -> WorkflowDefinition:
    """Return the fixed fictional household-onboarding workflow used by the public demo."""

    return WorkflowDefinition(
        workflow_id="wealth-household-onboarding",
        name="Fictional Wealth Management Household Onboarding",
        version="1.0",
        nodes=[
            NodeDefinition(
                node_id="validate_intake",
                name="Validate Intake",
                node_type=NodeType.TASK,
                handler="validate_intake",
            ),
            NodeDefinition(
                node_id="ai_intake_organizer",
                name="AI Intake Organizer",
                node_type=NodeType.TASK,
                handler="ai_intake_organizer",
                depends_on=["validate_intake"],
            ),
            NodeDefinition(
                node_id="document_check",
                name="Document Check",
                node_type=NodeType.TASK,
                handler="document_check",
                depends_on=["ai_intake_organizer"],
            ),
            NodeDefinition(
                node_id="policy_check",
                name="Onboarding Policy Check",
                node_type=NodeType.TASK,
                handler="policy_check",
                depends_on=["document_check"],
            ),
            NodeDefinition(
                node_id="create_onboarding_package",
                name="Create Onboarding Package",
                node_type=NodeType.TASK,
                handler="create_onboarding_package",
                depends_on=["policy_check"],
                retry_policy=RetryPolicy(retryable=True, max_attempts=3),
            ),
            NodeDefinition(
                node_id="verify_onboarding_package",
                name="Verify Onboarding Package",
                node_type=NodeType.TASK,
                handler="verify_onboarding_package",
                depends_on=["create_onboarding_package"],
            ),
            NodeDefinition(
                node_id="review_gate",
                name="Review Gate",
                node_type=NodeType.DECISION,
                handler="review_gate",
                depends_on=["verify_onboarding_package", "policy_check"],
                routes={
                    "STANDARD_PATH": "onboarding_ready",
                    "REVIEW_REQUIRED": "human_review",
                },
            ),
            NodeDefinition(
                node_id="onboarding_ready",
                name="Standard Onboarding Ready",
                node_type=NodeType.TASK,
                handler="onboarding_ready",
                depends_on=["review_gate"],
            ),
            NodeDefinition(
                node_id="human_review",
                name="Operations / Compliance Review",
                node_type=NodeType.HUMAN_GATE,
                depends_on=["review_gate"],
                config={
                    "reason": (
                        "A fictional onboarding exception requires explicit operations or "
                        "compliance review before the package can be marked ready."
                    )
                },
            ),
            NodeDefinition(
                node_id="reviewed_onboarding",
                name="Reviewed Onboarding Ready",
                node_type=NodeType.TASK,
                handler="reviewed_onboarding",
                depends_on=["human_review"],
            ),
        ],
    )


def build_onboarding_registry(
    *,
    onboarding_model: ModelCall | None = None,
) -> HandlerRegistry:
    """Return allowlisted handlers for the fictional onboarding demo.

    When onboarding_model is omitted, the AI-capable intake step uses a deterministic
    fallback so the public demo works without credentials. When a model callable is
    supplied, only the intake-organizer handler delegates to the bounded model adapter;
    all workflow control and all other handlers remain deterministic.
    """

    registry = HandlerRegistry()
    package_attempts: dict[str, int] = {}

    def validate_intake(payload: dict[str, Any]) -> dict[str, Any]:
        context = payload["context"]
        required_strings = (
            "household_id",
            "household_type",
            "onboarding_notes",
            "identity_status",
            "relationship_complexity",
        )
        normalized: dict[str, Any] = {}

        for field in required_strings:
            value = context.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-blank string")
            normalized[field] = value.strip()

        normalized["household_type"] = normalized["household_type"].upper()
        normalized["identity_status"] = normalized["identity_status"].upper()
        normalized["relationship_complexity"] = normalized[
            "relationship_complexity"
        ].upper()

        if normalized["household_type"] not in ALLOWED_HOUSEHOLD_TYPES:
            raise ValueError(
                "household_type must be one of: "
                + ", ".join(sorted(ALLOWED_HOUSEHOLD_TYPES))
            )
        if normalized["identity_status"] not in ALLOWED_IDENTITY_STATUSES:
            raise ValueError(
                "identity_status must be one of: "
                + ", ".join(sorted(ALLOWED_IDENTITY_STATUSES))
            )
        if normalized["relationship_complexity"] not in ALLOWED_COMPLEXITY_LEVELS:
            raise ValueError(
                "relationship_complexity must be one of: "
                + ", ".join(sorted(ALLOWED_COMPLEXITY_LEVELS))
            )

        documents_complete = context.get("documents_complete")
        if not isinstance(documents_complete, bool):
            raise ValueError("documents_complete must be a boolean")
        normalized["documents_complete"] = documents_complete

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
        return normalized

    def ai_intake_organizer(payload: dict[str, Any]) -> dict[str, Any]:
        intake = payload["dependencies"]["validate_intake"]

        if onboarding_model is not None:
            return organize_onboarding_with_model(
                onboarding_model,
                household_type=intake["household_type"],
                onboarding_notes=intake["onboarding_notes"],
            )

        household_type = intake["household_type"]
        if household_type in SPECIAL_STRUCTURE_TYPES:
            profile_category = "SPECIAL_STRUCTURE"
        else:
            profile_category = "STANDARD_HOUSEHOLD"
        return {
            "profile_category": profile_category,
            "summary": (
                f"Synthetic {household_type.lower()} household intake organized for "
                "fictional onboarding review."
            ),
            "source": "DETERMINISTIC_FALLBACK",
        }

    def document_check(payload: dict[str, Any]) -> dict[str, Any]:
        documents_complete = payload["context"]["documents_complete"]
        return {
            "documents_complete": documents_complete,
            "status": "COMPLETE" if documents_complete else "MISSING_ITEMS",
        }

    def policy_check(payload: dict[str, Any]) -> dict[str, Any]:
        context = payload["context"]
        documents = payload["dependencies"]["document_check"]
        exceptions: list[str] = []

        if not documents["documents_complete"]:
            exceptions.append("MISSING_DOCUMENTS")
        if str(context["identity_status"]).strip().upper() == "REVIEW_REQUIRED":
            exceptions.append("IDENTITY_REVIEW_REQUIRED")
        if str(context["relationship_complexity"]).strip().upper() == "COMPLEX":
            exceptions.append("COMPLEX_RELATIONSHIP")
        if str(context["household_type"]).strip().upper() in SPECIAL_STRUCTURE_TYPES:
            exceptions.append("SPECIAL_STRUCTURE")

        return {
            "eligible_to_prepare_package": True,
            "exception_reasons": exceptions,
        }

    def create_onboarding_package(payload: dict[str, Any]) -> dict[str, Any]:
        context = payload["context"]
        household_id = str(context["household_id"]).strip()
        simulation_mode = str(context.get("simulation_mode", "NONE")).strip().upper()
        attempt = package_attempts.get(household_id, 0) + 1
        package_attempts[household_id] = attempt

        if simulation_mode == "TRANSIENT_ONCE" and attempt == 1:
            raise RetryableHandlerError("synthetic temporary onboarding service interruption")
        if simulation_mode == "PERMANENT":
            raise RuntimeError("synthetic permanent onboarding service failure")

        return {
            "package_status": "PREPARED",
            "service_attempt": attempt,
            "action": "SIMULATED_ONBOARDING_PACKAGE_PREPARATION",
        }

    def verify_onboarding_package(payload: dict[str, Any]) -> dict[str, Any]:
        package = payload["dependencies"]["create_onboarding_package"]
        if package.get("package_status") != "PREPARED":
            raise RuntimeError("onboarding package failed verification")
        return {
            "verified": True,
            "action": package["action"],
        }

    def review_gate(payload: dict[str, Any]) -> dict[str, Any]:
        policy = payload["dependencies"]["policy_check"]
        reasons = list(policy["exception_reasons"])
        return {
            "route": "REVIEW_REQUIRED" if reasons else "STANDARD_PATH",
            "exception_reasons": reasons,
        }

    def onboarding_ready(payload: dict[str, Any]) -> dict[str, Any]:
        decision = payload["dependencies"]["review_gate"]
        if decision.get("route") != "STANDARD_PATH":
            raise RuntimeError("standard onboarding finalizer received the wrong route")
        return {
            "outcome": "READY_FOR_ADVISOR_REVIEW",
            "review_path": "STANDARD",
        }

    def reviewed_onboarding(payload: dict[str, Any]) -> dict[str, Any]:
        review = payload["dependencies"]["human_review"]
        if review.get("decision") != "APPROVE":
            raise RuntimeError("reviewed onboarding requires explicit human approval")
        return {
            "outcome": "READY_AFTER_HUMAN_REVIEW",
            "review_path": "EXCEPTION_REVIEW",
        }

    registry.register("validate_intake", validate_intake)
    registry.register("ai_intake_organizer", ai_intake_organizer)
    registry.register("document_check", document_check)
    registry.register("policy_check", policy_check)
    registry.register("create_onboarding_package", create_onboarding_package)
    registry.register("verify_onboarding_package", verify_onboarding_package)
    registry.register("review_gate", review_gate)
    registry.register("onboarding_ready", onboarding_ready)
    registry.register("reviewed_onboarding", reviewed_onboarding)
    return registry


def example_onboarding(
    *,
    household_id: str = "HH-DEMO-001",
    household_type: str = "JOINT",
    onboarding_notes: str = (
        "Fictional household seeking a standard advisory relationship. "
        "All intake information in this demo is synthetic."
    ),
    documents_complete: bool = True,
    identity_status: str = "VERIFIED",
    relationship_complexity: str = "STANDARD",
    simulation_mode: str = "NONE",
) -> dict[str, Any]:
    """Return one public-safe synthetic household suitable for demos and tests."""

    return {
        "household_id": household_id,
        "household_type": household_type,
        "onboarding_notes": onboarding_notes,
        "documents_complete": documents_complete,
        "identity_status": identity_status,
        "relationship_complexity": relationship_complexity,
        "simulation_mode": simulation_mode,
    }


# Backward-compatible aliases keep older internal imports from breaking during the
# incremental migration. Public documentation and the Gradio app use onboarding names.
build_service_request_workflow = build_onboarding_workflow
build_service_request_registry = build_onboarding_registry
example_request = example_onboarding
