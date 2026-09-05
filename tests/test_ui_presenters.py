from src.demo_workflow import (
    build_service_request_registry,
    build_service_request_workflow,
    example_request,
)
from src.evaluation import run_evaluation_suite
from src.executor import execute_workflow
from src.persistence import InMemoryStateStore
from src.schemas import WorkflowStatus
from src.ui_presenters import (
    evaluation_case_rows,
    evaluation_metric_rows,
    event_rows,
    review_rows,
    run_bundle,
    run_summary,
)


def test_run_bundle_exposes_runtime_views_without_workflow_context_in_events() -> None:
    request = example_request(request_id="UI-PRESENTER")
    request["description"] = "SYNTHETIC_CONTEXT_MARKER"

    run = execute_workflow(
        build_service_request_workflow(),
        build_service_request_registry(),
        context=request,
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
    assert final_output["low_risk_finalize"]["outcome"] == "AUTO_FINALIZED"

    event_text = repr(events)
    assert "SYNTHETIC_CONTEXT_MARKER" not in event_text


def test_waiting_human_summary_and_review_rows_are_clear() -> None:
    run = execute_workflow(
        build_service_request_workflow(),
        build_service_request_registry(),
        context=example_request(
            request_id="UI-HUMAN",
            risk_level="HIGH",
            estimated_cost=1_500.0,
            priority="HIGH",
        ),
        run_id="ui-human-run",
        state_store=InMemoryStateStore(),
    )

    assert run.status is WorkflowStatus.WAITING_FOR_HUMAN
    assert "Action required" in run_summary(run)

    rows = review_rows(run)
    assert len(rows) == 1
    assert rows[0][1] == "human_review"
    assert rows[0][2] == "OPEN"
    assert "requires explicit human approval" in rows[0][3]


def test_event_rows_preserve_append_only_event_order() -> None:
    run = execute_workflow(
        build_service_request_workflow(),
        build_service_request_registry(),
        context=example_request(request_id="UI-EVENTS"),
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
