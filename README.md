# Agent 9 — Agentic Workflow System

A deterministic, resumable, and auditable workflow runtime for AI-assisted business processes.

## Problem

AI systems can perform individual tasks, but reliable business processes require more than model reasoning. Production workflows need explicit sequencing, validated state transitions, bounded retries, durable checkpoints, failure handling, human approval gates, and an auditable event history.

This project explores that engineering boundary by building a small workflow runtime where models may assist with bounded tasks, but application code controls execution.

## Core Engineering Principle

> Models may propose and reason. Application code owns workflow state, validation, execution order, retries, escalation, and completion.

The workflow engine—not the language model—decides what may run next.

## Demo Scenario

The public demo uses a synthetic fictional **Service Request Workflow**.

A request moves through a controlled process:

```text
Submit Request
      ↓
Validate Request
      ↓
Classify Request
      ↓
Policy Check
      ↓
Perform Task
      ↓
Verify Result
      ↓
Risk Gate
   ↙       ↘
Low         High
 ↓           ↓
Finalize   Human Review
              ↓
         Approve / Reject
```

The scenario is intentionally synthetic and contains no private, client, financial, or proprietary data.

## Architecture

The system contains the following layers.

### 1. Structured Workflow Definition

Typed schemas define workflow nodes, dependencies, retry policies, workflow runs, node runs, events, and human-review decisions.

A workflow definition describes what **may** happen. A workflow run records what **did** happen.

### 2. DAG Validation

Before execution, deterministic validation rejects invalid workflow definitions such as:

- duplicate node identifiers,
- unknown dependencies,
- cyclic dependencies,
- invalid decision routes,
- unsupported branch reconvergence,
- invalid retry policies,
- and malformed workflow definitions.

Invalid workflows fail before any task executes.

### 3. Handler Registry

Workflow task handlers are explicitly registered and allowlisted. A workflow cannot invoke an arbitrary model-generated function name.

### 4. Workflow Executor

The executor determines which nodes are ready, completed, skipped, failed, retryable, awaiting human review, or terminal.

The MVP uses sequential synchronous execution so the workflow semantics remain easy to inspect and test.

### 5. Workflow State Store

An in-memory state store supports deterministic tests, while SQLite persistence demonstrates checkpoint, reload, and resume behavior.

### 6. Retry Controller

Retries are explicit, bounded, and policy-controlled.

The runtime distinguishes explicitly retryable failures from permanent failures and never permits unlimited retry loops.

### 7. Human Escalation

The workflow may enter a `WAITING_FOR_HUMAN` state. Execution cannot continue until a valid structured decision is recorded.

Human decisions:

- `APPROVE`
- `REJECT`
- `RETRY`

### 8. Event and Audit Log

Meaningful state transitions emit structured events so execution can be inspected and reconstructed.

Examples include:

- workflow started,
- node started,
- node completed,
- node skipped,
- node failed,
- decision routed,
- retry scheduled,
- human review requested,
- human approved or rejected,
- workflow resumed,
- workflow completed,
- workflow failed.

## Workflow States

Application-controlled workflow states:

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

The MVP uses a deliberately small node vocabulary:

```text
TASK
DECISION
HUMAN_GATE
END
```

Additional node types should be introduced only when a demonstrated requirement justifies them.

## Reliability Requirements

The MVP demonstrates that:

1. A normal workflow executes in dependency order and completes.
2. A transient failure retries within a bounded policy and can recover.
3. A permanent or exhausted failure stops safely.
4. A high-risk request pauses for human review and resumes only after a valid decision.
5. A partially completed workflow can reload from persisted state without repeating completed work.
6. Duplicate completion or resume events do not cause duplicate downstream execution.

The sixth requirement introduces **idempotency**, a core reliability property for workflow systems.

## Model Boundary

The service-request classifier now supports an optional **bounded model-assisted mode**.

The model receives only the request type and description needed for classification. It returns strict JSON containing a classification from an application-defined allowlist plus a short rationale. Pydantic validates that proposal before the workflow accepts it.

```text
model proposes classification
          ↓
strict JSON schema validates
          ↓
application accepts normalized data
          ↓
deterministic workflow continues
```

The deterministic classifier remains the default, and model integration is provider-agnostic through an injected callable. A live inference-provider adapter will be added separately so provider networking does not become part of workflow control logic.

The model is not permitted to:

- change the DAG,
- choose arbitrary route targets,
- register arbitrary handlers,
- bypass approval gates,
- change retry limits,
- execute arbitrary code,
- set workflow state,
- or publish unvalidated structured output.

Malformed model output, invented classifications, extra control fields, and provider failures are contained at the classification node. Rejected model text is not copied into audit-event details.

## Evaluation Focus

Evaluation emphasizes workflow correctness rather than prose quality.

Planned metrics include:

- workflow completion rate,
- expected-path accuracy,
- invalid-transition count,
- retry correctness,
- escalation correctness,
- checkpoint/resume success,
- duplicate-execution count,
- audit-log completeness,
- model-output containment,
- and failure-containment rate.

Planned tests cover success paths, malformed workflow definitions, retry exhaustion, permanent failures, invalid structured outputs, human escalation, duplicate events, persistence/recovery, and adversarial attempts to bypass workflow controls.

## Initial Project Structure

```text
README.md
requirements.txt
.env.example
.gitignore
src/
tests/
```

Implementation is being added incrementally in small, testable changes.

## Planned Build Sequence

1. Define structured schemas.
2. Implement DAG validation.
3. Implement an allowlisted handler registry.
4. Implement the basic deterministic executor.
5. Add structured event logging.
6. Add bounded retries.
7. Add workflow persistence and resume.
8. Add human escalation.
9. Add deterministic conditional routing.
10. Assemble the synthetic service-request workflow.
11. Add a model-assisted node only after deterministic behavior is tested.
12. Build the evaluation suite.
13. Add a Gradio demo.
14. Add CI-gated GitHub → Hugging Face deployment.
15. Complete live production and public-repository hygiene checks.

## Status

**Current phase:** Deterministic workflow engine, synthetic service-request workflow, and bounded provider-agnostic model-assisted classification are implemented. Full evaluation, live provider integration, UI, and deployment remain.
