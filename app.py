"""Gradio demo for Agent 9 — Agentic Workflow System."""

from __future__ import annotations

import os
import time
from typing import Any

import gradio as gr

from src.demo_presentation import (
    APP_CSS,
    EMPTY_ACTIVITY_HTML,
    EMPTY_AI_HTML,
    EMPTY_JOURNEY_HTML,
    EMPTY_OUTCOME_HTML,
    EMPTY_PATH_HTML,
    EMPTY_ROUTING_HTML,
    HERO_HTML,
    PATTERN_HTML,
    activity_html,
    activity_start_html,
    playback_delay,
)
from src.demo_workflow import build_onboarding_registry, build_onboarding_workflow
from src.evaluation import run_evaluation_suite
from src.executor import (
    WorkflowExecutionError,
    WorkflowHumanDecisionError,
    execute_workflow,
    submit_human_decision,
)
from src.hf_provider import (
    build_hf_onboarding_model_from_env,
    configured_model_id,
    live_ai_enabled_from_env,
)
from src.persistence import RunNotFoundError, SQLiteStateStore
from src.schemas import HumanDecision, WorkflowRun
from src.ui_presenters import (
    CASE_HEADERS,
    EVENT_HEADERS,
    METRIC_HEADERS,
    NODE_HEADERS,
    REVIEW_HEADERS,
    ai_insight_html,
    business_journey_html,
    business_outcome_html,
    evaluation_case_rows,
    evaluation_metric_rows,
    routing_explanation_html,
    run_bundle,
    workflow_path_html,
)

WORKFLOW = build_onboarding_workflow()
DATABASE_PATH = os.getenv("WORKFLOW_DB_PATH", "workflow_runs.db")
STATE_STORE = SQLiteStateStore(DATABASE_PATH)
LIVE_MODEL_ID = configured_model_id()
LIVE_ONBOARDING_MODEL = build_hf_onboarding_model_from_env()

STORY_SPECS: dict[str, dict[str, Any]] = {
    "Harbor Family — straightforward household": {
        "household_id": "HH-HARBOR-STANDARD",
        "household_type": "JOINT",
        "onboarding_notes": "The fictional Harbor family is beginning a standard advisory relationship. The household has two adults, straightforward planning needs, and a complete synthetic intake.",
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "STANDARD",
        "simulation_mode": "NONE",
    },
    "Harbor Family — temporary onboarding-service issue": {
        "household_id": "HH-HARBOR-RETRY",
        "household_type": "JOINT",
        "onboarding_notes": "The fictional Harbor family has a straightforward synthetic intake, but the demo will simulate one temporary package-preparation service interruption.",
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "STANDARD",
        "simulation_mode": "TRANSIENT_ONCE",
    },
    "Redwood Family Trust — human review required": {
        "household_id": "HH-REDWOOD-TRUST",
        "household_type": "TRUST",
        "onboarding_notes": "The fictional Redwood Family Trust has multiple interested parties and a more complex planning relationship. The synthetic intake is complete but should demonstrate an exception-review path.",
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "COMPLEX",
        "simulation_mode": "NONE",
    },
    "Cedar Household — permanent dependency failure": {
        "household_id": "HH-CEDAR-FAILURE",
        "household_type": "JOINT",
        "onboarding_notes": "The fictional Cedar household has a standard synthetic intake, but the demo will simulate a permanent downstream package-preparation failure.",
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "STANDARD",
        "simulation_mode": "PERMANENT",
    },
}

RunBundle = tuple[str, str, list[list[Any]], list[list[str]], list[list[str]], dict[str, Any]]
AppBundle = tuple[
    str,
    str,
    list[list[Any]],
    list[list[str]],
    list[list[str]],
    dict[str, Any],
    str,
    str,
    str,
    str,
    str,
]


def _ai_runtime_html() -> str:
    if LIVE_ONBOARDING_MODEL is not None:
        return (
            '<div class="ai-runtime ai-runtime-live"><strong>● Live AI connected</strong><br>'
            f'The AI Intake Organizer is using Hugging Face Inference Providers with <code>{LIVE_MODEL_ID}</code>. '
            'Its output still must pass the same strict Pydantic schema before the workflow can use it.</div>'
        )
    if live_ai_enabled_from_env():
        return (
            '<div class="ai-runtime ai-runtime-waiting"><strong>◐ Live AI requested but not connected</strong><br>'
            'LIVE_AI_ENABLED is on, but no usable HF_TOKEN was found. The demo is using its explicit deterministic fallback.</div>'
        )
    return (
        '<div class="ai-runtime"><strong>○ AI boundary ready; deterministic fallback active</strong><br>'
        'Live inference is deliberately opt-in. The same bounded node can use Hugging Face Inference Providers when the deployment sets <code>LIVE_AI_ENABLED=true</code> and supplies <code>HF_TOKEN</code>.</div>'
    )


