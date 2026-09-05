"""Presentation helpers for the Agent 9 Gradio demo.

These helpers translate workflow and evaluation objects into display-safe views.
The business presenters explain the workflow in plain English, while the technical
presenters preserve node, review, and audit evidence. Workflow context is never
copied into the audit timeline.
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
    ("validate_request", "Check the request", "Make sure the request is complete and usable."),
    ("classify_request", "Understand the request", "Place the request into an approved category."),
    ("policy_check", "Apply business policy", "Confirm the request is allowed to continue."),
    ("perform_automated_task", "Do the work", "Perform the simulated service action with bounded retries."),
    ("verify_result", "Verify the result", "Check that the automated action actually succeeded."),
    ("risk_gate", "Assess risk", "Choose only between the approved low-risk and high-risk paths."),
    ("low_risk_finalize", "Finish automatically", "Complete routine work without unnecessary human review."),
    ("human_review", "Ask a person", "Pause high-risk work until an explicit human decision is recorded."),
    ("high_risk_finalize", "Finish after approval", "Continue high-risk work only after a person approves it."),
]


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
        lines.append("\n**Action required:** submit an explicit human decision before the workflow can continue.")
    elif run.status is WorkflowStatus.REJECTED:
        lines.append("\nThe business process was rejected by a human reviewer; this is not a technical failure.")
    elif run.status is WorkflowStatus.FAILED:
        lines.append("\nThe workflow stopped safely after a controlled failure.")

    return "\n".join(lines)


def business_outcome_html(run: WorkflowRun) -> str:
    """Explain the current business outcome without requiring workflow terminology."""

    risk_route = _risk_route(run)
    attempts = _task_attempts(run)

    if run.status is WorkflowStatus.WAITING_FOR_HUMAN:
        tone = "waiting"
        eyebrow = "HUMAN CHECKPOINT"
        title = "A person needs to decide before this can continue"
        body = (
            "The request crossed the workflow's risk threshold. Automation has paused "
            "and cannot move forward until a person explicitly approves, rejects, or "
            "re-opens the review."
        )
        takeaway = "Pattern shown: automate routine work, but keep people in control of high-risk decisions."
    elif run.status is WorkflowStatus.REJECTED:
        tone = "rejected"
        eyebrow = "BUSINESS DECISION"
        title = "The reviewer stopped the request"
        body = (
            "A person rejected the high-risk request. The workflow ended intentionally; "
            "nothing crashed and downstream work did not continue."
        )
        takeaway = "Pattern shown: a valid business rejection is different from a technical failure."
    elif run.status is WorkflowStatus.FAILED:
        tone = "failed"
        eyebrow = "SAFE FAILURE"
        title = "The workflow stopped safely"
        body = (
            "A permanent problem occurred. Instead of continuing with uncertain state, "
            "the workflow contained the failure and prevented later steps from running."
        )
        takeaway = "Pattern shown: failures are contained instead of cascading through the process."
    elif run.status is WorkflowStatus.COMPLETED and risk_route == "HIGH_RISK":
        tone = "success"
        eyebrow = "HUMAN-GUIDED COMPLETION"
        title = "Completed after a person approved the high-risk request"
        body = (
            "Automation handled the routine steps, paused at the risk gate, and resumed "
            "only after an explicit human approval."
        )
        takeaway = "Pattern shown: automation handles the process; a person retains final authority when risk is high."
    elif run.status is WorkflowStatus.COMPLETED and attempts > 1:
        tone = "success"
        eyebrow = "AUTOMATIC RECOVERY"
        title = "A temporary problem happened — and the workflow recovered"
        body = (
            f"The automated task needed {attempts} attempts. The retry policy handled the "
            "temporary interruption within its limit, and the request still completed safely."
        )
        takeaway = "Pattern shown: temporary failures can recover automatically without creating an infinite retry loop."
    elif run.status is WorkflowStatus.COMPLETED:
        tone = "success"
        eyebrow = "ROUTINE AUTOMATION"
        title = "Completed automatically — no human review was needed"
        body = (
            "The request stayed within policy, the work was verified, and the risk check "
            "allowed the workflow to finish on the automatic path."
        )
        takeaway = "Pattern shown: people are not pulled into routine work when policy says automation is safe."
    else:
        tone = "neutral"
        eyebrow = "WORKFLOW IN PROGRESS"
        title = "The workflow is processing the request"
        body = "Application code is controlling the order of work, state changes, and allowed next steps."
        takeaway = "Pattern shown: the workflow engine controls the process rather than letting a model improvise the sequence."

    return (
        f'<div class="business-outcome outcome-{tone}">'
        f'<div class="outcome-eyebrow">{html.escape(eyebrow)}</div>'
        f'<div class="outcome-title">{html.escape(title)}</div>'
        f'<div class="outcome-body">{html.escape(body)}</div>'
        f'<div class="outcome-takeaway">{html.escape(takeaway)}</div>'
        "</div>"
    )


def business_journey_html(run: WorkflowRun) -> str:
    """Render the technical node state as an understandable business journey."""

    cards: list[str] = []
    for node_id, title, description in BUSINESS_STEPS:
        node = run.node_runs.get(node_id)
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
        '<div class="journey-subheading">The two finish paths are deliberate: routine work can auto-finish; high-risk work must go through a person.</div>'
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


def _risk_route(run: WorkflowRun) -> str | None:
    node = run.node_runs.get("risk_gate")
    if node is None or not isinstance(node.output, dict):
        return None
    route = node.output.get("route")
    return str(route) if route is not None else None


def _task_attempts(run: WorkflowRun) -> int:
    node = run.node_runs.get("perform_automated_task")
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
        if node_id == "perform_automated_task" and node.attempt > 1:
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

    if node_id == "perform_automated_task" and node.status.value == "COMPLETED":
        if node.attempt > 1:
            return f"A temporary problem occurred, but the bounded retry policy recovered in {node.attempt} attempts."
        return "The simulated business action completed on the first attempt."

    if node_id == "risk_gate" and isinstance(node.output, dict):
        route = node.output.get("route")
        if route == "HIGH_RISK":
            return "The request was classified as high risk, so the automatic finish path was blocked."
        if route == "LOW_RISK":
            return "The request stayed within the automatic path, so no human approval was required."

    if node_id == "human_review":
        decision = _latest_review_decision(run)
        if node.status.value == "WAITING_FOR_HUMAN":
            return "The workflow is deliberately paused and cannot continue on its own."
        if decision == "APPROVE":
            return "A person explicitly approved the request, allowing the workflow to resume."
        if decision == "REJECT":
            return "A person explicitly rejected the request, ending the business process."
        if decision == "RETRY":
            return "A person requested another review cycle without replaying upstream work."

    if node_id == "low_risk_finalize" and node.status.value == "COMPLETED":
        return "Routine work finished automatically under the approved policy path."
    if node_id == "high_risk_finalize" and node.status.value == "COMPLETED":
        return "High-risk work finished only after explicit human approval."
    if node.status.value == "SKIPPED":
        return "This step belongs to the other approved branch, so it was intentionally skipped."
    if node.status.value == "FAILED":
        return "The workflow contained the problem here and did not continue into later work."
    return None


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _metric_text(value: float | int) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
