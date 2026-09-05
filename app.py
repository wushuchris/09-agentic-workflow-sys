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
        "onboarding_notes": (
            "The fictional Harbor family is beginning a standard advisory relationship. "
            "The household has two adults, straightforward planning needs, and a complete synthetic intake."
        ),
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "STANDARD",
        "simulation_mode": "NONE",
    },
    "Harbor Family — temporary onboarding-service issue": {
        "household_id": "HH-HARBOR-RETRY",
        "household_type": "JOINT",
        "onboarding_notes": (
            "The fictional Harbor family has a straightforward synthetic intake, but the demo will simulate one temporary package-preparation service interruption."
        ),
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "STANDARD",
        "simulation_mode": "TRANSIENT_ONCE",
    },
    "Redwood Family Trust — human review required": {
        "household_id": "HH-REDWOOD-TRUST",
        "household_type": "TRUST",
        "onboarding_notes": (
            "The fictional Redwood Family Trust has multiple interested parties and a more complex planning relationship. The synthetic intake is complete but should demonstrate an exception-review path."
        ),
        "documents_complete": True,
        "identity_status": "VERIFIED",
        "relationship_complexity": "COMPLEX",
        "simulation_mode": "NONE",
    },
    "Cedar Household — permanent dependency failure": {
        "household_id": "HH-CEDAR-FAILURE",
        "household_type": "JOINT",
        "onboarding_notes": (
            "The fictional Cedar household has a standard synthetic intake, but the demo will simulate a permanent downstream package-preparation failure."
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
    str,
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
.agent-eyebrow, .outcome-eyebrow, .panel-eyebrow {
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
.pattern-card, .ai-result, .why-panel {
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
.ai-explainer, .ai-runtime {
  padding: 1rem 1.1rem;
  border-radius: 14px;
  border: 1px solid rgba(59,130,246,.38);
  background: rgba(59,130,246,.08);
  margin: .7rem 0 1rem 0;
  line-height: 1.5;
}
.ai-runtime-live { border-color: rgba(34,197,94,.45); background: rgba(34,197,94,.08); }
.ai-runtime-waiting { border-color: rgba(245,158,11,.45); background: rgba(245,158,11,.08); }
.pattern-flow { display: flex; flex-wrap: wrap; gap: .55rem; align-items: center; margin-top: .65rem; }
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
.outcome-title, .panel-title { font-size: 1.2rem; font-weight: 800; margin-bottom: .4rem; }
.outcome-body, .panel-body { line-height: 1.5; margin-bottom: .55rem; }
.outcome-takeaway { font-weight: 650; opacity: .83; }
.ai-result-live { border-color: rgba(59,130,246,.6); background: rgba(59,130,246,.09); }
.ai-result-fallback { border-color: rgba(100,116,139,.4); }
.ai-result-failed { border-color: rgba(239,68,68,.45); background: rgba(239,68,68,.07); }
.ai-mode { display: inline-block; padding: .25rem .5rem; border-radius: 999px; font-size: .76rem; font-weight: 800; background: rgba(59,130,246,.14); margin-bottom: .45rem; }
.ai-model { font-size: .82rem; opacity: .7; margin-bottom: .5rem; }
.ai-category { margin-bottom: .5rem; }
.ai-summary { line-height: 1.48; margin-bottom: .6rem; }
.ai-used { font-weight: 700; margin-bottom: .45rem; }
.ai-boundary, .why-proof { font-size: .88rem; opacity: .78; line-height: 1.4; }
.why-standard { border-left: 5px solid #22c55e; }
.why-review { border-left: 5px solid #f59e0b; }
.why-list { margin: .35rem 0 .7rem 1.15rem; }
.workflow-map {
  margin: 1rem 0;
  padding: 1rem 1.05rem;
  border-radius: 16px;
  border: 1px solid var(--border-color-primary, rgba(127,127,127,.25));
  background: var(--block-background-fill, rgba(127,127,127,.04));
}
.map-heading { font-size: 1.15rem; font-weight: 800; }
.map-subheading { opacity: .7; margin: .2rem 0 .9rem 0; line-height: 1.4; }
.map-main { display: flex; flex-wrap: wrap; align-items: center; gap: .42rem; }
.map-split { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: .75rem; margin-top: .85rem; }
.map-branch { padding: .75rem; border-radius: 12px; border: 1px dashed var(--border-color-primary, rgba(127,127,127,.28)); }
.branch-label { font-size: .72rem; font-weight: 800; letter-spacing: .08em; opacity: .65; margin-bottom: .45rem; }
.map-node { display: inline-block; padding: .42rem .62rem; border-radius: 10px; border: 1px solid rgba(100,116,139,.35); background: rgba(100,116,139,.08); font-size: .84rem; font-weight: 700; }
.map-node-completed { border-color: rgba(34,197,94,.55); background: rgba(34,197,94,.12); }
.map-node-waiting-for-human, .map-node-retry-scheduled, .map-node-running { border-color: rgba(245,158,11,.6); background: rgba(245,158,11,.12); }
.map-node-failed { border-color: rgba(239,68,68,.6); background: rgba(239,68,68,.12); }
.map-node-skipped, .map-node-pending, .map-node-ready { opacity: .42; }
.map-node-ai { box-shadow: inset 0 0 0 2px rgba(59,130,246,.62); }
.map-arrow { opacity: .5; font-weight: 800; }
.map-legend { margin-top: .8rem; font-size: .8rem; opacity: .65; }
.journey-wrap { padding: 1rem 0 .2rem 0; }
.journey-heading { font-size: 1.15rem; font-weight: 800; }
.journey-subheading { opacity: .72; margin: .25rem 0 .8rem 0; line-height: 1.45; }
.journey-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(245px, 1fr)); gap: .65rem; }
.journey-step { display: flex; gap: .7rem; padding: .75rem .8rem; border-radius: 12px; border: 1px solid var(--border-color-primary, rgba(127,127,127,.22)); background: var(--block-background-fill, rgba(127,127,127,.04)); }
.journey-icon { width: 30px; height: 30px; min-width: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 900; }
.journey-done { background: rgba(34,197,94,.16); }
.journey-waiting { background: rgba(245,158,11,.18); }
.journey-rejected { background: rgba(249,115,22,.18); }
.journey-failed { background: rgba(239,68,68,.18); }
.journey-skipped { background: rgba(100,116,139,.16); }
.journey-pending { background: rgba(100,116,139,.10); }
.journey-title { font-weight: 750; }
.journey-state { font-size: .8rem; font-weight: 700; opacity: .78; margin: .1rem 0 .2rem 0; }
.journey-description { font-size: .86rem; opacity: .72; line-height: 1.38; }
.section-note { padding: .8rem 1rem; border-radius: 12px; background: rgba(99,102,241,.08); border: 1px solid rgba(99,102,241,.18); margin-bottom: .85rem; }
"""


HERO_HTML = """
<div class="agent-hero">
  <div class="agent-eyebrow">WEALTH MANAGEMENT • OPERATIONS WORKFLOW DASHBOARD • SYNTHETIC DEMO</div>
  <h1>Agent 9 — Agentic Workflow System</h1>
  <p><strong>Think of this as an operations workflow dashboard for a fictional wealth-management firm.</strong> In this example, the dashboard follows a new household through onboarding and makes the AI step, deterministic controls, retries, routing, and human review visible in one place. AI organizes the unstructured intake into useful work product while application code governs what happens next. No real client, account, KYC/AML service, money movement, or trade is involved.</p>
</div>
"""


PATTERN_HTML = """
<div class="pattern-grid">
  <div class="pattern-card ai-card"><strong>🤖 AI contributes work product</strong><span>The bounded AI node creates a profile category and concise intake summary that can be included in the simulated onboarding package.</span></div>
  <div class="pattern-card"><strong>✓ Code governs consequences</strong><span>Document status, exception rules, routing, retries, persistence, and allowed next steps remain application-controlled.</span></div>
  <div class="pattern-card"><strong>🧑 A person handles exceptions</strong><span>Trust, entity, complex, missing-document, or identity-review cases can pause before they are marked ready.</span></div>
  <div class="pattern-card"><strong>↻ Operations recover safely</strong><span>Temporary service problems retry within a limit; permanent failures stop before uncertain downstream work.</span></div>
</div>
<div class="section-note"><strong>The pattern:</strong> AI produces useful, validated work. Deterministic software controls the business process. Humans retain authority over consequential exceptions.</div>
<div class="pattern-flow">
  <span class="flow-pill">Household intake</span><span class="flow-arrow">→</span>
  <span class="flow-pill ai-pill">🤖 AI organize</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Rules + package</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Verify</span><span class="flow-arrow">→</span>
  <span class="flow-pill">Standard ready OR human review</span>
</div>
"""


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


EMPTY_OUTCOME_HTML = """
<div class="business-outcome outcome-neutral">
  <div class="outcome-eyebrow">READY TO DEMONSTRATE</div>
  <div class="outcome-title">Choose a fictional household story and run it</div>
  <div class="outcome-body">The result will be explained in business language first. The technical tabs remain available underneath as evidence.</div>
  <div class="outcome-takeaway">Start with the Harbor Family straightforward case.</div>
</div>
"""

EMPTY_PATH_HTML = """
<div class="workflow-map"><div class="map-heading">Live workflow path</div><div class="map-subheading">Run a household to light up the path it actually takes.</div></div>
"""

EMPTY_AI_HTML = """
<div class="ai-result"><div class="panel-eyebrow">🤖 BOUNDED AI WORK PRODUCT</div><div class="panel-title">Waiting for a household</div><div class="panel-body">The validated profile category and intake summary will appear here.</div></div>
"""

EMPTY_ROUTING_HTML = """
<div class="why-panel"><div class="panel-eyebrow">WHY DID IT ROUTE HERE?</div><div class="panel-title">Waiting for the review gate</div><div class="panel-body">After a run, this panel will show the exact deterministic reasons for the selected path.</div></div>
"""

EMPTY_JOURNEY_HTML = """
<div class="journey-wrap"><div class="journey-heading">What happened, step by step</div><div class="journey-subheading">After you run a story, this section will translate the workflow engine into an understandable onboarding journey.</div></div>
"""


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
            _build_registry(),
            context=context,
            state_store=STATE_STORE,
        )
        return _app_bundle(run)
    except WorkflowExecutionError as exc:
        return _bundle_with_notice(exc.run, "The onboarding workflow stopped after a controlled failure.")
    except Exception as exc:
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
        return _bundle_with_notice(
            run,
            "This run does not have exactly one open human review. Reload the run and inspect the Human Review table.",
        )

    review = open_reviews[0]
    try:
        updated = submit_human_decision(
            WORKFLOW,
            _build_registry(),
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
        f"### Workflow Status\n{message}",
        run_id,
        [],
        [],
        [],
        {},
        EMPTY_OUTCOME_HTML,
        EMPTY_PATH_HTML,
        EMPTY_AI_HTML,
        EMPTY_ROUTING_HTML,
        EMPTY_JOURNEY_HTML,
    )


def build_app() -> gr.Blocks:
    """Construct the public Gradio application."""

    with gr.Blocks(title="Agent 9 — Wealth Onboarding Workflow") as demo:
        gr.HTML(HERO_HTML)
        gr.HTML(PATTERN_HTML)
        gr.HTML(_ai_runtime_html())

        gr.Markdown("## Try the onboarding pattern in one click")
        gr.Markdown(
            "Pick a fictional household. The app shows the route, AI work product, and routing reasons before the engineering details."
        )
        story = gr.Radio(
            choices=list(STORY_SPECS),
            value="Harbor Family — straightforward household",
            label="Choose an onboarding story",
        )
        story_button = gr.Button("Run This Onboarding Story", variant="primary")

        business_outcome = gr.HTML(EMPTY_OUTCOME_HTML)
        workflow_path = gr.HTML(EMPTY_PATH_HTML)
        with gr.Row():
            ai_insight = gr.HTML(EMPTY_AI_HTML)
            routing_explanation = gr.HTML(EMPTY_ROUTING_HTML)
        business_journey = gr.HTML(EMPTY_JOURNEY_HTML)

        with gr.Accordion("Reload a saved run", open=False):
            gr.Markdown(
                "Every run receives a random ID and is checkpointed in SQLite. Reloading a completed run shows the same state without replaying completed work."
            )
            with gr.Row():
                current_run_id = gr.Textbox(label="Run ID", placeholder="A random run ID appears here after execution.")
                refresh_button = gr.Button("Reload Saved Run")

        with gr.Tabs():
            with gr.Tab("Customize Household"):
                gr.Markdown("### Build your own synthetic onboarding scenario\nThese inputs are fictional and exist only to demonstrate workflow behavior.")
                with gr.Row():
                    household_id = gr.Textbox(label="Household ID", value="HH-DEMO-001")
                    household_type = gr.Dropdown(
                        choices=["INDIVIDUAL", "JOINT", "TRUST", "ENTITY"],
                        value="JOINT",
                        label="Household Type",
                    )
                    documents_complete = gr.Checkbox(label="Onboarding documents complete", value=True)
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
                        choices=["VERIFIED", "REVIEW_REQUIRED"], value="VERIFIED", label="Identity Check Status"
                    )
                    relationship_complexity = gr.Dropdown(
                        choices=["STANDARD", "COMPLEX"], value="STANDARD", label="Relationship Complexity"
                    )
                    simulation_mode = gr.Dropdown(
                        choices=["NONE", "TRANSIENT_ONCE", "PERMANENT"], value="NONE", label="Failure Simulation"
                    )
                gr.Markdown(
                    "**Helpful shortcuts:** TRUST/ENTITY, COMPLEX, missing documents, or REVIEW_REQUIRED demonstrates human review. TRANSIENT_ONCE demonstrates bounded retry recovery."
                )
                run_button = gr.Button("Run Custom Household", variant="primary")

            with gr.Tab("Technical Details"):
                gr.Markdown(
                    "### Engineering view\nInspect exact workflow status, node state, attempt counts, errors, and structured outputs—including the AI Intake Organizer output and its source."
                )
                status = gr.Markdown("### Workflow Status\nRun a synthetic household to begin.")
                node_table = gr.Dataframe(headers=NODE_HEADERS, interactive=False, label="Node Runtime State")
                final_output = gr.JSON(label="Final Output")

            with gr.Tab("Audit Trail"):
                gr.Markdown(
                    "### Why the workflow is auditable\nEvery meaningful control transition is recorded. The audit timeline contains control metadata only; onboarding context is not copied into event details."
                )
                event_table = gr.Dataframe(headers=EVENT_HEADERS, interactive=False, label="Append-Only Workflow Events")

            with gr.Tab("Operations / Compliance Review"):
                gr.Markdown(
                    "### The human remains in control\nA fictional exception case pauses here. The workflow cannot mark the package ready until a person explicitly decides what should happen."
                )
                review_table = gr.Dataframe(headers=REVIEW_HEADERS, interactive=False, label="Human Review History")
                with gr.Row():
                    human_decision = gr.Dropdown(
                        choices=["APPROVE", "REJECT", "RETRY"], value="APPROVE", label="What should the reviewer do?"
                    )
                    decision_button = gr.Button("Submit Human Decision", variant="primary")
                gr.Markdown(
                    "**APPROVE** continues the approved exception path. **REJECT** ends the fictional process as `REJECTED`, not `FAILED`. **RETRY** opens a fresh review without replaying completed upstream work. This is illustrative, not any firm's actual regulatory procedure."
                )

            with gr.Tab("Evaluation"):
                gr.Markdown(
                    "### Reliability evidence\nThe same onboarding engine is exercised across success, retry, human review, persistence, failure, and adversarial-control scenarios."
                )
                evaluation_summary = gr.Markdown("Run the deterministic evaluation harness to inspect system-level metrics.")
                evaluation_button = gr.Button("Run 10-Case Evaluation")
                metric_table = gr.Dataframe(headers=METRIC_HEADERS, interactive=False, label="Evaluation Metrics")
                case_table = gr.Dataframe(headers=CASE_HEADERS, interactive=False, label="Evaluation Cases")

        run_outputs = [
            status,
            current_run_id,
            node_table,
            event_table,
            review_table,
            final_output,
            business_outcome,
            workflow_path,
            ai_insight,
            routing_explanation,
            business_journey,
        ]

        story_button.click(fn=run_story_ui, inputs=[story], outputs=run_outputs)
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
        refresh_button.click(fn=refresh_run_ui, inputs=[current_run_id], outputs=run_outputs)
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
        css=APP_CSS,
    )
