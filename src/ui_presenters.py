"""Presentation helpers for the Agent 9 Gradio demo.

These helpers translate workflow and evaluation objects into display-safe rows.
They intentionally do not expose the workflow context in status tables or the audit
timeline; node outputs, review records, and control-plane events remain separate.
"""

from __future__ import annotations

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


def run_summary(run: WorkflowRun) -> str:
    """Return a concise Markdown summary for one workflow run."""

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
    """Return the standard output bundle consumed by Gradio callbacks."""

    return (
        run_summary(run),
        run.run_id,
        node_rows(run),
        event_rows(run),
        review_rows(run),
        run.final_output or {},
    )


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _metric_text(value: float | int) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
