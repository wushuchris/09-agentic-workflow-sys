"""Gradio demo for Agent 9 — Agentic Workflow System.

The UI is intentionally thin: it calls the same workflow engine, persistence layer,
human-decision API, and evaluation harness used by tests. No workflow-control logic
is reimplemented in Gradio callbacks.
"""

from __future__ import annotations

import os
from typing import Any

import gradio as gr

from src.demo_workflow import (
    build_service_request_registry,
    build_service_request_workflow,
)
from src.evaluation import run_evaluation_suite
from src.executor import (
    WorkflowExecutionError,
    WorkflowHumanDecisionError,
    execute_workflow,
    submit_human_decision,
)
from src.persistence import RunNotFoundError, SQLiteStateStore
from src.schemas import HumanDecision, WorkflowRun
from src.ui_presenters import (
    CASE_HEADERS,
    EVENT_HEADERS,
    METRIC_HEADERS,
    NODE_HEADERS,
    REVIEW_HEADERS,
    evaluation_case_rows,
    evaluation_metric_rows,
    run_bundle,
)


WORKFLOW = build_service_request_workflow()
DATABASE_PATH = os.getenv("WORKFLOW_DB_PATH", "workflow_runs.db")
STATE_STORE = SQLiteStateStore(DATABASE_PATH)


RunBundle = tuple[
    str,
    str,
    list[list[Any]],
    list[list[str]],
    list[list[str]],
    dict[str, Any],
]


def run_request_ui(
    request_id: str,
    request_type: str,
    description: str,
    priority: str,
    risk_level: str,
    estimated_cost: float,
    simulation_mode: str,
) -> RunBundle:
    """Run one synthetic service request and return display-safe state."""

    context = {
        "request_id": request_id,
        "request_type": request_type,
        "description": description,
        "priority": priority,
        "risk_level": risk_level,
        "estimated_cost": estimated_cost,
        "supporting_info": {"source": "gradio-synthetic-demo"},
        "simulation_mode": simulation_mode,
    }

    try:
        run = execute_workflow(
            WORKFLOW,
            build_service_request_registry(),
            context=context,
            state_store=STATE_STORE,
        )
        return run_bundle(run)
    except WorkflowExecutionError as exc:
        return _bundle_with_notice(exc.run, "The workflow stopped after a controlled failure.")
    except Exception as exc:  # UI boundary: do not surface traceback details
        return _empty_bundle(f"Unable to start workflow: {type(exc).__name__}")


def refresh_run_ui(run_id: str) -> RunBundle:
    """Reload one persisted workflow run by its random run identifier."""

    if not run_id or not run_id.strip():
        return _empty_bundle("Enter a run ID to load a persisted workflow.")

    try:
        run = STATE_STORE.load(run_id.strip())
        return run_bundle(run)
    except RunNotFoundError:
        return _empty_bundle("No persisted workflow run was found for that ID.", run_id.strip())
    except Exception as exc:
        return _empty_bundle(f"Unable to load workflow: {type(exc).__name__}", run_id.strip())


def submit_human_decision_ui(run_id: str, decision: str) -> RunBundle:
    """Apply one explicit decision to the currently open human review."""

    if not run_id or not run_id.strip():
        return _empty_bundle("Enter a run ID before submitting a human decision.")

    normalized_run_id = run_id.strip()
    try:
        run = STATE_STORE.load(normalized_run_id)
    except RunNotFoundError:
        return _empty_bundle("No persisted workflow run was found for that ID.", normalized_run_id)

    open_reviews = [review for review in run.human_reviews if review.decision is None]
    if len(open_reviews) != 1:
        notice = (
            "This run does not have exactly one open human review. "
            "Refresh the run and inspect the Human Review table."
        )
        return _bundle_with_notice(run, notice)

    review = open_reviews[0]
    try:
        updated = submit_human_decision(
            WORKFLOW,
            build_service_request_registry(),
            run_id=normalized_run_id,
            review_id=review.review_id,
            decision=HumanDecision(decision),
            state_store=STATE_STORE,
        )
        return run_bundle(updated)
    except (WorkflowHumanDecisionError, WorkflowExecutionError) as exc:
        return _bundle_with_notice(exc.run, str(exc))
    except ValueError:
        return _bundle_with_notice(run, "Unknown human decision.")
    except Exception as exc:
        return _bundle_with_notice(run, f"Unable to apply decision: {type(exc).__name__}")


def run_evaluation_ui() -> tuple[str, list[list[str]], list[list[str]]]:
    """Run the deterministic system evaluation and return compact display rows."""

    report = run_evaluation_suite()
    summary = (
        "### Deterministic Evaluation\n"
        f"**Cases:** {report.passed_cases}/{report.total_cases} passed  \n"
        f"**Pass rate:** {report.case_pass_rate:.2f}  \n"
        f"**Duplicate executions:** {report.metrics['duplicate_execution_count']}  \n"
        f"**Invalid transitions:** {report.metrics['invalid_transition_count']}"
    )
    return summary, evaluation_metric_rows(report), evaluation_case_rows(report)


