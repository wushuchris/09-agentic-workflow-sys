"""Gradio demo for Agent 9 — Agentic Workflow System.

The UI presents a fictional wealth-management household-onboarding workflow at two
levels: a plain-English business story for non-technical visitors and detailed
workflow evidence for engineers. Workflow-control logic remains in the runtime,
not in Gradio callbacks. All households and onboarding data are synthetic.
"""

from __future__ import annotations

import os
from typing import Any

import gradio as gr

from src.demo_workflow import build_onboarding_registry, build_onboarding_workflow
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


WORKFLOW = build_onboarding_workflow()
DATABASE_PATH = os.getenv("WORKFLOW_DB_PATH", "workflow_runs.db")
STATE_STORE = SQLiteStateStore(DATABASE_PATH)


STORY_SPECS: dict[str, dict[str, Any]] = {
    "Straightforward household — package becomes ready": {
        "household_id": "HH-STORY-STANDARD",
        "household_type": "JOINT",
        "onboarding_notes": (
            "Fictional joint household seeking a standard advisory relationship. "
            "All intake information is synthetic."
        ),
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "STANDARD",
        "simulation_mode": "NONE",
    },
    "Temporary service problem — retries and recovers": {
        "household_id": "HH-STORY-RETRY",
        "household_type": "JOINT",
        "onboarding_notes": (
            "Fictional standard household used to demonstrate one temporary onboarding-service interruption."
        ),
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "STANDARD",
        "simulation_mode": "TRANSIENT_ONCE",
    },
    "Trust / complex household — pauses for a person": {
        "household_id": "HH-STORY-EXCEPTION",
        "household_type": "TRUST",
        "onboarding_notes": (
            "Fictional trust household with a more complex relationship structure that requires extra review."
        ),
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "COMPLEX",
        "simulation_mode": "NONE",
    },
    "Permanent dependency failure — stops safely": {
        "household_id": "HH-STORY-FAILURE",
        "household_type": "JOINT",
        "onboarding_notes": (
            "Fictional standard household used to demonstrate a permanent downstream onboarding-service failure."
        ),
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "STANDARD",
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
.agent-hero p { margin: 0; max-width: 1000px; font-size: 1.03rem; line-height: 1.55; }
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
.ai-card {
  border-color: rgba(59,130,246,.55);
  background: linear-gradient(135deg, rgba(59,130,246,.14), rgba(99,102,241,.09));
}
.ai-explainer {
  padding: 1rem 1.1rem;
  border-radius: 14px;
  border: 1px solid rgba(59,130,246,.38);
  background: rgba(59,130,246,.08);
  margin: .7rem 0 1rem 0;
  line-height: 1.5;
}
.ai-explainer strong { font-size: 1.03rem; }
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
.ai-pill { border-color: rgba(59,130,246,.6); background: rgba(59,130,246,.12); }
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
.journey-wrap { padding: 1rem 0 .2rem 0; }
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
  <div class="agent-eyebrow">WEALTH MANAGEMENT • AI WORKFLOW PATTERN • SYNTHETIC DEMO</div>
  <h1>Agent 9 — Agentic Workflow System</h1>
  <p><strong>Imagine a fictional wealth-management firm onboarding a new household.</strong> The workflow validates intake, lets AI organize the notes inside a tightly bounded step, checks documents and exceptions with deterministic rules, prepares and verifies an onboarding package, retries temporary operational failures, and pauses exception cases for a person. No real client, account, KYC/AML service, money movement, or trade is involved.</p>
</div>
"""


PATTERN_HTML = """
<div class="pattern-grid">
  <div class="pattern-card ai-card"><strong>🤖 AI organizes the intake</strong><span>A bounded AI node may summarize synthetic notes and propose one approved household-profile category.</span></div>
  <div class="pattern-card"><strong>✓ Code enforces the process</strong><span>Document status, exception rules, routing, retries, persistence, and allowed next steps remain application-controlled.</span></div>
  <div class="pattern-card"><strong>🧑 A person handles exceptions</strong><span>Trust, entity, complex, missing-document, or identity-review cases can pause before they are marked ready.</span></div>
  <div class="pattern-card"><strong>↻ Operations recover safely</strong><span>Temporary service problems retry within a limit; permanent failures stop before uncertain downstream work.</span></div>
</div>
<div class="ai-explainer"><strong>Where is the AI?</strong><br>The <strong>AI Intake Organizer</strong> receives only the fictional household type and synthetic onboarding notes. Its output is restricted to a household-profile category and a short summary. It does <strong>not</strong> receive document-completeness flags, identity-review status, exception routing, handler names, retry limits, workflow state, or approval controls. The current public demo uses the deterministic fallback unless a live model provider is connected to this same bounded interface.</div>
<div class="section-note"><strong>The pattern:</strong> AI helps interpret unstructured intake; deterministic software owns the business process; people retain authority over exception decisions.</div>
<div class="pattern-flow">
  <span class="flow-pill">Household intake</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Validate</span><span class="flow-arrow">→</span>
  <span class="flow-pill ai-pill">🤖 AI organize</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Documents + rules</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Prepare + verify package</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Standard ready OR human review</span>
</div>
"""


EMPTY_OUTCOME_HTML = """
<div class="business-outcome outcome-neutral">
  <div class="outcome-eyebrow">READY TO DEMONSTRATE</div>
  <div class="outcome-title">Choose a fictional household story and run it</div>
  <div class="outcome-body">The result will be explained here in plain English. You can then open the technical tabs to see the exact state, audit events, AI-node output, retries, and human-review record behind the story.</div>
  <div class="outcome-takeaway">Start with “Straightforward household” for the simplest onboarding path.</div>
</div>
"""


EMPTY_JOURNEY_HTML = """
<div class="journey-wrap">
  <div class="journey-heading">What happened, step by step</div>
  <div class="journey-subheading">After you run a story, this section will show where AI assisted, where deterministic rules took over, and whether a person was required.</div>
</div>
"""


def run_request_ui(
    household_id: str,
    household_type: str,
    onboarding_notes: str,
    documents_complete: bool,
    identity_status: str,
    relationship_complexity: str,
    simulation_mode: str,
) -> AppBundle:
    """Run one synthetic onboarding case and return business plus technical views."""

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
        run = execute_workflow(
            WORKFLOW,
            build_onboarding_registry(),
            context=context,
            state_store=STATE_STORE,
        )
        return _app_bundle(run)
    except WorkflowExecutionError as exc:
        return _bundle_with_notice(exc.run, "The onboarding workflow stopped after a controlled failure.")
    except Exception as exc:  # UI boundary: do not surface traceback details
        return _empty_bundle(f"Unable to start onboarding workflow: {type(exc).__name__}")


def run_story_ui(story: str) -> AppBundle:
    """Run one prebuilt public-safe onboarding story for a non-technical visitor."""

    spec = STORY_SPECS.get(story)
    if spec is None:
        return _empty_bundle("Choose one of the four onboarding stories before running the workflow.")
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
    """Apply one explicit decision to the currently open onboarding review."""

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
            "Reload the run and inspect the Human Review table."
        )
        return _bundle_with_notice(run, notice)

    review = open_reviews[0]
    try:
        updated = submit_human_decision(
            WORKFLOW,
            build_onboarding_registry(),
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
        "### Wealth Onboarding Workflow Evaluation\n"
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

    with gr.Blocks(title="Agent 9 — Wealth Onboarding Workflow", css=APP_CSS) as demo:
        gr.HTML(HERO_HTML)
        gr.HTML(PATTERN_HTML)

        gr.Markdown("## Try the onboarding pattern in one click")
        gr.Markdown(
            "Pick a fictional household story. The app explains the business outcome first; "
            "the engineering evidence remains available in the technical tabs below."
        )
        story = gr.Radio(
            choices=list(STORY_SPECS),
            value="Straightforward household — package becomes ready",
            label="Choose an onboarding story",
        )
        story_button = gr.Button("Run This Onboarding Story", variant="primary")

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
            with gr.Tab("Customize Household"):
                gr.Markdown(
                    "### Build your own synthetic onboarding scenario\n"
                    "These inputs are fictional and exist only to demonstrate workflow behavior."
                )
                with gr.Row():
                    household_id = gr.Textbox(
                        label="Household ID",
                        value="HH-DEMO-001",
                    )
                    household_type = gr.Dropdown(
                        choices=["INDIVIDUAL", "JOINT", "TRUST", "ENTITY"],
                        value="JOINT",
                        label="Household Type",
                    )
                    documents_complete = gr.Checkbox(
                        label="Onboarding documents complete",
                        value=True,
                    )
                onboarding_notes = gr.Textbox(
                    label="Synthetic Onboarding Notes",
                    value=(
                        "Fictional household seeking a standard advisory relationship. "
                        "All information in this demo is synthetic."
                    ),
                    lines=4,
                )
                with gr.Row():
                    identity_status = gr.Dropdown(
                        choices=["VERIFIED", "REVIEW_REQUIRED"],
                        value="VERIFIED",
                        label="Identity Check Status",
                    )
                    relationship_complexity = gr.Dropdown(
                        choices=["STANDARD", "COMPLEX"],
                        value="STANDARD",
                        label="Relationship Complexity",
                    )
                    simulation_mode = gr.Dropdown(
                        choices=["NONE", "TRANSIENT_ONCE", "PERMANENT"],
                        value="NONE",
                        label="Failure Simulation",
                    )
                gr.Markdown(
                    "**Helpful shortcuts:** TRUST/ENTITY, COMPLEX, missing documents, or "
                    "REVIEW_REQUIRED demonstrates the human-review path. TRANSIENT_ONCE "
                    "demonstrates bounded retry recovery."
                )
                run_button = gr.Button("Run Custom Household", variant="primary")

            with gr.Tab("Technical Details"):
                gr.Markdown(
                    "### Engineering view\n"
                    "Inspect exact workflow status, node state, attempt counts, errors, and "
                    "structured outputs—including the AI Intake Organizer output and its source."
                )
                status = gr.Markdown("### Workflow Status\nRun a synthetic household to begin.")
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
                    "contains control metadata only; onboarding context is not copied into event details."
                )
                event_table = gr.Dataframe(
                    headers=EVENT_HEADERS,
                    interactive=False,
                    label="Append-Only Workflow Events",
                )

            with gr.Tab("Operations / Compliance Review"):
                gr.Markdown(
                    "### The human remains in control\n"
                    "A fictional exception case pauses here. The workflow cannot mark the "
                    "package ready until a person explicitly decides what should happen."
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
                    "**APPROVE** continues the approved exception path. **REJECT** ends the "
                    "fictional business process as `REJECTED`, not `FAILED`. **RETRY** opens "
                    "a fresh review without replaying completed upstream work. This is an "
                    "illustrative workflow, not any firm's actual regulatory procedure."
                )

            with gr.Tab("Evaluation"):
                gr.Markdown(
                    "### Reliability evidence\n"
                    "The same onboarding engine is exercised across success, retry, human "
                    "review, persistence, failure, and adversarial-control scenarios."
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
                household_id,
                household_type,
                onboarding_notes,
                documents_complete,
                identity_status,
                relationship_complexity,
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
