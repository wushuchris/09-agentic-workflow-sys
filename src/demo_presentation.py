"""Business-first presentation helpers for the Agent 9 Gradio demo."""

from __future__ import annotations

import html

from src.schemas import WorkflowRun

PLAYBACK_DELAY_SECONDS = 0.20

NODE_LABELS = {
    "validate_intake": "Check household intake",
    "ai_intake_organizer": "AI Intake Organizer",
    "document_check": "Check onboarding documents",
    "policy_check": "Apply onboarding rules",
    "create_onboarding_package": "Prepare onboarding package",
    "verify_onboarding_package": "Verify onboarding package",
    "review_gate": "Choose review path",
    "onboarding_ready": "Standard package ready",
    "human_review": "Operations / compliance review",
    "reviewed_onboarding": "Ready after human review",
}

EVENT_LABELS = {
    "WORKFLOW_STARTED": "Workflow started",
    "NODE_STARTED": "Step started",
    "NODE_COMPLETED": "Step completed",
    "NODE_FAILED": "Step stopped safely",
    "NODE_SKIPPED": "Step not needed",
    "DECISION_ROUTED": "Route selected",
    "RETRY_SCHEDULED": "Retry scheduled",
    "HUMAN_REVIEW_REQUESTED": "Human review requested",
    "HUMAN_APPROVED": "Human approved",
    "HUMAN_REJECTED": "Human rejected",
    "WORKFLOW_RESUMED": "Workflow resumed",
    "WORKFLOW_COMPLETED": "Workflow completed",
    "WORKFLOW_FAILED": "Workflow failed closed",
}

EVENT_ICONS = {
    "WORKFLOW_STARTED": "▶", "NODE_STARTED": "→", "NODE_COMPLETED": "✓",
    "NODE_FAILED": "×", "NODE_SKIPPED": "↷", "DECISION_ROUTED": "⇢",
    "RETRY_SCHEDULED": "↻", "HUMAN_REVIEW_REQUESTED": "👤",
    "HUMAN_APPROVED": "✓", "HUMAN_REJECTED": "■", "WORKFLOW_RESUMED": "▶",
    "WORKFLOW_COMPLETED": "✓", "WORKFLOW_FAILED": "×",
}