def _bundle_with_notice(run: WorkflowRun, notice: str) -> RunBundle:
    summary, run_id, nodes, events, reviews, final_output = run_bundle(run)
    return (
        f"> {notice}\n\n{summary}",
        run_id,
        nodes,
        events,
        reviews,
        final_output,
    )


def _empty_bundle(message: str, run_id: str = "") -> RunBundle:
    return (f"### Workflow Status\n{message}", run_id, [], [], [], {})


def build_app() -> gr.Blocks:
    """Construct the public Gradio application."""

    with gr.Blocks(title="Agent 9 — Agentic Workflow System") as demo:
        gr.Markdown(
            "# Agent 9 — Agentic Workflow System\n"
            "A deterministic, resumable, and auditable workflow runtime for "
            "AI-assisted business processes. The demo uses fictional synthetic data."
        )
        gr.Markdown(
            "**Control principle:** AI may assist inside a bounded node; application "
            "code owns workflow state, execution order, retries, routing, persistence, "
            "and human approval."
        )

        with gr.Row():
            current_run_id = gr.Textbox(
                label="Current Run ID",
                placeholder="A random run ID appears here after execution.",
            )
            refresh_button = gr.Button("Refresh Persisted Run")

        status = gr.Markdown("### Workflow Status\nRun a synthetic request to begin.")

        with gr.Tabs():
            with gr.Tab("Run Workflow"):
                with gr.Row():
                    request_id = gr.Textbox(
                        label="Request ID",
                        value="REQ-DEMO-001",
                    )
                    request_type = gr.Dropdown(
                        choices=["ACCESS", "BILLING", "GENERAL"],
                        value="ACCESS",
                        label="Request Type",
                    )
                    priority = gr.Dropdown(
                        choices=["LOW", "NORMAL", "HIGH"],
                        value="NORMAL",
                        label="Priority",
                    )
                description = gr.Textbox(
                    label="Description",
                    value="Provision synthetic access for a fictional demo user.",
                    lines=3,
                )
                with gr.Row():
                    risk_level = gr.Dropdown(
                        choices=["LOW", "HIGH"],
                        value="LOW",
                        label="Risk Level",
                    )
                    estimated_cost = gr.Number(
                        label="Estimated Cost",
                        value=125.0,
                        minimum=0,
                    )
                    simulation_mode = gr.Dropdown(
                        choices=["NONE", "TRANSIENT_ONCE", "PERMANENT"],
                        value="NONE",
                        label="Failure Simulation",
                    )
                gr.Markdown(
                    "Use **HIGH** risk or cost ≥ 1000 to demonstrate human escalation. "
                    "Use **TRANSIENT_ONCE** to show bounded retry recovery."
                )
                run_button = gr.Button("Run Workflow", variant="primary")

            with gr.Tab("Status & Node Results"):
                node_table = gr.Dataframe(
                    headers=NODE_HEADERS,
                    interactive=False,
                    label="Node Runtime State",
                )
                final_output = gr.JSON(label="Final Output")

            with gr.Tab("Event Timeline"):
                gr.Markdown(
                    "The audit timeline contains control metadata only; workflow context "
                    "is not copied into event details."
                )
                event_table = gr.Dataframe(
                    headers=EVENT_HEADERS,
                    interactive=False,
                    label="Append-Only Workflow Events",
                )

            with gr.Tab("Human Approval"):
                review_table = gr.Dataframe(
                    headers=REVIEW_HEADERS,
                    interactive=False,
                    label="Human Review History",
                )
                with gr.Row():
                    human_decision = gr.Dropdown(
                        choices=["APPROVE", "REJECT", "RETRY"],
                        value="APPROVE",
                        label="Decision",
                    )
                    decision_button = gr.Button("Submit Human Decision", variant="primary")
                gr.Markdown(
                    "A waiting human gate cannot be bypassed with ordinary resume. "
                    "REJECT ends the business process as `REJECTED`, not `FAILED`."
                )

            with gr.Tab("Evaluation Results"):
                evaluation_summary = gr.Markdown(
                    "Run the deterministic evaluation harness to inspect system-level metrics."
                )
                evaluation_button = gr.Button("Run 10-Case Evaluation")
                metric_table = gr.Dataframe(
                    headers=METRIC_HEADERS,
                    interactive=False,
                    label="Evaluation Metrics",
                )
                case_table = gr.Dataframe(
                    headers=CASE_HEADERS,
                    interactive=False,
                    label="Evaluation Cases",
                )

        run_outputs = [
            status,
            current_run_id,
            node_table,
            event_table,
            review_table,
            final_output,
        ]

        run_button.click(
            fn=run_request_ui,
            inputs=[
                request_id,
                request_type,
                description,
                priority,
                risk_level,
                estimated_cost,
                simulation_mode,
            ],
            outputs=run_outputs,
        )
        refresh_button.click(
            fn=refresh_run_ui,
            inputs=[current_run_id],
            outputs=run_outputs,
        )
        decision_button.click(
            fn=submit_human_decision_ui,
            inputs=[current_run_id, human_decision],
            outputs=run_outputs,
        )
        evaluation_button.click(
            fn=run_evaluation_ui,
            outputs=[evaluation_summary, metric_table, case_table],
        )

    return demo


demo = build_app()


if __name__ == "__main__":
    demo.queue().launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
    )
