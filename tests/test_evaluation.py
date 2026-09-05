from src.evaluation import EvaluationReport, run_evaluation_suite


EXPECTED_CASE_IDS = {
    "straightforward_onboarding",
    "transient_retry_recovery",
    "exception_approval",
    "exception_rejection",
    "validation_failure",
    "permanent_failure",
    "checkpoint_resume",
    "model_control_injection",
    "invalid_dag",
    "human_gate_bypass",
}

RATE_METRICS = {
    "overall_case_pass_rate",
    "workflow_completion_rate",
    "expected_path_accuracy",
    "retry_correctness",
    "escalation_correctness",
    "checkpoint_resume_success",
    "audit_log_completeness",
    "failure_containment_rate",
    "model_output_containment_rate",
}


def test_full_evaluation_suite_passes_all_cases() -> None:
    report = run_evaluation_suite()

    assert isinstance(report, EvaluationReport)
    assert report.total_cases == 10
    assert report.passed_cases == 10
    assert report.failed_cases == 0
    assert report.case_pass_rate == 1.0
    assert {case.case_id for case in report.cases} == EXPECTED_CASE_IDS
    assert all(case.passed for case in report.cases)


def test_evaluation_metrics_meet_deterministic_mvp_targets() -> None:
    report = run_evaluation_suite()

    for metric_name in RATE_METRICS:
        assert report.metrics[metric_name] == 1.0

    assert report.metrics["duplicate_execution_count"] == 0
    assert report.metrics["invalid_transition_count"] == 0


def test_evaluation_cases_expose_readable_checks_without_raw_payloads() -> None:
    report = run_evaluation_suite()

    for case in report.cases:
        assert case.case_id
        assert case.category
        assert case.expected
        assert case.observed
        assert case.checks

    serialized = report.model_dump_json()
    assert "EVAL_MODEL_CONTROL_MARKER" not in serialized
    assert "arbitrary_handler" not in serialized


def test_checkpoint_and_adversarial_cases_report_zero_duplicate_execution() -> None:
    report = run_evaluation_suite()
    cases = {case.case_id: case for case in report.cases}

    assert cases["checkpoint_resume"].details["duplicate_executions"] == 0
    assert cases["exception_approval"].details["duplicate_executions"] == 0
    assert cases["model_control_injection"].checks["model_contained"] is True
    assert cases["human_gate_bypass"].checks["failure_contained"] is True