APP_CSS = """
.gradio-container { max-width:1120px !important; margin:0 auto !important; }
.agent-hero { padding:1.65rem 1.75rem; border:1px solid var(--border-color-primary,rgba(127,127,127,.25)); border-radius:22px; background:linear-gradient(135deg,rgba(249,115,22,.12),rgba(99,102,241,.08)); margin-bottom:1rem; }
.agent-eyebrow,.outcome-eyebrow,.panel-eyebrow { font-size:.76rem; font-weight:800; letter-spacing:.12em; opacity:.72; margin-bottom:.35rem; }
.agent-hero h1 { margin:.25rem 0 .55rem; font-size:2.12rem; line-height:1.16; max-width:820px; }
.agent-hero p { margin:0; max-width:820px; font-size:1.06rem; line-height:1.58; }
.pattern-grid { display:grid; grid-template-columns:1fr; gap:.65rem; margin:1rem 0; }
.pattern-card,.ai-result,.why-panel { padding:1rem 1.1rem; border-radius:14px; border:1px solid var(--border-color-primary,rgba(127,127,127,.25)); background:var(--block-background-fill,rgba(127,127,127,.06)); }
.pattern-card strong { display:block; margin-bottom:.3rem; font-size:1.04rem; }
.pattern-card span { opacity:.80; line-height:1.48; font-size:.96rem; }
.ai-card { border-color:rgba(59,130,246,.55); background:linear-gradient(135deg,rgba(59,130,246,.14),rgba(99,102,241,.09)); }
.ai-runtime { padding:1rem 1.1rem; border-radius:14px; border:1px solid rgba(59,130,246,.38); background:rgba(59,130,246,.08); margin:.7rem 0 1rem; line-height:1.5; }
.ai-runtime-live { border-color:rgba(34,197,94,.45); background:rgba(34,197,94,.08); }
.ai-runtime-waiting { border-color:rgba(245,158,11,.45); background:rgba(245,158,11,.08); }
.pattern-flow { display:flex; flex-direction:column; align-items:stretch; gap:.35rem; margin:.8rem 0 1.2rem; }
.flow-pill { padding:.7rem .85rem; border-radius:12px; border:1px solid var(--border-color-primary,rgba(127,127,127,.25)); background:var(--block-background-fill,rgba(127,127,127,.06)); font-weight:700; font-size:.96rem; }
.ai-pill { border-color:rgba(59,130,246,.6); background:rgba(59,130,246,.12); }
.flow-arrow { align-self:center; opacity:.5; font-weight:800; transform:rotate(90deg); line-height:1; }
.section-note { padding:.9rem 1rem; border-radius:12px; background:rgba(99,102,241,.08); border:1px solid rgba(99,102,241,.18); margin-bottom:.85rem; line-height:1.5; }
.business-outcome { border-radius:16px; padding:1.1rem 1.2rem; border:1px solid var(--border-color-primary,rgba(127,127,127,.25)); margin:.8rem 0; }
.outcome-success { border-left:6px solid #22c55e; background:rgba(34,197,94,.08); }
.outcome-waiting { border-left:6px solid #f59e0b; background:rgba(245,158,11,.08); }
.outcome-rejected { border-left:6px solid #f97316; background:rgba(249,115,22,.08); }
.outcome-failed { border-left:6px solid #ef4444; background:rgba(239,68,68,.08); }
.outcome-neutral { border-left:6px solid #64748b; background:rgba(100,116,139,.08); }
.outcome-title,.panel-title { font-size:1.2rem; font-weight:800; margin-bottom:.4rem; }
.outcome-body,.panel-body { line-height:1.5; margin-bottom:.55rem; }
.outcome-takeaway { font-weight:650; opacity:.83; }
.ai-result-live { border-color:rgba(59,130,246,.6); background:rgba(59,130,246,.09); }
.ai-result-fallback { border-color:rgba(100,116,139,.4); }
.ai-result-failed { border-color:rgba(239,68,68,.45); background:rgba(239,68,68,.07); }
.ai-mode { display:inline-block; padding:.25rem .5rem; border-radius:999px; font-size:.76rem; font-weight:800; background:rgba(59,130,246,.14); margin-bottom:.45rem; }
.ai-model { font-size:.82rem; opacity:.7; margin-bottom:.5rem; }
.ai-category { margin-bottom:.5rem; }
.ai-summary { line-height:1.48; margin-bottom:.6rem; }
.ai-used { font-weight:700; margin-bottom:.45rem; }
.ai-boundary,.why-proof { font-size:.88rem; opacity:.78; line-height:1.4; }
.why-standard { border-left:5px solid #22c55e; }
.why-review { border-left:5px solid #f59e0b; }
.why-list { margin:.35rem 0 .7rem 1.15rem; }
.workflow-map { margin:1rem 0; padding:1rem 1.05rem; border-radius:16px; border:1px solid var(--border-color-primary,rgba(127,127,127,.25)); background:var(--block-background-fill,rgba(127,127,127,.04)); }
.map-heading,.journey-heading { font-size:1.15rem; font-weight:800; }
.map-subheading,.journey-subheading { opacity:.72; margin:.25rem 0 .8rem; line-height:1.45; }
.map-main { display:flex; flex-wrap:wrap; align-items:center; gap:.42rem; }
.map-split { display:grid; grid-template-columns:1fr; gap:.75rem; margin-top:.85rem; }
.map-branch { padding:.75rem; border-radius:12px; border:1px dashed var(--border-color-primary,rgba(127,127,127,.28)); }
.branch-label { font-size:.72rem; font-weight:800; letter-spacing:.08em; opacity:.65; margin-bottom:.45rem; }
.map-node { display:inline-block; padding:.42rem .62rem; border-radius:10px; border:1px solid rgba(100,116,139,.35); background:rgba(100,116,139,.08); font-size:.84rem; font-weight:700; }
.map-node-completed { border-color:rgba(34,197,94,.55); background:rgba(34,197,94,.12); }
.map-node-waiting-for-human,.map-node-retry-scheduled,.map-node-running { border-color:rgba(245,158,11,.6); background:rgba(245,158,11,.12); }
.map-node-failed { border-color:rgba(239,68,68,.6); background:rgba(239,68,68,.12); }
.map-node-skipped,.map-node-pending,.map-node-ready { opacity:.42; }
.map-node-ai { box-shadow:inset 0 0 0 2px rgba(59,130,246,.62); }
.map-arrow { opacity:.5; font-weight:800; }
.map-legend { margin-top:.8rem; font-size:.8rem; opacity:.65; }
.journey-wrap { padding:1rem 0 .2rem; }
.journey-grid { display:grid; grid-template-columns:1fr; gap:.65rem; }
.journey-step { display:flex; gap:.7rem; padding:.85rem .9rem; border-radius:12px; border:1px solid var(--border-color-primary,rgba(127,127,127,.22)); background:var(--block-background-fill,rgba(127,127,127,.04)); }
.journey-icon { width:30px; height:30px; min-width:30px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:900; }
.journey-done { background:rgba(34,197,94,.16); } .journey-waiting { background:rgba(245,158,11,.18); } .journey-rejected { background:rgba(249,115,22,.18); } .journey-failed { background:rgba(239,68,68,.18); } .journey-skipped { background:rgba(100,116,139,.16); } .journey-pending { background:rgba(100,116,139,.10); }
.journey-title { font-weight:750; } .journey-state { font-size:.8rem; font-weight:700; opacity:.78; margin:.1rem 0 .2rem; } .journey-description { font-size:.9rem; opacity:.74; line-height:1.42; }
.activity-card { border:1px solid rgba(59,130,246,.30); border-radius:18px; padding:17px 19px; margin:14px 0 18px; background:linear-gradient(135deg,rgba(59,130,246,.08),rgba(99,102,241,.035)); }
.activity-head { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
.activity-spinner { width:24px; height:24px; box-sizing:border-box; border:4px solid rgba(59,130,246,.18); border-top-color:#3b82f6; border-right-color:#6366f1; border-radius:50%; animation:workflow-spin .78s linear infinite; flex:0 0 auto; }
.activity-badge { display:inline-block; border:1px solid rgba(59,130,246,.42); border-radius:999px; padding:4px 8px; font-size:.72rem; font-weight:850; letter-spacing:.09em; }
.activity-title { font-size:1.07rem; font-weight:800; } .activity-sub { font-size:.92rem; opacity:.79; line-height:1.4; margin-bottom:10px; }
.activity-track { height:8px; background:rgba(148,163,184,.18); border-radius:999px; overflow:hidden; margin:10px 0 13px; }
.activity-fill { height:100%; background:linear-gradient(90deg,#3b82f6,#6366f1); transition:width .2s ease; }
.activity-track.indeterminate .activity-fill { width:34%; animation:workflow-slide 1.05s ease-in-out infinite; }
.activity-feed { display:grid; gap:6px; } .activity-feed.activity-scroll { max-height:430px; overflow-y:auto; padding-right:7px; scrollbar-gutter:stable; }
.activity-event { display:grid; grid-template-columns:28px minmax(0,1fr); gap:8px; padding-top:8px; border-top:1px solid rgba(148,163,184,.16); } .activity-event:first-child { border-top:0; padding-top:0; }
.activity-icon { font-weight:850; line-height:1.45; text-align:center; } .activity-main { font-size:.94rem; line-height:1.4; } .activity-main strong { font-weight:800; } .activity-meta { font-size:.78rem; opacity:.66; margin-top:2px; }
.activity-complete { border-color:rgba(34,197,94,.35); background:linear-gradient(135deg,rgba(34,197,94,.08),rgba(59,130,246,.035)); } .activity-scroll-note { font-size:.82rem; opacity:.72; margin-bottom:8px; }
@keyframes workflow-spin { to { transform:rotate(360deg); } } @keyframes workflow-slide { 0% { transform:translateX(-110%); } 50% { transform:translateX(205%); } 100% { transform:translateX(-110%); } }
@media (max-width:700px) { .gradio-container { max-width:100% !important; } .agent-hero { padding:1.3rem 1.1rem; } .agent-hero h1 { font-size:1.75rem; } }
"""