def _build_registry():
    return build_onboarding_registry(
        onboarding_model=LIVE_ONBOARDING_MODEL,
        model_label=LIVE_MODEL_ID if LIVE_ONBOARDING_MODEL is not None else None,
    )


def run_request_ui(
    household_id: str,
    household_type: str,
    onboarding_notes: str,
    documents_complete: bool,
    identity_status: str,
    relationship_complexity: str,
    simulation_mode: str,
) -> AppBundle:
    context = {
        "household_id": household_id,
        "household_type": household_type,
        "onboarding_notes": onboarding_notes,
        "documents_complete": documents_complete,
        "identity_status": identity_status,
        "relationship_complexity": relationship_complexity,
        "simulation_mode": simulation_mode,
    }
    try:
        run = execute_workflow(WORKFLOW, _build_registry(), context=context, state_store=STATE_STORE)
        return _app_bundle(run)
    except WorkflowExecutionError as exc:
        return _bundle_with_notice(exc.run, "The onboarding workflow stopped after a controlled failure.")
    except Exception as exc:
        return _empty_bundle(f"Unable to start onboarding workflow: {type(exc).__name__}")


def run_story_ui(story: str) -> AppBundle:
    spec = STORY_SPECS.get(story)
    if spec is None:
        return _empty_bundle("Choose one of the four onboarding stories before running the workflow.")
    return run_request_ui(**spec)


def refresh_run_ui(run_id: str) -> AppBundle:
    if not run_id or not run_id.strip():
        return _empty_bundle("Enter a run ID to load a persisted workflow.")
    try:
        return _app_bundle(STATE_STORE.load(run_id.strip()))
    except RunNotFoundError:
        return _empty_bundle("No persisted workflow run was found for that ID.", run_id.strip())
    except Exception as exc:
        return _empty_bundle(f"Unable to load workflow: {type(exc).__name__}", run_id.strip())


def submit_human_decision_ui(run_id: str, decision: str) -> AppBundle:
    if not run_id or not run_id.strip():
        return _empty_bundle("Enter a run ID before submitting a human decision.")
    normalized_run_id = run_id.strip()
    try:
        run = STATE_STORE.load(normalized_run_id)
    except RunNotFoundError:
        return _empty_bundle("No persisted workflow run was found for that ID.", normalized_run_id)
    open_reviews = [review for review in run.human_reviews if review.decision is None]
    if len(open_reviews) != 1:
        return _bundle_with_notice(run, "This run does not have exactly one open human review. Reload the run and inspect the Human Review table.")
    try:
        updated = submit_human_decision(
            WORKFLOW,
            _build_registry(),
            run_id=normalized_run_id,
            review_id=open_reviews[0].review_id,
            decision=HumanDecision(decision),
            state_store=STATE_STORE,
        )
        return _app_bundle(updated)
    except (WorkflowHumanDecisionError, WorkflowExecutionError) as exc:
        return _bundle_with_notice(exc.run, str(exc))
    except ValueError:
        return _bundle_with_notice(run, "Unknown human decision.")
    except Exception as exc:
        return _bundle_with_notice(run, f"Unable to apply decision: {type(exc).__name__}")


def run_evaluation_ui() -> tuple[str, list[list[str]], list[list[str]]]:
    report = run_evaluation_suite()
    summary = (
        "### Wealth Onboarding Workflow Evaluation\n"
        f"**Cases:** {report.passed_cases}/{report.total_cases} passed  \n"
        f"**Pass rate:** {report.case_pass_rate:.2f}  \n"
        f"**Duplicate executions:** {report.metrics['duplicate_execution_count']}  \n"
        f"**Invalid transitions:** {report.metrics['invalid_transition_count']}"
    )
    return summary, evaluation_metric_rows(report), evaluation_case_rows(report)


def _app_bundle(run: WorkflowRun) -> AppBundle:
    technical: RunBundle = run_bundle(run)
    return (
        *technical,
        business_outcome_html(run),
        workflow_path_html(run),
        ai_insight_html(run),
        routing_explanation_html(run),
        business_journey_html(run),
    )


