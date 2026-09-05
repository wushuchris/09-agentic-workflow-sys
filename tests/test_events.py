from src.events import record_event
from src.schemas import EventType, WorkflowRun


def test_record_event_appends_structured_event_to_run() -> None:
    run = WorkflowRun(run_id="run-1", workflow_id="workflow-1")

    event = record_event(
        run,
        EventType.WORKFLOW_STARTED,
        details={"workflow_id": "workflow-1"},
    )

    assert run.events == (event,)
    assert event.run_id == "run-1"
    assert event.event_type is EventType.WORKFLOW_STARTED
    assert event.node_id is None
    assert event.details == {"workflow_id": "workflow-1"}


def test_events_are_appended_in_order_with_unique_ids() -> None:
    run = WorkflowRun(run_id="run-1", workflow_id="workflow-1")

    first = record_event(run, EventType.WORKFLOW_STARTED)
    second = record_event(run, EventType.NODE_STARTED, node_id="task")
    third = record_event(run, EventType.NODE_COMPLETED, node_id="task")

    assert run.events == (first, second, third)
    assert len({event.event_id for event in run.events}) == 3


def test_event_details_are_copied_when_recorded() -> None:
    run = WorkflowRun(run_id="run-1", workflow_id="workflow-1")
    details = {"attempt": 1}

    event = record_event(run, EventType.NODE_STARTED, node_id="task", details=details)
    details["attempt"] = 99

    assert event.details == {"attempt": 1}


def test_new_workflow_run_starts_with_empty_tuple_event_history() -> None:
    run = WorkflowRun(run_id="run-1", workflow_id="workflow-1")

    assert run.events == ()
    assert isinstance(run.events, tuple)