HERO_HTML = """
<div class="agent-hero">
  <div class="agent-eyebrow">AGENT 9 • BUSINESS + ENGINEERING DEMO • SYNTHETIC DATA</div>
  <h1>How can AI help onboard a household without controlling the process?</h1>
  <p>A fictional wealth-management operations team needs to move a new household through onboarding. AI may organize the unstructured intake into useful work product, but application code controls sequencing, retries, routing, persistence, and the human-review boundary.</p>
</div>
"""

PATTERN_HTML = """
<div class="pattern-grid">
  <div class="pattern-card ai-card"><strong>🤖 AI prepares useful work</strong><span>The bounded AI node creates a profile category and concise intake summary for the simulated onboarding package.</span></div>
  <div class="pattern-card"><strong>✓ Software controls consequences</strong><span>Document checks, exception rules, routes, retries, checkpoints, and allowed next steps remain deterministic.</span></div>
  <div class="pattern-card"><strong>👤 A person owns exceptions</strong><span>Trust, entity, complex, missing-document, or identity-review cases pause until an explicit human decision is recorded.</span></div>
  <div class="pattern-card"><strong>↻ Operations recover safely</strong><span>Temporary service failures retry within policy; permanent failures stop before uncertain downstream work continues.</span></div>
</div>
<div class="section-note"><strong>The operating model:</strong> AI contributes work. Application code governs the process. Humans retain authority over consequential exceptions.</div>
<div class="pattern-flow">
  <span class="flow-pill">1 · Household intake</span><span class="flow-arrow">→</span>
  <span class="flow-pill ai-pill">2 · 🤖 AI organizes the intake</span><span class="flow-arrow">→</span>
  <span class="flow-pill">3 · Rules prepare and verify the package</span><span class="flow-arrow">→</span>
  <span class="flow-pill">4 · Standard path or explicit human review</span>
</div>
"""