def _bundle_with_notice(run: WorkflowRun, notice: str) -> AppBundle:
    technical = run_bundle(run)
    return (
        f"> {notice}\n\n{technical[0]}",
        *technical[1:],
        business_outcome_html(run),
        workflow_path_html(run),
        ai_insight_html(run),
        routing_explanation_html(run),
        business_journey_html(run),
    )


def _empty_bundle(message: str, run_id: str = "") -> AppBundle:
    return (
        f"### Workflow Status\n{message}", run_id, [], [], [], {},
        EMPTY_OUTCOME_HTML, EMPTY_PATH_HTML, EMPTY_AI_HTML, EMPTY_ROUTING_HTML, EMPTY_JOURNEY_HTML,
    )


def _running_bundle(run_id: str = "") -> AppBundle:
    return (
        "### Workflow running…\nThe workflow engine is controlling the approved next steps.",
        run_id,
        [], [], [], {},
        EMPTY_OUTCOME_HTML, EMPTY_PATH_HTML, EMPTY_AI_HTML, EMPTY_ROUTING_HTML, EMPTY_JOURNEY_HTML,
    )


def _stream_bundle(bundle: AppBundle):
    run_id = bundle[1]
    if not run_id:
        yield ('<div class="activity-card"><div class="activity-badge">STOPPED</div><div class="activity-title">Workflow did not start</div></div>', *bundle)
        return
    try:
        run = STATE_STORE.load(run_id)
    except Exception:
        yield ('<div class="activity-card"><div class="activity-badge">STOPPED</div><div class="activity-title">Workflow trace unavailable</div></div>', *bundle)
        return
    running = _running_bundle(run_id)
    for index, event in enumerate(run.events, start=1):
        yield (activity_html(run, index), *running)
        time.sleep(playback_delay(event.event_type.value))
    yield (activity_html(run, len(run.events), complete=True), *bundle)


def stream_story_ui(story: str):
    yield (activity_start_html(story), *_running_bundle())
    yield from _stream_bundle(run_story_ui(story))


