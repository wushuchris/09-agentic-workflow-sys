"""Gradio demo for Agent 9 — Agentic Workflow System.

The UI presents the same runtime at two levels: a plain-English business story for
non-technical visitors and detailed workflow evidence for engineers. Workflow-control
logic remains in the runtime, not in Gradio callbacks.
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
    business_journey_html,
    business_outcome_html,
    evaluation_case_rows,
    evaluation_metric_rows,
    run_bundle,
)


WORKFLOW = build_service_request_workflow()
DATABASE_PATH = os.getenv("WORKFLOW_DB_PATH", "workflow_runs.db")
STATE_STORE = SQLiteStateStore(DATABASE_PATH)


STORY_SPECS: dict[str, dict[str, Any]] = {
    "Routine request — finishes automatically": {
        "request_id": "REQ-STORY-ROUTINE",
        "request_type": "ACCESS",
        "description": "Provision standard synthetic access for a fictional demo user.",
        "priority": "NORMAL",
        "risk_level": "LOW",
        "estimated_cost": 125.0,
        "simulation_mode": "NONE",
    },
    "Temporary problem — retries once and recovers": {
        "request_id": "REQ-STORY-RETRY",
        "request_type": "ACCESS",
        "description": "Provision synthetic access while simulating one temporary service interruption.",
        "priority": "NORMAL",
        "risk_level": "LOW",
        "estimated_cost": 125.0,
        "simulation_mode": "TRANSIENT_ONCE",
    },
    "High-risk request — pauses for a person": {
        "request_id": "REQ-STORY-HIGH-RISK",
        "request_type": "ACCESS",
        "description": "Provision privileged synthetic access that requires explicit human review.",
        "priority": "HIGH",
        "risk_level": "HIGH",
        "estimated_cost": 1_500.0,
        "simulation_mode": "NONE",
    },
    "Permanent problem — stops safely": {
        "request_id": "REQ-STORY-FAILURE",
        "request_type": "ACCESS",
        "description": "Provision synthetic access while simulating a permanent downstream service failure.",
        "priority": "NORMAL",
        "risk_level": "LOW",
        "estimated_cost": 125.0,
        "simulation_mode": "PERMANENT",
    },
}


RunBundle = tuple[
    str,
    str,
    list[list[Any]],
    list[list[str]],
    list[list[str]],
    dict[str, Any],
]

AppBundle = tuple[
    str,
    str,
    list[list[Any]],
    list[list[str]],
    list[list[str]],
    dict[str, Any],
    str,
    str,
]


APP_CSS = """
.agent-hero {
  padding: 1.35rem 1.45rem;
  border: 1px solid var(--border-color-primary, rgba(127,127,127,.25));
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(249,115,22,.12), rgba(99,102,241,.08));
  margin-bottom: 1rem;
}
.agent-eyebrow, .outcome-eyebrow {
  font-size: .76rem;
  font-weight: 800;
  letter-spacing: .12em;
  opacity: .72;
  margin-bottom: .35rem;
}
.agent-hero h1 { margin: .1rem 0 .45rem 0; font-size: 2rem; }
.agent-hero p { margin: 0; max-width: 980px; font-size: 1.03rem; line-height: 1.55; }
.pattern-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: .8rem;
  margin: 1rem 0 1.15rem 0;
}
.pattern-card {
  padding: 1rem;
  border-radius: 14px;
  border: 1px solid var(--border-color-primary, rgba(127,127,127,.25));
  background: var(--block-background-fill, rgba(127,127,127,.06));
}
.pattern-card strong { display: block; margin-bottom: .3rem; font-size: 1rem; }
.pattern-card span { opacity: .78; line-height: 1.45; font-size: .92rem; }
.pattern-flow {
  display: flex;
  flex-wrap: wrap;
  gap: .55rem;
  align-items: center;
  margin-top: .65rem;
}
.flow-pill {
  padding: .48rem .7rem;
  border-radius: 999px;
  border: 1px solid var(--border-color-primary, rgba(127,127,127,.25));
  background: var(--block-background-fill, rgba(127,127,127,.06));
  font-weight: 650;
  font-size: .9rem;
}
.flow-arrow { opacity: .55; font-weight: 800; }
.business-outcome {
  border-radius: 16px;
  padding: 1.1rem 1.2rem;
  border: 1px solid var(--border-color-primary, rgba(127,127,127,.25));
  margin: .8rem 0;
}
.outcome-success { border-left: 6px solid #22c55e; background: rgba(34,197,94,.08); }
.outcome-waiting { border-left: 6px solid #f59e0b; background: rgba(245,158,11,.08); }
.outcome-rejected { border-left: 6px solid #f97316; background: rgba(249,115,22,.08); }
.outcome-failed { border-left: 6px solid #ef4444; background: rgba(239,68,68,.08); }
.outcome-neutral { border-left: 6px solid #64748b; background: rgba(100,116,139,.08); }
.outcome-title { font-size: 1.28rem; font-weight: 800; margin-bottom: .4rem; }
.outcome-body { line-height: 1.5; margin-bottom: .55rem; }
.outcome-takeaway { font-weight: 650; opacity: .83; }
.journey-wrap {
  padding: 1rem 0 .2rem 0;
}
.journey-heading { font-size: 1.15rem; font-weight: 800; }
.journey-subheading { opacity: .72; margin: .25rem 0 .8rem 0; line-height: 1.45; }
.journey-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(245px, 1fr));
  gap: .65rem;
}
.journey-step {
  display: flex;
  gap: .7rem;
  padding: .75rem .8rem;
  border-radius: 12px;
  border: 1px solid var(--border-color-primary, rgba(127,127,127,.22));
  background: var(--block-background-fill, rgba(127,127,127,.04));
}
.journey-icon {
  width: 30px;
  height: 30px;
  min-width: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 900;
}
.journey-done { background: rgba(34,197,94,.16); }
.journey-waiting { background: rgba(245,158,11,.18); }
.journey-rejected { background: rgba(249,115,22,.18); }
.journey-failed { background: rgba(239,68,68,.18); }
.journey-skipped { background: rgba(100,116,139,.16); }
.journey-pending { background: rgba(100,116,139,.10); }
.journey-title { font-weight: 750; }
.journey-state { font-size: .8rem; font-weight: 700; opacity: .78; margin: .1rem 0 .2rem 0; }
.journey-description { font-size: .86rem; opacity: .72; line-height: 1.38; }
.section-note {
  padding: .8rem 1rem;
  border-radius: 12px;
  background: rgba(99,102,241,.08);
  border: 1px solid rgba(99,102,241,.18);
  margin-bottom: .85rem;
}
"""


HERO_HTML = """
<div class="agent-hero">
  <div class="agent-eyebrow">AI WORKFLOW PATTERN</div>
  <h1>Agent 9 — Agentic Workflow System</h1>
  <p><strong>Think of this as a digital operations manager.</strong> It moves a business request through approved steps, retries temporary problems, stops safely on permanent failures, and asks a person before high-risk work can continue. AI may assist inside a bounded step, but it never gets to rewrite the process or bypass a human checkpoint.</p>
</div>
"""


PATTERN_HTML = """
<div class="pattern-grid">
  <div class="pattern-card"><strong>⚡ Automate routine work</strong><span>Low-risk requests can finish without pulling a person into every step.</span></div>
  <div class="pattern-card"><strong>↻ Recover from temporary problems</strong><span>Bounded retries handle transient failures without creating an endless loop.</span></div>
  <div class="pattern-card"><strong>🧑 Human control when it matters</strong><span>High-risk work pauses until an explicit person approves or rejects it.</span></div>
  <div class="pattern-card"><strong>🛑 Stop safely</strong><span>Permanent failures are contained so later actions do not run in an uncertain state.</span></div>
</div>
<div class="section-note"><strong>The pattern:</strong> the model or task can help with work inside a step, but application code owns the sequence, allowed routes, retry limits, saved state, and human approval.</div>
<div class="pattern-flow">
  <span class="flow-pill">Business request</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Validate</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Do work</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Verify</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Risk check</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Auto-finish OR human approval</span>
</div>
"""


EMPTY_OUTCOME_HTML = """
<div class="business-outcome outcome-neutral">
  <div class="outcome-eyebrow">READY TO DEMONSTRATE</div>
  <div class="outcome-title">Choose one story and run it</div>
  <div class="outcome-body">The result will be explained here in plain English. You can then open the technical tabs to see the exact node state, audit events, and structured outputs behind the story.</div>
  <div class="outcome-takeaway">Start with “Routine request” for the simplest path.</div>
</div>
"""


EMPTY_JOURNEY_HTML = """
<div class="journey-wrap">
  <div class="journey-heading">What happened, step by step</div>
  <div class="journey-subheading">After you run a story, this section will translate the workflow engine into an understandable business journey.</div>
</div>
"""


def run_request_ui(
    request_id: str,
    request_type: str,
    description: str,
    priority: str,
    risk_level: str,
    estimated_cost: float,
    simulation_mode: str,
) -> AppBundle:
    """Run one synthetic service request and return business plus technical views."""

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
        return _app_bundle(run)
    except WorkflowExecutionError as exc:
        return _bundle_with_notice(exc.run, "The workflow stopped after a controlled failure.")
    except Exception as exc:  # UI boundary: do not surface traceback details
        return _empty_bundle(f"Unable to start workflow: {type(exc).__name__}")


def run_story_ui(story: str) -> AppBundle:
    """Run one prebuilt public-safe story for a non-technical visitor."""

    spec = STORY_SPECS.get(story)
    if spec is None:
        return _empty_bundle("Choose one of the four demo stories before running the workflow.")
    return run_request_ui(**spec)


def refresh_run_ui(run_id: str) -> AppBundle:
    """Reload one persisted workflow run by its random run identifier."""

    if not run_id or not run_id.strip():
        return _empty_bundle("Enter a run ID to load a persisted workflow.")

    try:
        run = STATE_STORE.load(run_id.strip())
        return _app_bundle(run)
    except RunNotFoundError:
        return _empty_bundle("No persisted workflow run was found for that ID.", run_id.strip())
    except Exception as exc:
        return _empty_bundle(f"Unable to load workflow: {type(exc).__name__}", run_id.strip())


def submit_human_decision_ui(run_id: str, decision: str) -> AppBundle:
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
        return _app_bundle(updated)
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


def _app_bundle(run: WorkflowRun) -> AppBundle:
    technical: RunBundle = run_bundle(run)
    return (*technical, business_outcome_html(run), business_journey_html(run))


def _bundle_with_notice(run: WorkflowRun, notice: str) -> AppBundle:
    summary, run_id, nodes, events, reviews, final_output = run_bundle(run)
    return (
        f"> {notice}\n\n{summary}",
        run_id,
        nodes,
        events,
        reviews,
        final_output,
        business_outcome_html(run),
        business_journey_html(run),
    )


def _empty_bundle(message: str, run_id: str = "") -> AppBundle:
    return (
        f"### Workflow Status\n{message}",
        run_id,
        [],
        [],
        [],
        {},
        EMPTY_OUTCOME_HTML,
        EMPTY_JOURNEY_HTML,
    )


def build_app() -> gr.Blocks:
    """Construct the public Gradio application."""

    with gr.Blocks(title="Agent 9 — Agentic Workflow System", css=APP_CSS) as demo:
        gr.HTML(HERO_HTML)
        gr.HTML(PATTERN_HTML)

        gr.Markdown("## Try the pattern in one click")
        gr.Markdown(
            "Pick the business story you want to see. The app will explain the outcome "
            "in plain English first; the engineering evidence remains available below."
        )
        story = gr.Radio(
            choices=list(STORY_SPECS),
            value="Routine request — finishes automatically",
            label="Choose a demo story",
        )
        story_button = gr.Button("Run This Story", variant="primary")

        business_outcome = gr.HTML(EMPTY_OUTCOME_HTML)
        business_journey = gr.HTML(EMPTY_JOURNEY_HTML)

        with gr.Accordion("Reload a saved run", open=False):
            gr.Markdown(
                "Every run receives a random ID and is checkpointed in SQLite. Reloading "
                "a completed run shows the same state without replaying completed work."
            )
            with gr.Row():
                current_run_id = gr.Textbox(
                    label="Run ID",
                    placeholder="A random run ID appears here after execution.",
                )
                refresh_button = gr.Button("Reload Saved Run")

        with gr.Tabs():
            with gr.Tab("Customize Request"):
                gr.Markdown(
                    "### Build your own synthetic scenario\n"
                    "This is the same workflow used by the one-click stories, with the "
                    "inputs exposed so you can deliberately exercise different paths."
                )
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
                    "**Helpful shortcuts:** HIGH risk or cost ≥ 1000 demonstrates human "
                    "escalation. TRANSIENT_ONCE demonstrates bounded retry recovery."
                )
                run_button = gr.Button("Run Custom Request", variant="primary")

            with gr.Tab("Technical Details"):
                gr.Markdown(
                    "### Engineering view\n"
                    "This is the evidence behind the plain-English story: exact workflow "
                    "status, node state, attempt counts, errors, and structured outputs."
                )
                status = gr.Markdown("### Workflow Status\nRun a synthetic request to begin.")
                node_table = gr.Dataframe(
                    headers=NODE_HEADERS,
                    interactive=False,
                    label="Node Runtime State",
                )
                final_output = gr.JSON(label="Final Output")

            with gr.Tab("Audit Trail"):
                gr.Markdown(
                    "### Why the workflow is auditable\n"
                    "Every meaningful control transition is recorded. The audit timeline "
                    "contains control metadata only; workflow context is not copied into event details."
                )
                event_table = gr.Dataframe(
                    headers=EVENT_HEADERS,
                    interactive=False,
                    label="Append-Only Workflow Events",
                )

            with gr.Tab("Human Decision"):
                gr.Markdown(
                    "### The human remains in control\n"
                    "A high-risk run pauses here. The workflow cannot continue until a "
                    "person explicitly decides what should happen."
                )
                review_table = gr.Dataframe(
                    headers=REVIEW_HEADERS,
                    interactive=False,
                    label="Human Review History",
                )
                with gr.Row():
                    human_decision = gr.Dropdown(
                        choices=["APPROVE", "REJECT", "RETRY"],
                        value="APPROVE",
                        label="What should the reviewer do?",
                    )
                    decision_button = gr.Button("Submit Human Decision", variant="primary")
                gr.Markdown(
                    "**APPROVE** continues the approved high-risk path. **REJECT** ends the "
                    "business process as `REJECTED`, not `FAILED`. **RETRY** opens a fresh "
                    "review without replaying completed upstream work."
                )

            with gr.Tab("Evaluation"):
                gr.Markdown(
                    "### Reliability evidence\n"
                    "The same engine is exercised across success, retry, escalation, recovery, "
                    "failure, persistence, and adversarial-control scenarios."
                )
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
            business_outcome,
            business_journey,
        ]

        story_button.click(
            fn=run_story_ui,
            inputs=[story],
            outputs=run_outputs,
        )
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