EMPTY_OUTCOME_HTML = """<div class="business-outcome outcome-neutral"><div class="outcome-eyebrow">READY TO DEMONSTRATE</div><div class="outcome-title">Choose a fictional household story and run it</div><div class="outcome-body">The result will be explained in business language first. The engineering tabs remain available underneath as evidence.</div><div class="outcome-takeaway">Start with the Harbor Family straightforward case.</div></div>"""
EMPTY_PATH_HTML = """<div class="workflow-map"><div class="map-heading">Workflow path</div><div class="map-subheading">Run a household to light up the path it actually takes.</div></div>"""
EMPTY_AI_HTML = """<div class="ai-result"><div class="panel-eyebrow">🤖 BOUNDED AI WORK PRODUCT</div><div class="panel-title">Waiting for a household</div><div class="panel-body">The validated profile category and intake summary will appear here.</div></div>"""
EMPTY_ROUTING_HTML = """<div class="why-panel"><div class="panel-eyebrow">WHY DID IT ROUTE HERE?</div><div class="panel-title">Waiting for the review gate</div><div class="panel-body">After a run, this panel will show the exact deterministic reasons for the selected path.</div></div>"""
EMPTY_JOURNEY_HTML = """<div class="journey-wrap"><div class="journey-heading">What happened, step by step</div><div class="journey-subheading">After you run a story, this section will translate the workflow engine into an understandable onboarding journey.</div></div>"""
EMPTY_ACTIVITY_HTML = """<div class="activity-card"><div class="activity-title">Live workflow activity</div><div class="activity-sub">Run a household to watch the workflow's real append-only control events replay here at a readable pace.</div></div>"""


