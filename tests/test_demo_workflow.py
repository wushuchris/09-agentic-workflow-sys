import pytest

from src.demo_workflow import (
    build_onboarding_registry,
    build_onboarding_workflow,
    example_onboarding,
)
from src.executor import WorkflowExecutionError, execute_workflow, submit_human_decision
from src.persistence import InMemoryStateStore
from src.schemas import EventType, HumanDecision, NodeStatus, WorkflowStatus
from src.validator import validate_workflow


def test_demo_workflow_is_structurally_valid() -> None:
    workflow = build_onboarding_workflow()

    assert validate_workflow(workflow) is None
    assert workflow.workflow_id == "wealth-household-onboarding"
    assert workflow.version == "1.1"
    assert len(workflow.nodes) == 10


def test_straightforward_household_reaches_standard_ready_path() -> None:
    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=example_onboarding(household_id="HH-STANDARD"),
        run_id="demo-standard",
        state_store=InMemoryStateStore(),
    )

    assert run.status is WorkflowStatus.COMPLETED
    assert run.node_runs["create_onboarding_package"].attempt == 1
    assert run.node_runs["review_gate"].output == {
        "route": "STANDARD_PATH",
        "exception_reasons": [],
    }
    assert run.node_runs["onboarding_ready"].status is NodeStatus.COMPLETED
    assert run.node_runs["human_review"].status is NodeStatus.SKIPPED
    assert run.node_runs["reviewed_onboarding"].status is NodeStatus.SKIPPED
    assert run.final_output == {
        "onboarding_ready": {
            "outcome": "READY_FOR_ADVISOR_REVIEW",
            "review_path": "STANDARD",
        }
    }


def test_ai_capable_node_uses_deterministic_fallback_without_model() -> None:
    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=example_onboarding(household_id="HH-AI-FALLBACK"),
        run_id="demo-ai-fallback",
        state_store=InMemoryStateStore(),
    )

    ai_output = run.node_runs["ai_intake_organizer"].output
    package_output = run.node_runs["create_onboarding_package"].output

    assert ai_output["source"] == "DETERMINISTIC_FALLBACK"
    assert ai_output["profile_category"] == "STANDARD_HOUSEHOLD"
    assert "synthetic" in ai_output["summary"].lower()
    assert package_output["ai_profile_category"] == ai_output["profile_category"]
    assert package_output["ai_intake_summary"] == ai_output["summary"]
    assert package_output["ai_source"] == "DETERMINISTIC_FALLBACK"
    assert run.node_runs["verify_onboarding_package"].output["ai_summary_included"] is True


def test_live_ai_work_product_is_used_but_does_not_control_route() -> None:
    def fake_model(prompt: str) -> str:
        return (
            '{"profile_category":"COMPLEX_HOUSEHOLD",'
            '"summary":"AI sees nuance in the fictional notes."}'
        )

    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(onboarding_model=fake_model, model_label="example/model"),
        context=example_onboarding(
            household_id="HH-AI-NONAUTHORITATIVE",
            household_type="JOINT",
            documents_complete=True,
            identity_status="VERIFIED",
            relationship_complexity="STANDARD",
        ),
        run_id="demo-ai-nonauthoritative",
        state_store=InMemoryStateStore(),
    )

    ai_output = run.node_runs["ai_intake_organizer"].output
    package_output = run.node_runs["create_onboarding_package"].output

    assert ai_output["source"] == "MODEL_ASSISTED"
    assert ai_output["profile_category"] == "COMPLEX_HOUSEHOLD"
    assert ai_output["model_id"] == "example/model"
    assert package_output["ai_profile_category"] == "COMPLEX_HOUSEHOLD"
    assert run.node_runs["review_gate"].output == {
        "route": "STANDARD_PATH",
        "exception_reasons": [],
    }


def test_transient_failure_retries_once_then_recovers() -> None:
    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=example_onboarding(
            household_id="HH-TRANSIENT",
            simulation_mode="TRANSIENT_ONCE",
        ),
        run_id="demo-transient",
        state_store=InMemoryStateStore(),
    )

    package = run.node_runs["create_onboarding_package"]
    assert run.status is WorkflowStatus.COMPLETED
    assert package.status is NodeStatus.COMPLETED
    assert package.attempt == 2
    assert package.output["service_attempt"] == 2
    assert package.output["ai_intake_summary"]
    assert EventType.RETRY_SCHEDULED in [event.event_type for event in run.events]


def test_invalid_intake_fails_before_ai_or_package_preparation() -> None:
    onboarding = example_onboarding(household_id="HH-INVALID")
    onboarding["onboarding_notes"] = "   "

    with pytest.raises(WorkflowExecutionError, match="onboarding_notes must be a non-blank string") as exc_info:
        execute_workflow(
            build_onboarding_workflow(),
            build_onboarding_registry(),
            context=onboarding,
            run_id="demo-invalid",
            state_store=InMemoryStateStore(),
        )

    run = exc_info.value.run
    assert run.status is WorkflowStatus.FAILED
    assert run.node_runs["validate_intake"].status is NodeStatus.FAILED
    assert run.node_runs["ai_intake_organizer"].status is NodeStatus.PENDING
    assert run.node_runs["create_onboarding_package"].attempt == 0


