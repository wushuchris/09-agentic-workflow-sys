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

**Think of this as an operations workflow dashboard for a fictional wealth-management firm.** It demonstrates how AI can contribute useful work product inside a deterministic, resumable, and auditable business process while application code controls execution and people retain authority over consequential exceptions.

## Problem

AI systems can perform individual tasks, but reliable business processes require more than model reasoning. Production workflows need explicit sequencing, validated state transitions, bounded retries, durable checkpoints, failure handling, human approval gates, and an auditable event history.

This project explores that engineering boundary by building a small workflow runtime where AI can contribute useful work product while application code controls consequences.

## Core Engineering Principle

> AI contributes work. Application code governs the process. Humans retain authority over consequential exceptions.

The workflow engine—not the language model—decides what may run next.

## Demo Scenario — Fictional Wealth Management Household Onboarding

The public demo presents the workflow as an **operations workflow dashboard** for a fictional wealth-management business. A fully synthetic household moves through a hypothetical onboarding process while the dashboard makes AI assistance, deterministic controls, exception routing, retries, and human review visible. It illustrates workflow engineering; it does not represent any firm's actual compliance procedure and does not open a real account.

```text
Synthetic household intake
          ↓
Validate intake
          ↓
🤖 AI Intake Organizer
   profile + summary
          ↓
Check documents
          ↓
Apply deterministic onboarding rules
          ↓
Prepare onboarding package
(includes validated AI work product)
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

- **Harbor Family — straightforward household** — the fictional package becomes ready on the standard path.
- **Harbor Family — temporary onboarding-service issue** — package preparation fails once, retries within policy, and recovers.
- **Redwood Family Trust — human review required** — deterministic exception rules pause the workflow for a person.
- **Cedar Household — permanent dependency failure** — the workflow stops safely before uncertain downstream work runs.

All names and facts are synthetic.

## 60-Second Demo Walkthrough

A useful way to explain the project is:

> Think of this as an operations workflow dashboard. A fictional wealth-management household enters onboarding. AI helps organize the unstructured intake, but it cannot control the workflow. Deterministic code checks the rules and decides the permitted path. Routine cases continue automatically, temporary failures retry safely, and exception cases pause for a human. The important pattern is: **AI contributes work, code governs consequences, and humans retain authority over consequential exceptions.**

For a quick walkthrough, run the **Harbor Family — straightforward household** first to show the standard path, then run the **Redwood Family Trust — human review required** case to show where automation deliberately stops and hands authority to a person. The technical tabs underneath provide the evidence for the story: node state, bounded AI output, append-only events, retries, persistence, and human-review history.

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
strict Pydantic validation
        ↓
validated bounded work product
        ↓
simulated onboarding package
```

The validated AI work product is intentionally useful: package preparation includes the profile category and intake summary. The AI is therefore part of the business workflow rather than a decorative UI element.

But the AI output is deliberately **non-authoritative**. The deterministic review gate ignores the model's profile category and summary. Routing is based only on application-controlled structured fields such as document completeness, identity-review status, relationship complexity, and special household structure.

A regression test explicitly demonstrates that a model can propose `COMPLEX_HOUSEHOLD` while a case with no configured deterministic exception still remains on the standard path.

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

## Live Hugging Face Inference

`src/hf_provider.py` implements a small provider adapter around Hugging Face `InferenceClient`. The adapter knows only how to turn one prompt into one text response; it has no access to workflow state or routing.

Live inference is deliberately opt-in. It requires both:

```text
LIVE_AI_ENABLED=true
HF_TOKEN=<runtime secret>
```

The default model is configurable through `MODEL_ID`; the current example default is:

```text
Qwen/Qwen2.5-7B-Instruct-1M
```

If live inference is not explicitly enabled, the AI-capable node uses a clearly labeled deterministic fallback. The UI never claims a live model ran when it did not.

The live provider output still passes through the same strict Pydantic boundary. Provider failures and invalid model output fail closed at the AI node rather than gaining workflow authority.

## What the Business-Friendly UI Shows

The landing experience is designed for both non-technical and technical visitors. The top-level framing is deliberately that of an **operations workflow dashboard**: the visitor can see what the business process is doing, where AI contributed, why a case took a particular path, where recovery occurred, and when a person must intervene.

After each run it shows, in this order:

1. **Plain-English business outcome** — what happened to the fictional onboarding case.
2. **Live workflow path** — completed steps light up while the unused branch is muted; the AI node is visually highlighted.
3. **Bounded AI work product** — live vs fallback source, profile category, intake summary, and whether the validated summary reached the simulated package.
4. **Why did it route here?** — the exact deterministic exception reasons that selected the standard or human-review path, with an explicit statement that the AI summary did not choose the route.
5. **Step-by-step journey** — a readable translation of node state, retry recovery, and human decisions.

Technical tabs preserve the underlying evidence: exact node state, structured outputs, append-only audit events, persisted human reviews, and the evaluation suite.

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

Meaningful state transitions emit structured events so execution can be inspected and reconstructed. Audit events carry control metadata rather than copying onboarding notes or AI summaries into the event stream.

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
7. AI output can contribute to the work product without controlling deterministic routing.

The sixth requirement demonstrates **idempotency**. The seventh demonstrates **bounded AI authority**.

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

The harness measures overall case pass rate, workflow completion, expected-path accuracy, retry correctness, escalation correctness, checkpoint/resume success, audit completeness, failure containment, model-output containment, duplicate executions, and invalid transitions.

## CI and Deployment

`.github/workflows/ci.yml` is the source-of-truth automation gate. Pushes and pull requests to `main` run the complete pytest suite. Pull requests are test-only; a push to `main` deploys to Hugging Face only after the test job succeeds.

The Hugging Face sync job uses `huggingface/hub-sync@v0.1.0`, targets `FlyingNunchucks/09-agentic-workflow-sys`, and authenticates only through the GitHub repository secret `HF_DEPLOY_TOKEN`. GitHub remains the code source of truth.

Runtime inference credentials are separate from deployment credentials. `HF_DEPLOY_TOKEN` is not reused as the Space's inference token.

## Project Structure

```text
app.py
README.md
requirements.txt
.env.example
.gitignore
.github/workflows/ci.yml
src/
  hf_provider.py
  model_assist.py
  ...
tests/
```

## Status

**Complete — production validated.** Agent 9 now includes the deterministic workflow engine, fictional wealth-management onboarding dashboard, bounded AI intake work product, provider adapter, path visualization, deterministic routing explanation, persistence, bounded retries, human escalation, append-only audit history, idempotent resume behavior, a 10-case evaluation harness, a business-friendly Gradio interface, GitHub Actions CI, and automated GitHub → Hugging Face deployment. The final CI run passed **125 tests**, the public Space was validated across standard, retry, approve, reject, evaluation, and persisted-reload paths, and the GitHub → Hugging Face sync completed successfully. Live model inference remains an optional deployment enhancement rather than a requirement for the completed workflow pattern.