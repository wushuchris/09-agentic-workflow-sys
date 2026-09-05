"""Presentation helpers for the Agent 9 Gradio demo.

These helpers translate workflow and evaluation objects into display-safe views.
The business presenters explain the fictional wealth-onboarding workflow in plain
English, while the technical presenters preserve node, review, and audit evidence.
Workflow context is never copied into the audit timeline.
"""

from __future__ import annotations

import html
import json
from typing import Any

from src.evaluation import EvaluationReport
from src.schemas import WorkflowRun, WorkflowStatus


NODE_HEADERS = ["Node", "Status", "Attempt", "Error", "Output"]
EVENT_HEADERS = ["Timestamp (UTC)", "Event", "Node", "Details"]
REVIEW_HEADERS = [
    "Review ID",
    "Node",
    "Decision",
    "Reason",
    "Requested At (UTC)",
    "Decided At (UTC)",
]
METRIC_HEADERS = ["Metric", "Value"]
CASE_HEADERS = ["Case", "Category", "Passed", "Expected", "Observed"]

BUSINESS_STEPS = [
    ("validate_intake", "Check the household intake", "Make sure the fictional intake is complete and usable."),
    ("ai_intake_organizer", "🤖 AI Intake Organizer", "Organize synthetic notes into a bounded household profile and summary."),
    ("document_check", "Check onboarding documents", "Record whether the fictional document set is complete."),
    ("policy_check", "Apply onboarding rules", "Identify deterministic exception reasons that require extra review."),
    ("create_onboarding_package", "Prepare the onboarding package", "Create a simulated package with bounded retry protection."),
    ("verify_onboarding_package", "Verify the package", "Confirm the simulated onboarding package was prepared correctly."),
    ("review_gate", "Choose the review path", "Route only between the approved standard path and human-review path."),
    ("onboarding_ready", "Standard package ready", "Mark a straightforward fictional household ready for advisor review."),
    ("human_review", "Operations / compliance review", "Pause exception cases until an explicit person decides."),
    ("reviewed_onboarding", "Ready after human review", "Continue only after an exception case is explicitly approved."),
]

_EXCEPTION_LABELS = {
    "MISSING_DOCUMENTS": "missing onboarding documents",
    "IDENTITY_REVIEW_REQUIRED": "identity information needs review",
    "COMPLEX_RELATIONSHIP": "the relationship is marked complex",
    "SPECIAL_STRUCTURE": "the household uses a special structure",
}


def run_summary(run: WorkflowRun) -> str:
    """Return a concise technical Markdown summary for one workflow run."""

    completed = sum(node.status.value == "COMPLETED" for node in run.node_runs.values())
    skipped = sum(node.status.value == "SKIPPED" for node in run.node_runs.values())
    failed = sum(node.status.value == "FAILED" for node in run.node_runs.values())
    waiting_reviews = sum(review.decision is None for review in run.human_reviews)

    lines = [
        f"### Run `{run.run_id}`",
        f"**Workflow:** `{run.workflow_id}` v`{run.workflow_version}`  ",
        f"**Status:** `{run.status.value}`  ",
        f"**Nodes:** {completed} completed · {skipped} skipped · {failed} failed  ",
        f"**Events:** {len(run.events)} · **Open human reviews:** {waiting_reviews}",
    ]

    if run.status is WorkflowStatus.WAITING_FOR_HUMAN:
        lines.append("\n**Action required:** an explicit operations/compliance decision is required before the workflow can continue.")
    elif run.status is WorkflowStatus.REJECTED:
        lines.append("\nThe fictional onboarding process was rejected by a human reviewer; this is not a technical failure.")
    elif run.status is WorkflowStatus.FAILED:
        lines.append("\nThe onboarding workflow stopped safely after a controlled failure.")

    return "\n".join(lines)