def test_complex_trust_household_pauses_then_approval_completes() -> None:
    workflow = build_onboarding_workflow()
    registry = build_onboarding_registry()
    store = InMemoryStateStore()

    paused = execute_workflow(
        workflow,
        registry,
        context=example_onboarding(
            household_id="HH-EXCEPTION",
            household_type="TRUST",
            relationship_complexity="COMPLEX",
        ),
        run_id="demo-exception",
        state_store=store,
    )

    assert paused.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert paused.node_runs["review_gate"].output["route"] == "REVIEW_REQUIRED"
    assert "SPECIAL_STRUCTURE" in paused.node_runs["review_gate"].output["exception_reasons"]
    assert "COMPLEX_RELATIONSHIP" in paused.node_runs["review_gate"].output["exception_reasons"]
    assert paused.node_runs["onboarding_ready"].status is NodeStatus.SKIPPED
    assert paused.node_runs["human_review"].status is NodeStatus.WAITING_FOR_HUMAN
    assert paused.node_runs["reviewed_onboarding"].status is NodeStatus.PENDING
    assert len(paused.human_reviews) == 1

    completed = submit_human_decision(
        workflow,
        registry,
        run_id="demo-exception",
        review_id=paused.human_reviews[0].review_id,
        decision=HumanDecision.APPROVE,
        state_store=store,
    )

    assert completed.status is WorkflowStatus.COMPLETED
    assert completed.node_runs["human_review"].status is NodeStatus.COMPLETED
    assert completed.node_runs["reviewed_onboarding"].status is NodeStatus.COMPLETED
    assert completed.node_runs["validate_intake"].attempt == 1
    assert completed.node_runs["review_gate"].attempt == 1
    assert completed.final_output == {
        "reviewed_onboarding": {
            "outcome": "READY_AFTER_HUMAN_REVIEW",
            "review_path": "EXCEPTION_REVIEW",
        }
    }


def test_missing_documents_route_to_human_review() -> None:
    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=example_onboarding(
            household_id="HH-MISSING-DOCS",
            documents_complete=False,
        ),
        run_id="demo-missing-docs",
        state_store=InMemoryStateStore(),
    )

    assert run.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert run.node_runs["document_check"].output["status"] == "MISSING_ITEMS"
    assert "MISSING_DOCUMENTS" in run.node_runs["review_gate"].output["exception_reasons"]


def test_human_rejection_ends_as_rejected_not_failed() -> None:
    workflow = build_onboarding_workflow()
    registry = build_onboarding_registry()
    store = InMemoryStateStore()

    paused = execute_workflow(
        workflow,
        registry,
        context=example_onboarding(
            household_id="HH-REJECT",
            identity_status="REVIEW_REQUIRED",
        ),
        run_id="demo-reject",
        state_store=store,
    )

    rejected = submit_human_decision(
        workflow,
        registry,
        run_id="demo-reject",
        review_id=paused.human_reviews[0].review_id,
        decision=HumanDecision.REJECT,
        state_store=store,
    )

    assert rejected.status is WorkflowStatus.REJECTED
    assert rejected.node_runs["human_review"].status is NodeStatus.COMPLETED
    assert rejected.node_runs["reviewed_onboarding"].status is NodeStatus.PENDING
    assert EventType.HUMAN_REJECTED in [event.event_type for event in rejected.events]
    assert EventType.WORKFLOW_FAILED not in [event.event_type for event in rejected.events]


def test_permanent_failure_is_not_retried_even_though_node_allows_retries() -> None:
    with pytest.raises(WorkflowExecutionError, match="synthetic permanent onboarding service failure") as exc_info:
        execute_workflow(
            build_onboarding_workflow(),
            build_onboarding_registry(),
            context=example_onboarding(
                household_id="HH-PERMANENT",
                simulation_mode="PERMANENT",
            ),
            run_id="demo-permanent",
            state_store=InMemoryStateStore(),
        )

    run = exc_info.value.run
    package = run.node_runs["create_onboarding_package"]
    assert run.status is WorkflowStatus.FAILED
    assert package.status is NodeStatus.FAILED
    assert package.attempt == 1
    assert EventType.RETRY_SCHEDULED not in [event.event_type for event in run.events]
    assert run.node_runs["verify_onboarding_package"].status is NodeStatus.PENDING


def test_audit_log_does_not_copy_onboarding_notes_or_ai_summary() -> None:
    onboarding = example_onboarding(household_id="HH-PRIVACY")
    onboarding["onboarding_notes"] = "Synthetic but intentionally private-looking demo text."

    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=onboarding,
        run_id="demo-privacy",
        state_store=InMemoryStateStore(),
    )

    audit_text = repr([event.details for event in run.events])
    ai_summary = run.node_runs["ai_intake_organizer"].output["summary"]
    assert "Synthetic but intentionally private-looking demo text." not in audit_text
    assert ai_summary not in audit_text
