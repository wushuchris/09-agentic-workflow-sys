---
title: Agent 9 — Agentic Workflow System
emoji: ⚙️
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 6.26.0
app_file: app.py
pinned: false
license: mit
---

# Agent 9 — Agentic Workflow System

[![CI](https://github.com/wushuchris/09-agentic-workflow-sys/actions/workflows/ci.yml/badge.svg)](https://github.com/wushuchris/09-agentic-workflow-sys/actions/workflows/ci.yml)

**Hugging Face Space:** https://huggingface.co/spaces/FlyingNunchucks/09-agentic-workflow-sys

A deterministic, resumable, and auditable workflow runtime for AI-assisted business processes.

## Problem

AI systems can perform individual tasks, but reliable business processes require more than model reasoning. Production workflows need explicit sequencing, validated state transitions, bounded retries, durable checkpoints, failure handling, human approval gates, and an auditable event history.

This project explores that engineering boundary by building a small workflow runtime where models may assist with bounded tasks, but application code controls execution.

## Core Engineering Principle

> Models may propose and reason. Application code owns workflow state, validation, execution order, retries, escalation, and completion.

The workflow engine—not the language model—decides what may run next.

## Demo Scenario — Fictional Wealth Management Household Onboarding

The public demo follows a fully synthetic household through a hypothetical wealth-management onboarding process. It is designed to illustrate workflow engineering, not to represent any firm's real compliance program or to open an actual account.

```text
Synthetic household intake
          ↓
Validate intake
          ↓
🤖 AI Intake Organizer
          ↓
Check documents
          ↓
Apply deterministic onboarding rules
          ↓
Prepare onboarding package
          ↓
Verify package
          ↓
Review gate
     ↙              ↘
Standard         Exception
   ↓                ↓
Ready for      Human operations /
advisor review compliance review
                    ↓
              Approve / Reject
                    ↓
             Ready after review
```

The demo contains no real clients, accounts, trades, KYC/AML service calls, money movement, or proprietary data.

### Four one-click stories

- **Straightforward household** — the fictional package becomes ready on the standard path.
- **Temporary service problem** — package preparation fails once, retries within policy, and recovers.
- **Trust / complex household** — deterministic exception rules pause the workflow for a person.
- **Permanent dependency failure** — the workflow stops safely before uncertain downstream work runs.

## Where AI Is Implemented

The `AI Intake Organizer` is the intentionally narrow model boundary.

A model may receive only:

- fictional household type,
- synthetic onboarding notes.

It may return only strict JSON containing:

- an approved household-profile category,
- a short intake summary.

Pydantic rejects malformed output, invented categories, and extra control fields.

```text
synthetic intake notes
        ↓
🤖 model proposes profile + summary
        ↓
strict schema validation
        ↓
normalized bounded output
        ↓
deterministic workflow continues
```

The AI does **not** receive or control:

- document-completeness flags,
- identity-review status,
- relationship-complexity routing rules,
- DAG structure,
- route targets,
- handler identifiers,
- retry limits,
- workflow state,
- or human approval decisions.

The current public demo uses a deterministic fallback at this AI-capable node unless a live provider callable is connected. The provider boundary is deliberately separate from workflow control so a model can be added or changed without changing the engine's state-transition rules.

## Architecture

### 1. Structured Workflow Definition

Typed schemas define workflow nodes, dependencies, retry policies, workflow runs, node runs, events, and human-review decisions.

A workflow definition describes what **may** happen. A workflow run records what **did** happen.

### 2. DAG Validation

Before execution, deterministic validation rejects invalid workflow definitions such as duplicate node identifiers, unknown dependencies, cycles, invalid decision routes, unsupported branch reconvergence, invalid retry policies, and malformed definitions.

Invalid workflows fail before any task executes.

### 3. Handler Registry

Workflow task handlers are explicitly registered and allowlisted. A workflow cannot invoke an arbitrary model-generated function name.

### 4. Workflow Executor

The executor determines which nodes are ready, completed, skipped, failed, retryable, awaiting human review, or terminal.

The MVP uses sequential synchronous execution so workflow semantics remain easy to inspect and test.

### 5. Workflow State Store

An in-memory state store supports deterministic tests, while SQLite persistence demonstrates checkpoint, reload, and resume behavior.

### 6. Retry Controller

Retries are explicit, bounded, and policy-controlled. The runtime distinguishes explicitly retryable failures from permanent failures and never permits unlimited retry loops.

### 7. Human Escalation

The workflow may enter `WAITING_FOR_HUMAN`. Execution cannot continue until a valid structured decision is recorded.

Human decisions:

- `APPROVE`
- `REJECT`
- `RETRY`

### 8. Event and Audit Log

Meaningful state transitions emit structured events so execution can be inspected and reconstructed. Audit events carry control metadata rather than copying onboarding notes into the event stream.

## Workflow States

```text
PENDING
RUNNING
WAITING_FOR_HUMAN
RETRY_SCHEDULED
COMPLETED
FAILED
REJECTED
```

The model cannot invent or directly set arbitrary workflow states.

## Node Types

```text
TASK
DECISION
HUMAN_GATE
END
```

Additional node types should be introduced only when a demonstrated requirement justifies them.

## Reliability Requirements

The MVP demonstrates that:

1. A straightforward onboarding workflow executes in dependency order and completes.
2. A transient package-preparation failure retries within a bounded policy and can recover.
3. A permanent or exhausted failure stops safely.
4. An exception household pauses for human review and resumes only after a valid decision.
5. A partially completed workflow can reload from persisted state without repeating completed work.
6. Duplicate completion or resume attempts do not cause duplicate downstream execution.

The sixth requirement demonstrates **idempotency**, a core reliability property for workflow systems.

## Evaluation Suite

`src/evaluation.py` runs ten named deterministic scenarios and returns a structured `EvaluationReport` that the Gradio UI and CI can consume.

Current scenarios cover:

- straightforward onboarding completion,
- transient failure with bounded retry and recovery,
- exception review followed by approval,
- exception review followed by rejection,
- invalid intake containment,
- permanent failure without unsafe retry,
- checkpoint reload and resume without replay,
- adversarial model attempts to inject workflow-control fields,
- cyclic DAG rejection before handler execution,
- and attempts to bypass a human gate through ordinary resume.

The harness measures:

- overall case pass rate,
- workflow completion rate,
- expected-path accuracy,
- retry correctness,
- escalation correctness,
- checkpoint/resume success,
- audit-log completeness,
- failure-containment rate,
- model-output containment rate,
- duplicate-execution count,
- and invalid-transition count.

The deterministic validation target is:

```text
overall case pass rate          1.00
workflow completion rate       1.00
expected-path accuracy          1.00
retry correctness              1.00
escalation correctness         1.00
checkpoint/resume success      1.00
audit-log completeness         1.00
failure-containment rate       1.00
model-output containment       1.00
duplicate execution count      0
invalid transition count       0
```

## Gradio Demo

`app.py` provides a thin Gradio interface over the same runtime used by the tests. Workflow control is not duplicated inside the UI.

The landing page is intentionally understandable to non-technical visitors first:

- a fictional wealth-management onboarding story,
- a clearly highlighted AI Intake Organizer,
- one-click standard, retry, exception, and permanent-failure scenarios,
- a plain-English business outcome,
- and a step-by-step explanation of what happened.

Technical evidence remains available in separate views for node state, structured outputs, audit events, human decisions, persistence, and evaluation metrics.

Each new workflow execution receives a random run ID. The app stores checkpoints in SQLite and can reload a run by ID so a waiting human gate can survive ordinary UI interaction and process-level workflow pauses. The local database filename is gitignored, and `WORKFLOW_DB_PATH` can override its location at deployment time.

Local SQLite persistence is appropriate for this portfolio demo, but it is not presented as multi-tenant production storage. Persistence across hosting-environment restarts depends on the deployment environment's storage configuration.

## CI and Deployment

`.github/workflows/ci.yml` is the source-of-truth automation gate. Pushes and pull requests to `main` run the complete pytest suite. Pull requests are test-only; a push to `main` deploys to Hugging Face only after the test job succeeds.

The Hugging Face sync job uses `huggingface/hub-sync@v0.1.0`, targets `FlyingNunchucks/09-agentic-workflow-sys`, and authenticates only through the GitHub repository secret `HF_DEPLOY_TOKEN`. GitHub remains the code source of truth.

## Project Structure

```text
app.py
README.md
requirements.txt
.env.example
.gitignore
.github/workflows/ci.yml
src/
tests/
```

## Build Sequence

1. Structured schemas
2. DAG validation
3. Allowlisted handler registry
4. Deterministic executor
5. Structured event logging
6. Bounded retries
7. Workflow persistence and resume
8. Human escalation
9. Deterministic conditional routing
10. Synthetic business workflow
11. Bounded model-assisted node
12. System evaluation suite
13. Gradio demo
14. CI-gated GitHub → Hugging Face deployment
15. Live production and public-repository hygiene checks

## Status

**Current phase:** Deterministic workflow engine, fictional wealth-management household-onboarding demo, bounded AI intake-organizer interface, structured evaluation harness, business-friendly Gradio experience, GitHub Actions CI, and automated GitHub → Hugging Face deployment are implemented. Final live validation of the redesigned onboarding UI and portfolio closeout remain.
