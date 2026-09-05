from src.demo_workflow import (
    build_onboarding_registry,
    build_onboarding_workflow,
    example_onboarding,
)
from src.evaluation import run_evaluation_suite
from src.executor import execute_workflow, submit_human_decision
from src.persistence import InMemoryStateStore
from src.schemas import HumanDecision, WorkflowStatus
from src.ui_presenters import (
    ai_insight_html,
    business_journey_html,
    business_outcome_html,
    evaluation_case_rows,
    evaluation_metric_rows,
    event_rows,
    review_rows,
    routing_explanation_html,
    run_bundle,
    run_summary,
    workflow_path_html,
)


def test_run_bundle_exposes_runtime_views_without_onboarding_context_in_events() -> None:
    onboarding = example_onboarding(household_id="UI-PRESENTER")
    onboarding["onboarding_notes"] = "SYNTHETIC_CONTEXT_MARKER"

    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=onboarding,
        run_id="ui-presenter-run",
        state_store=InMemoryStateStore(),
    )

    summary, run_id, nodes, events, reviews, final_output = run_bundle(run)

    assert run.status is WorkflowStatus.COMPLETED
    assert run_id == "ui-presenter-run"
    assert "COMPLETED" in summary
    assert nodes
    assert events
    assert reviews == []
    assert final_output["onboarding_ready"]["outcome"] == "READY_FOR_ADVISOR_REVIEW"
    assert "SYNTHETIC_CONTEXT_MARKER" not in repr(events)


def test_standard_path_presenters_explain_ai_and_code_roles() -> None:
    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=example_onboarding(household_id="UI-BUSINESS-STANDARD"),
        run_id="ui-business-standard-run",
        state_store=InMemoryStateStore(),
    )

    outcome = business_outcome_html(run)
    journey = business_journey_html(run)
    ai_panel = ai_insight_html(run)
    why_panel = routing_explanation_html(run)
    path = workflow_path_html(run)

    assert "ready for advisor review" in outcome.lower()
    assert "AI Intake Organizer" in journey
    assert "deterministic fallback" in journey.lower()
    assert "Standard package ready" in journey
    assert "DETERMINISTIC FALLBACK" in ai_panel
    assert "included in the simulated onboarding package" in ai_panel
    assert "Standard path selected by code" in why_panel
    assert "did <strong>not</strong> choose this route" in why_panel
    assert "Live workflow path" in path
    assert "map-node-ai" in path
    assert "map-node-completed" in path


def test_live_model_presenter_labels_model_without_granting_routing_authority() -> None:
    def fake_model(prompt: str) -> str:
        return (
            '{"profile_category":"STANDARD_HOUSEHOLD",'
            '"summary":"Live model organized this fictional intake."}'
        )

    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(
            onboarding_model=fake_model,
            model_label="example/live-model",
        ),
        context=example_onboarding(household_id="UI-LIVE-MODEL"),
        run_id="ui-live-model-run",
        state_store=InMemoryStateStore(),
    )

    ai_panel = ai_insight_html(run)
    why_panel = routing_explanation_html(run)

    assert "LIVE HUGGING FACE MODEL" in ai_panel
    assert "example/live-model" in ai_panel
    assert "Live model organized this fictional intake." in ai_panel
    assert "AI did not decide" in ai_panel
    assert "Standard path selected by code" in why_panel


def test_business_presenters_explain_retry_recovery_without_raw_errors() -> None:
    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=example_onboarding(
            household_id="UI-BUSINESS-RETRY",
            simulation_mode="TRANSIENT_ONCE",
        ),
        run_id="ui-business-retry-run",
        state_store=InMemoryStateStore(),
    )

    outcome = business_outcome_html(run)
    journey = business_journey_html(run)

    assert run.node_runs["create_onboarding_package"].attempt == 2
    assert "temporary onboarding-service problem" in outcome.lower()
    assert "Recovered on attempt 2" in journey
    assert "synthetic temporary onboarding service interruption" not in outcome


def test_waiting_human_presenters_explain_exact_deterministic_reasons() -> None:
    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=example_onboarding(
            household_id="UI-HUMAN",
            household_type="TRUST",
            relationship_complexity="COMPLEX",
        ),
        run_id="ui-human-run",
        state_store=InMemoryStateStore(),
    )

    assert run.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert "Action required" in run_summary(run)
    assert "needs a person" in business_outcome_html(run)
    assert "Waiting for a person" in business_journey_html(run)

    why_panel = routing_explanation_html(run)
    assert "Human review required by deterministic rules" in why_panel
    assert "Trust or entity structure" in why_panel
    assert "Relationship marked complex" in why_panel
    assert "not from the AI-generated summary" in why_panel

    path = workflow_path_html(run)
    assert "map-node-waiting-for-human" in path
    assert "map-node-skipped" in path

    rows = review_rows(run)
    assert len(rows) == 1
    assert rows[0][1] == "human_review"
    assert rows[0][2] == "OPEN"
    assert "operations or compliance review" in rows[0][3]


def test_business_presenter_explains_human_approved_completion() -> None:
    workflow = build_onboarding_workflow()
    store = InMemoryStateStore()
    run = execute_workflow(
        workflow,
        build_onboarding_registry(),
        context=example_onboarding(
            household_id="UI-HUMAN-APPROVED",
            household_type="TRUST",
            relationship_complexity="COMPLEX",
        ),
        run_id="ui-human-approved-run",
        state_store=store,
    )
    review = run.human_reviews[0]

    completed = submit_human_decision(
        workflow,
        build_onboarding_registry(),
        run_id=run.run_id,
        review_id=review.review_id,
        decision=HumanDecision.APPROVE,
        state_store=store,
    )

    assert completed.status is WorkflowStatus.COMPLETED
    assert "ready after human review" in business_outcome_html(completed).lower()
    assert "Approved by a person" in business_journey_html(completed)
    assert "map-node-completed" in workflow_path_html(completed)


def test_event_rows_preserve_append_only_event_order() -> None:
    run = execute_workflow(
        build_onboarding_workflow(),
        build_onboarding_registry(),
        context=example_onboarding(household_id="UI-EVENTS"),
        run_id="ui-events-run",
        state_store=InMemoryStateStore(),
    )

    rows = event_rows(run)

    assert rows[0][1] == "WORKFLOW_STARTED"
    assert rows[-1][1] == "WORKFLOW_COMPLETED"
    assert [row[1] for row in rows] == [event.event_type.value for event in run.events]


def test_evaluation_presenters_return_all_metrics_and_cases() -> None:
    report = run_evaluation_suite()

    metric_rows = evaluation_metric_rows(report)
    case_rows = evaluation_case_rows(report)

    assert ["total_cases", "10"] in metric_rows
    assert len(case_rows) == 10
    assert all(row[2] == "PASS" for row in case_rows)
    assert any(row[0] == "model_control_injection" for row in case_rows)
