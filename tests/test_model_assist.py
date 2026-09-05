import pytest

from src.demo_workflow import (
    build_onboarding_registry,
    build_onboarding_workflow,
    example_onboarding,
)
from src.executor import WorkflowExecutionError, execute_workflow
from src.model_assist import (
    ModelOnboardingError,
    build_onboarding_prompt,
    organize_onboarding_with_model,
)
from src.persistence import InMemoryStateStore
from src.schemas import NodeStatus, WorkflowStatus


def test_onboarding_prompt_contains_only_bounded_ai_inputs() -> None:
    prompt = build_onboarding_prompt(
        household_type="JOINT",
        onboarding_notes="Synthetic household intake notes.",
    )

    assert "household_type: JOINT" in prompt
    assert "onboarding_notes: Synthetic household intake notes." in prompt
    assert "documents_complete" not in prompt
    assert "identity_status" not in prompt
    assert "relationship_complexity" not in prompt
    assert "handler" not in prompt
    assert "retry" not in prompt.lower()
    assert "workflow state" not in prompt.lower()


def test_valid_model_json_is_normalized_to_bounded_onboarding_proposal() -> None:
    def fake_model(prompt: str) -> str:
        return (
            '{"profile_category":"STANDARD_HOUSEHOLD",'
            '"summary":"Synthetic household appears straightforward."}'
        )

    result = organize_onboarding_with_model(
        fake_model,
        household_type="JOINT",
        onboarding_notes="Synthetic intake notes.",
    )

    assert result == {
        "profile_category": "STANDARD_HOUSEHOLD",
        "summary": "Synthetic household appears straightforward.",
        "source": "MODEL_ASSISTED",
    }


@pytest.mark.parametrize(
    "response",
    [
        "not-json",
        '{"profile_category":"UNAPPROVED","summary":"invented class"}',
        '{"profile_category":"STANDARD_HOUSEHOLD","summary":"ok","route":"REVIEW_REQUIRED"}',
        '{"profile_category":"STANDARD_HOUSEHOLD"}',
        "",
    ],
)
def test_malformed_or_unapproved_model_outputs_are_rejected(response: str) -> None:
    def fake_model(prompt: str) -> str:
        return response

    with pytest.raises(ModelOnboardingError):
        organize_onboarding_with_model(
            fake_model,
            household_type="JOINT",
            onboarding_notes="Synthetic intake notes.",
        )


def test_model_call_failure_is_sanitized() -> None:
    def failing_model(prompt: str) -> str:
        raise RuntimeError("provider-secret-detail-should-not-leak")

    with pytest.raises(ModelOnboardingError, match="model onboarding call failed") as exc_info:
        organize_onboarding_with_model(
            failing_model,
            household_type="JOINT",
            onboarding_notes="Synthetic intake notes.",
        )

    assert "provider-secret-detail-should-not-leak" not in str(exc_info.value)


def test_model_assisted_intake_completes_without_controlling_routing() -> None:
    prompts: list[str] = []

    def fake_model(prompt: str) -> str:
        prompts.append(prompt)
        return (
            '{"profile_category":"STANDARD_HOUSEHOLD",'
            '"summary":"A bounded model organized the synthetic intake."}'
        )

    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(onboarding_model=fake_model),
        context=example_onboarding(household_id="HH-MODEL-VALID"),
        run_id="model-valid",
        state_store=InMemoryStateStore(),
    )

    assert run.status is WorkflowStatus.COMPLETED
    proposal = run.node_runs["ai_intake_organizer"].output
    assert proposal == {
        "profile_category": "STANDARD_HOUSEHOLD",
        "summary": "A bounded model organized the synthetic intake.",
        "source": "MODEL_ASSISTED",
    }
    assert run.node_runs["review_gate"].output["route"] == "STANDARD_PATH"
    assert run.node_runs["onboarding_ready"].status is NodeStatus.COMPLETED
    assert len(prompts) == 1
    assert "documents_complete" not in prompts[0]
    assert "identity_status" not in prompts[0]


def test_model_cannot_inject_route_handler_or_approval_fields() -> None:
    malicious_marker = "MODEL_TRIED_TO_CONTROL_WORKFLOW"

    def malicious_model(prompt: str) -> str:
        return (
            '{"profile_category":"STANDARD_HOUSEHOLD",'
            '"summary":"' + malicious_marker + '",'
            '"route":"REVIEW_REQUIRED",'
            '"handler":"arbitrary_handler",'
            '"decision":"APPROVE"}'
        )

    with pytest.raises(
        WorkflowExecutionError,
        match="model onboarding output failed schema validation",
    ) as exc_info:
        execute_workflow(
            build_onboarding_workflow(),
            build_onboarding_registry(onboarding_model=malicious_model),
            context=example_onboarding(household_id="HH-MODEL-INJECT"),
            run_id="model-inject",
            state_store=InMemoryStateStore(),
        )

    run = exc_info.value.run
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["ai_intake_organizer"].status is NodeStatus.FAILED
    assert run.node_runs["document_check"].status is NodeStatus.PENDING
    assert run.node_runs["review_gate"].status is NodeStatus.PENDING

    audit_text = repr([event.details for event in run.events])
    assert malicious_marker not in audit_text
    assert "arbitrary_handler" not in audit_text


def test_provider_exception_details_do_not_enter_audit_log() -> None:
    secret_marker = "SYNTHETIC_PROVIDER_SECRET_DETAIL"

    def failing_model(prompt: str) -> str:
        raise RuntimeError(secret_marker)

    with pytest.raises(WorkflowExecutionError) as exc_info:
        execute_workflow(
            build_onboarding_workflow(),
            build_onboarding_registry(onboarding_model=failing_model),
            context=example_onboarding(household_id="HH-MODEL-PROVIDER-FAIL"),
            run_id="model-provider-fail",
            state_store=InMemoryStateStore(),
        )

    audit_text = repr([event.details for event in exc_info.value.run.events])
    assert secret_marker not in audit_text
    assert "model onboarding call failed" in audit_text


def test_deterministic_fallback_remains_default_without_provider() -> None:
    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=example_onboarding(household_id="HH-DETERMINISTIC-DEFAULT"),
        run_id="deterministic-default",
        state_store=InMemoryStateStore(),
    )

    assert run.status is WorkflowStatus.COMPLETED
    assert run.node_runs["ai_intake_organizer"].output["source"] == "DETERMINISTIC_FALLBACK"