def business_outcome_html(run: WorkflowRun) -> str:
    """Explain the current onboarding outcome without requiring workflow terminology."""

    review_route = _review_route(run)
    attempts = _package_attempts(run)

    if run.status is WorkflowStatus.WAITING_FOR_HUMAN:
        tone = "waiting"
        eyebrow = "HUMAN CHECKPOINT"
        title = "An onboarding exception needs a person"
        body = (
            "The routine preparation steps are complete, but one or more deterministic "
            "exception rules require operations or compliance review. Automation is paused "
            "and cannot mark the package ready on its own."
        )
        takeaway = "Pattern shown: AI can organize intake, but people retain authority over exception decisions."
    elif run.status is WorkflowStatus.REJECTED:
        tone = "rejected"
        eyebrow = "BUSINESS DECISION"
        title = "The reviewer stopped this onboarding case"
        body = (
            "A person rejected the fictional exception case. The workflow ended intentionally; "
            "nothing crashed and the reviewed-ready step did not run."
        )
        takeaway = "Pattern shown: a valid human business decision is different from a technical failure."
    elif run.status is WorkflowStatus.FAILED:
        tone = "failed"
        eyebrow = "SAFE FAILURE"
        title = "The onboarding workflow stopped safely"
        body = (
            "A permanent simulated dependency problem occurred. Instead of continuing with an "
            "uncertain package, the workflow contained the failure and blocked later steps."
        )
        takeaway = "Pattern shown: failures are contained instead of cascading through an onboarding process."
    elif run.status is WorkflowStatus.COMPLETED and review_route == "REVIEW_REQUIRED":
        tone = "success"
        eyebrow = "HUMAN-GUIDED COMPLETION"
        title = "The onboarding package is ready after human review"
        body = (
            "Automation prepared and verified the fictional package, paused at the exception gate, "
            "and resumed only after an explicit human approval."
        )
        takeaway = "Pattern shown: automation handles the process while a person retains authority over exceptions."
    elif run.status is WorkflowStatus.COMPLETED and attempts > 1:
        tone = "success"
        eyebrow = "AUTOMATIC RECOVERY"
        title = "A temporary onboarding-service problem occurred — and recovered"
        body = (
            f"Package preparation needed {attempts} attempts. The bounded retry policy handled "
            "the temporary interruption and the fictional onboarding package still reached the standard ready path."
        )
        takeaway = "Pattern shown: temporary operational failures can recover without an endless retry loop."
    elif run.status is WorkflowStatus.COMPLETED:
        tone = "success"
        eyebrow = "STRAIGHTFORWARD ONBOARDING"
        title = "The fictional household package is ready for advisor review"
        body = (
            "The intake was valid, the package was prepared and verified, and no deterministic "
            "exception rule required an additional operations/compliance checkpoint."
        )
        takeaway = "Pattern shown: routine preparation can move automatically while consequential exceptions stay human-controlled."
    else:
        tone = "neutral"
        eyebrow = "WORKFLOW IN PROGRESS"
        title = "The onboarding workflow is processing the household"
        body = "Application code is controlling the order of work, state changes, and approved next steps."
        takeaway = "Pattern shown: AI assists inside a bounded step; it does not improvise the onboarding process."

    return (
        f'<div class="business-outcome outcome-{tone}">'
        f'<div class="outcome-eyebrow">{html.escape(eyebrow)}</div>'
        f'<div class="outcome-title">{html.escape(title)}</div>'
        f'<div class="outcome-body">{html.escape(body)}</div>'
        f'<div class="outcome-takeaway">{html.escape(takeaway)}</div>'
        "</div>"
    )


def business_journey_html(run: WorkflowRun) -> str:
    """Render technical node state as an understandable onboarding journey."""

    cards: list[str] = []
    for node_id, title, description in BUSINESS_STEPS:
        icon, state_label, tone = _friendly_node_state(run, node_id)
        detail = _friendly_node_detail(run, node_id)
        cards.append(
            '<div class="journey-step">'
            f'<div class="journey-icon journey-{tone}">{icon}</div>'
            '<div class="journey-copy">'
            f'<div class="journey-title">{html.escape(title)}</div>'
            f'<div class="journey-state">{html.escape(state_label)}</div>'
            f'<div class="journey-description">{html.escape(detail or description)}</div>'
            "</div></div>"
        )

    return (
        '<div class="journey-wrap">'
        '<div class="journey-heading">What happened, step by step</div>'
        '<div class="journey-subheading">The AI step interprets intake only. Deterministic rules decide whether the fictional household stays on the standard path or pauses for a person.</div>'
        f'<div class="journey-grid">{"".join(cards)}</div>'
        "</div>"
    )


def node_rows(run: WorkflowRun) -> list[list[Any]]:
    """Return display rows for node runtime state without workflow context."""

    rows: list[list[Any]] = []
    for node_id, node in run.node_runs.items():
        rows.append(
            [
                node_id,
                node.status.value,
                node.attempt,
                node.error or "",
                _json_text(node.output),
            ]
        )
    return rows


def event_rows(run: WorkflowRun) -> list[list[str]]:
    """Return append-only audit events as control-metadata rows."""

    return [
        [
            event.timestamp.isoformat(),
            event.event_type.value,
            event.node_id or "",
            _json_text(event.details),
        ]
        for event in run.events
    ]


def review_rows(run: WorkflowRun) -> list[list[str]]:
    """Return structured human-review history for display."""

    return [
        [
            review.review_id,
            review.node_id,
            review.decision.value if review.decision is not None else "OPEN",
            review.reason,
            review.requested_at.isoformat(),
            review.decided_at.isoformat() if review.decided_at is not None else "",
        ]
        for review in run.human_reviews
    ]


def evaluation_metric_rows(report: EvaluationReport) -> list[list[str]]:
    """Return sorted evaluation metrics for a compact UI table."""

    rows = [["total_cases", str(report.total_cases)]]
    rows.extend(
        [metric_name, _metric_text(metric_value)]
        for metric_name, metric_value in sorted(report.metrics.items())
    )
    return rows