def stream_request_ui(
    household_id: str,
    household_type: str,
    onboarding_notes: str,
    documents_complete: bool,
    identity_status: str,
    relationship_complexity: str,
    simulation_mode: str,
):
    yield (activity_start_html("Custom synthetic household"), *_running_bundle())
    bundle = run_request_ui(
        household_id, household_type, onboarding_notes, documents_complete,
        identity_status, relationship_complexity, simulation_mode,
    )
    yield from _stream_bundle(bundle)


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Agent 9 — Wealth Onboarding Workflow", analytics_enabled=False) as demo:
        gr.HTML(HERO_HTML)
        gr.HTML(PATTERN_HTML)
        gr.HTML(_ai_runtime_html())

        gr.Markdown("## Try the onboarding pattern in one click")
        gr.Markdown("Choose a fictional household and watch the workflow control plane move it through AI assistance, deterministic rules, retry/recovery, and human escalation.")
        story = gr.Radio(choices=list(STORY_SPECS), value="Harbor Family — straightforward household", label="Choose an onboarding story")
        story_button = gr.Button("Run this onboarding workflow", variant="primary")
        live_activity = gr.HTML(EMPTY_ACTIVITY_HTML)

        business_outcome = gr.HTML(EMPTY_OUTCOME_HTML)
        workflow_path = gr.HTML(EMPTY_PATH_HTML)
        ai_insight = gr.HTML(EMPTY_AI_HTML)
        routing_explanation = gr.HTML(EMPTY_ROUTING_HTML)
        business_journey = gr.HTML(EMPTY_JOURNEY_HTML)

        with gr.Accordion("Reload a saved run", open=False):
            gr.Markdown("Every run receives a random ID and is checkpointed in SQLite. Reloading a completed run shows the same state without replaying completed work.")
            with gr.Row():
                current_run_id = gr.Textbox(label="Run ID", placeholder="A random run ID appears here after execution.")
                refresh_button = gr.Button("Reload Saved Run")

        with gr.Tabs():
            with gr.Tab("Customize Scenario"):
                gr.Markdown("### Build your own synthetic onboarding scenario\nThese inputs are fictional and exist only to demonstrate workflow behavior.")
                household_id = gr.Textbox(label="Household ID", value="HH-DEMO-001")
                household_type = gr.Dropdown(choices=["INDIVIDUAL", "JOINT", "TRUST", "ENTITY"], value="JOINT", label="Household Type")
                documents_complete = gr.Checkbox(label="Onboarding documents complete", value=True)
                onboarding_notes = gr.Textbox(label="Synthetic Onboarding Notes", value="Fictional household seeking a standard advisory relationship. All information in this demo is synthetic.", lines=4)
                identity_status = gr.Dropdown(choices=["VERIFIED", "REVIEW_REQUIRED"], value="VERIFIED", label="Identity Check Status")
                relationship_complexity = gr.Dropdown(choices=["STANDARD", "COMPLEX"], value="STANDARD", label="Relationship Complexity")
                simulation_mode = gr.Dropdown(choices=["NONE", "TRANSIENT_ONCE", "PERMANENT"], value="NONE", label="Failure Simulation")
                gr.Markdown("**Helpful shortcuts:** TRUST/ENTITY, COMPLEX, missing documents, or REVIEW_REQUIRED demonstrates human review. TRANSIENT_ONCE demonstrates bounded retry recovery.")
                run_button = gr.Button("Run custom workflow", variant="primary")

            with gr.Tab("Engineering State"):
                gr.Markdown("### Engineering evidence\nInspect exact workflow status, node state, attempt counts, errors, and structured outputs—including the AI Intake Organizer output and its source.")
                status = gr.Markdown("### Workflow Status\nRun a synthetic household to begin.")
                node_table = gr.Dataframe(headers=NODE_HEADERS, interactive=False, label="Node Runtime State")
                final_output = gr.JSON(label="Final Output")

            with gr.Tab("Audit Trail"):
                gr.Markdown("### Why the workflow is auditable\nEvery meaningful control transition is recorded. The audit timeline contains control metadata only; onboarding context is not copied into event details.")
                event_table = gr.Dataframe(headers=EVENT_HEADERS, interactive=False, label="Append-Only Workflow Events")

            with gr.Tab("Human Review"):
                gr.Markdown("### The human remains in control\nA fictional exception case pauses here. The workflow cannot mark the package ready until a person explicitly decides what should happen.")
                review_table = gr.Dataframe(headers=REVIEW_HEADERS, interactive=False, label="Human Review History")
                human_decision = gr.Dropdown(choices=["APPROVE", "REJECT", "RETRY"], value="APPROVE", label="What should the reviewer do?")
                decision_button = gr.Button("Submit Human Decision", variant="primary")
                gr.Markdown("**APPROVE** continues the approved exception path. **REJECT** ends the fictional process as `REJECTED`, not `FAILED`. **RETRY** opens a fresh review without replaying completed upstream work. This is illustrative, not any firm's actual regulatory procedure.")

            with gr.Tab("Evaluation"):
                gr.Markdown("### Reliability evidence\nThe same onboarding engine is exercised across success, retry, human review, persistence, failure, and adversarial-control scenarios.")
                evaluation_summary = gr.Markdown("Run the deterministic evaluation harness to inspect system-level metrics.")
                evaluation_button = gr.Button("Run 10-Case Evaluation")
                metric_table = gr.Dataframe(headers=METRIC_HEADERS, interactive=False, label="Evaluation Metrics")
                case_table = gr.Dataframe(headers=CASE_HEADERS, interactive=False, label="Evaluation Cases")

        run_outputs = [
            status, current_run_id, node_table, event_table, review_table, final_output,
            business_outcome, workflow_path, ai_insight, routing_explanation, business_journey,
        ]
        stream_outputs = [live_activity, *run_outputs]

        story_button.click(fn=stream_story_ui, inputs=[story], outputs=stream_outputs, show_progress="hidden")
        run_button.click(
            fn=stream_request_ui,
            inputs=[household_id, household_type, onboarding_notes, documents_complete, identity_status, relationship_complexity, simulation_mode],
            outputs=stream_outputs,
            show_progress="hidden",
        )
        refresh_button.click(fn=refresh_run_ui, inputs=[current_run_id], outputs=run_outputs)
        decision_button.click(fn=submit_human_decision_ui, inputs=[current_run_id, human_decision], outputs=run_outputs)
        evaluation_button.click(fn=run_evaluation_ui, outputs=[evaluation_summary, metric_table, case_table])

    return demo


demo = build_app()

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")), css=APP_CSS)