def activity_start_html(label: str) -> str:
    return f"""<div class="activity-card"><div class="activity-head"><span class="activity-spinner"></span><span class="activity-badge">RUNNING</span><span class="activity-title">Workflow engine is running</span></div><div class="activity-sub">{html.escape(label)} · deterministic workflow control is executing. Real audit events from this exact run will appear here.</div><div class="activity-track indeterminate"><div class="activity-fill"></div></div><div class="activity-feed"><div class="activity-event"><div class="activity-icon">…</div><div class="activity-main">Preparing the workflow run and its persisted event trace.</div></div></div></div>"""


def _event_text(event) -> tuple[str, str, str]:
    event_type = event.event_type.value
    label = EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())
    node_label = NODE_LABELS.get(event.node_id or "", (event.node_id or "Workflow").replace("_", " ").title())
    return EVENT_ICONS.get(event_type, "•"), label, node_label


def activity_html(run: WorkflowRun, count: int, *, complete: bool = False) -> str:
    total = max(len(run.events), 1)
    visible_count = min(max(count, 0), len(run.events))
    percent = min(100.0, (visible_count / total) * 100)
    rows = run.events if complete else run.events[max(0, visible_count - 8):visible_count]
    if complete:
        badge = "STOPPED" if run.status.value == "FAILED" else "COMPLETE"
        title = "Workflow event trace complete"
        sub = f"{len(run.events)} real append-only workflow events retained. Scroll inside the transcript to review the full run."
        spinner = ""
        card_class = "activity-card activity-complete"
        note = '<div class="activity-scroll-note">Scroll inside this panel to review the complete workflow event transcript.</div>'
        feed_class = "activity-feed activity-scroll"
    else:
        current = run.events[visible_count - 1] if visible_count else None
        if current is None:
            sub = "Waiting for the first workflow event."
        else:
            _, event_label, node_label = _event_text(current)
            sub = f"Event {visible_count}/{len(run.events)} · {event_label} · {node_label}"
        badge, title = "RUNNING", "Workflow activity"
        spinner = '<span class="activity-spinner"></span>'
        card_class, note, feed_class = "activity-card", "", "activity-feed"
    start = 1 if complete else max(1, visible_count - len(rows) + 1)
    feed_rows = []
    for index, event in enumerate(rows, start=start):
        icon, event_label, node_label = _event_text(event)
        feed_rows.append(f'<div class="activity-event"><div class="activity-icon">{html.escape(icon)}</div><div class="activity-main"><strong>{html.escape(event_label)}</strong><br>{html.escape(node_label)}<div class="activity-meta">Event {index} · {html.escape(event.event_type.value)}</div></div></div>')
    feed = "".join(feed_rows) or '<div class="activity-event"><div class="activity-icon">…</div><div class="activity-main">Waiting for the first workflow event.</div></div>'
    return f'<div class="{card_class}"><div class="activity-head">{spinner}<span class="activity-badge">{badge}</span><span class="activity-title">{html.escape(title)}</span></div><div class="activity-sub">{html.escape(sub)}</div><div class="activity-track"><div class="activity-fill" style="width:{percent:.1f}%"></div></div>{note}<div class="{feed_class}">{feed}</div></div>'


def playback_delay(event_type: str, base: float = PLAYBACK_DELAY_SECONDS) -> float:
    if base <= 0:
        return 0
    if event_type in {"WORKFLOW_STARTED", "WORKFLOW_RESUMED"}:
        return base * 1.5
    if event_type in {"DECISION_ROUTED", "RETRY_SCHEDULED", "HUMAN_REVIEW_REQUESTED"}:
        return base * 2.0
    if event_type in {"WORKFLOW_COMPLETED", "WORKFLOW_FAILED", "HUMAN_APPROVED", "HUMAN_REJECTED"}:
        return base * 2.4
    return base