def evaluation_case_rows(report: EvaluationReport) -> list[list[str]]:
    """Return readable evaluation case summaries without raw test payloads."""

    return [
        [
            case.case_id,
            case.category,
            "PASS" if case.passed else "FAIL",
            case.expected,
            case.observed,
        ]
        for case in report.cases
    ]


def run_bundle(run: WorkflowRun) -> tuple[
    str,
    str,
    list[list[Any]],
    list[list[str]],
    list[list[str]],
    dict[str, Any],
]:
    """Return the standard technical output bundle consumed by Gradio callbacks."""

    return (
        run_summary(run),
        run.run_id,
        node_rows(run),
        event_rows(run),
        review_rows(run),
        run.final_output or {},
    )


def _review_route(run: WorkflowRun) -> str | None:
    node = run.node_runs.get("review_gate")
    if node is None or not isinstance(node.output, dict):
        return None
    route = node.output.get("route")
    return str(route) if route is not None else None


def _package_attempts(run: WorkflowRun) -> int:
    node = run.node_runs.get("create_onboarding_package")
    return node.attempt if node is not None else 0


def _latest_review_decision(run: WorkflowRun) -> str | None:
    if not run.human_reviews:
        return None
    decision = run.human_reviews[-1].decision
    return decision.value if decision is not None else None


def _friendly_node_state(run: WorkflowRun, node_id: str) -> tuple[str, str, str]:
    node = run.node_runs.get(node_id)
    if node is None:
        return "•", "Not reached", "pending"

    status = node.status.value
    if status == "COMPLETED":
        if node_id == "human_review":
            decision = _latest_review_decision(run)
            if decision == "APPROVE":
                return "✓", "Approved by a person", "done"
            if decision == "REJECT":
                return "■", "Rejected by a person", "rejected"
        if node_id == "create_onboarding_package" and node.attempt > 1:
            return "↻", f"Recovered on attempt {node.attempt}", "done"
        return "✓", "Done", "done"
    if status == "WAITING_FOR_HUMAN":
        return "!", "Waiting for a person", "waiting"
    if status == "SKIPPED":
        return "↷", "Not needed on this path", "skipped"
    if status == "FAILED":
        return "×", "Stopped safely here", "failed"
    if status == "RETRY_SCHEDULED":
        return "↻", "Retry scheduled", "waiting"
    if status == "RUNNING":
        return "…", "In progress", "waiting"
    return "•", "Not reached", "pending"


def _friendly_node_detail(run: WorkflowRun, node_id: str) -> str | None:
    node = run.node_runs.get(node_id)
    if node is None:
        return None

    if node_id == "ai_intake_organizer" and isinstance(node.output, dict):
        source = node.output.get("source")
        category = node.output.get("profile_category")
        if source == "MODEL_ASSISTED":
            return f"A live bounded model organized the intake and proposed {category}; it did not receive routing or approval controls."
        if source == "DETERMINISTIC_FALLBACK":
            return f"This is the AI-capable boundary. The public demo used the deterministic fallback and produced {category}; a live model can be connected without changing workflow control."

    if node_id == "create_onboarding_package" and node.status.value == "COMPLETED":
        if node.attempt > 1:
            return f"A temporary service problem occurred, but the bounded retry policy recovered in {node.attempt} attempts."
        return "The fictional onboarding package was prepared on the first attempt."

    if node_id == "review_gate" and isinstance(node.output, dict):
        route = node.output.get("route")
        reasons = node.output.get("exception_reasons") or []
        if route == "REVIEW_REQUIRED":
            friendly = [_EXCEPTION_LABELS.get(str(reason), str(reason).lower()) for reason in reasons]
            reason_text = ", ".join(friendly) if friendly else "an onboarding exception"
            return f"Deterministic rules found {reason_text}, so the standard-ready path was blocked."
        if route == "STANDARD_PATH":
            return "Deterministic rules found no exception requiring the extra human-review path."

    if node_id == "human_review":
        decision = _latest_review_decision(run)
        if node.status.value == "WAITING_FOR_HUMAN":
            return "The workflow is deliberately paused and cannot mark the package ready on its own."
        if decision == "APPROVE":
            return "A person explicitly approved the exception case, allowing the workflow to resume."
        if decision == "REJECT":
            return "A person explicitly rejected the exception case, ending the fictional onboarding process."
        if decision == "RETRY":
            return "A person requested another review cycle without replaying upstream work."

    if node_id == "onboarding_ready" and node.status.value == "COMPLETED":
        return "The straightforward fictional package is ready for the next advisor-facing step; no account is actually opened."
    if node_id == "reviewed_onboarding" and node.status.value == "COMPLETED":
        return "The exception package is ready only because a person explicitly approved it; no account is actually opened."
    if node.status.value == "SKIPPED":
        return "This step belongs to the other approved branch, so it was intentionally skipped."
    if node.status.value == "FAILED":
        return "The workflow contained the problem here and did not continue into later onboarding work."
    return None


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _metric_text(value: float | int) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
