import pytest

from src.demo_workflow import (
    build_service_request_registry,
    build_service_request_workflow,
    example_request,
)
from src.executor import WorkflowExecutionError, execute_workflow
from src.model_assist import (
    ModelClassificationError,
    build_classification_prompt,
    classify_with_model,
)
from src.persistence import InMemoryStateStore
from src.schemas import NodeStatus, WorkflowStatus


def test_classification_prompt_contains_only_bounded_business_inputs() -> None:
    prompt = build_classification_prompt(
        request_type="ACCESS",
        description="Synthetic access request.",
    )

    assert "request_type: ACCESS" in prompt
    assert "description: Synthetic access request." in prompt
    assert "risk_level" not in prompt
    assert "estimated_cost" not in prompt
    assert "handler" not in prompt
    assert "retry" not in prompt.lower()
    assert "human" not in prompt.lower()


def test_valid_model_json_is_normalized_to_bounded_classification() -> None:
    def fake_model(prompt: str) -> str:
        return (
            '{"classification":"ACCESS_REQUEST",'
            '"rationale":"The description asks for access."}'
        )

    result = classify_with_model(
        fake_model,
        request_type="ACCESS",
        description="Provision synthetic access.",
    )

    assert result == {
        "classification": "ACCESS_REQUEST",
        "rationale": "The description asks for access.",
        "source": "MODEL_ASSISTED",
    }


@pytest.mark.parametrize(
    "response",
    [
        "not-json",
        '{"classification":"UNAPPROVED","rationale":"invented class"}',
        '{"classification":"ACCESS_REQUEST","rationale":"ok","route":"HIGH_RISK"}',
        '{"classification":"ACCESS_REQUEST"}',
        "",
    ],
)
def test_malformed_or_unapproved_model_outputs_are_rejected(response: str) -> None:
    def fake_model(prompt: str) -> str:
        return response

    with pytest.raises(ModelClassificationError):
        classify_with_model(
            fake_model,
            request_type="ACCESS",
            description="Synthetic access request.",
        )


def test_model_call_failure_is_sanitized() -> None:
    def failing_model(prompt: str) -> str:
        raise RuntimeError("provider-secret-detail-should-not-leak")

    with pytest.raises(ModelClassificationError, match="model classification call failed") as exc_info:
        classify_with_model(
            failing_model,
            request_type="ACCESS",
            description="Synthetic access request.",
        )

    assert "provider-secret-detail-should-not-leak" not in str(exc_info.value)


def test_model_assisted_classifier_completes_workflow_without_controlling_routing() -> None:
    prompts: list[str] = []

    def fake_model(prompt: str) -> str:
        prompts.append(prompt)
        return (
            '{"classification":"ACCESS_REQUEST",'
            '"rationale":"This is an access request."}'
        )

    run = execute_workflow(
        build_service_request_workflow(),
        build_service_request_registry(classification_model=fake_model),
        context=example_request(request_id="REQ-MODEL-VALID"),
        run_id="model-valid",
        state_store=InMemoryStateStore(),
    )

    assert run.status is WorkflowStatus.COMPLETED
    classification = run.node_runs["classify_request"].output
    assert classification == {
        "classification": "ACCESS_REQUEST",
        "rationale": "This is an access request.",
        "source": "MODEL_ASSISTED",
        "priority": "NORMAL",
    }
    assert run.node_runs["risk_gate"].output["route"] == "LOW_RISK"
    assert run.node_runs["low_risk_finalize"].status is NodeStatus.COMPLETED
    assert len(prompts) == 1
    assert "estimated_cost" not in prompts[0]
    assert "risk_level" not in prompts[0]


def test_model_cannot_inject_route_or_handler_fields_into_workflow() -> None:
    malicious_marker = "MODEL_TRIED_TO_CONTROL_WORKFLOW"

    def malicious_model(prompt: str) -> str:
        return (
            '{"classification":"ACCESS_REQUEST",'
            '"rationale":"' + malicious_marker + '",'
            '"route":"HIGH_RISK",'
            '"handler":"arbitrary_handler"}'
        )

    with pytest.raises(
        WorkflowExecutionError,
        match="model classification output failed schema validation",
    ) as exc_info:
        execute_workflow(
            build_service_request_workflow(),
            build_service_request_registry(classification_model=malicious_model),
            context=example_request(request_id="REQ-MODEL-INJECT"),
            run_id="model-inject",
            state_store=InMemoryStateStore(),
        )

    run = exc_info.value.run
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["classify_request"].status is NodeStatus.FAILED
    assert run.node_runs["policy_check"].status is NodeStatus.PENDING
    assert run.node_runs["risk_gate"].status is NodeStatus.PENDING

    audit_text = repr([event.details for event in run.events])
    assert malicious_marker not in audit_text
    assert "arbitrary_handler" not in audit_text


def test_provider_exception_details_do_not_enter_audit_log() -> None:
    secret_marker = "SYNTHETIC_PROVIDER_SECRET_DETAIL"

    def failing_model(prompt: str) -> str:
        raise RuntimeError(secret_marker)

    with pytest.raises(WorkflowExecutionError) as exc_info:
        execute_workflow(
            build_service_request_workflow(),
            build_service_request_registry(classification_model=failing_model),
            context=example_request(request_id="REQ-MODEL-PROVIDER-FAIL"),
            run_id="model-provider-fail",
            state_store=InMemoryStateStore(),
        )

    audit_text = repr([event.details for event in exc_info.value.run.events])
    assert secret_marker not in audit_text
    assert "model classification call failed" in audit_text


def test_deterministic_classifier_remains_default() -> None:
    run = execute_workflow(
        build_service_request_workflow(),
        build_service_request_registry(),
        context=example_request(request_id="REQ-DETERMINISTIC-DEFAULT"),
        run_id="deterministic-default",
        state_store=InMemoryStateStore(),
    )

    assert run.status is WorkflowStatus.COMPLETED
    assert run.node_runs["classify_request"].output["source"] == "DETERMINISTIC"
