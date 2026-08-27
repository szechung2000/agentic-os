"""Contract behavior tests — written before the E0 implementation."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentic_os.core.contracts import (
    ApprovalRequest,
    ArtifactRef,
    ComponentKind,
    EvaluationResult,
    GoalContract,
    RunEvent,
    TaskContract,
    WorkerResult,
)


def test_goal_contract_requires_objective_and_success_metric():
    with pytest.raises(ValidationError):
        GoalContract(objective="Ship it", success_metrics=[])

    goal = GoalContract(
        objective="Improve L3 synthesis",
        success_metrics=["L3 score increases", "No golden regression"],
        constraints=["local only"],
    )
    assert goal.schema_version == "1"
    assert goal.goal_id.startswith("goal_")


def test_task_contract_rejects_self_dependency():
    task = TaskContract(
        task_id="task_same",
        goal_id="goal_1",
        worker_role="coding",
        objective="Prototype hypothesis",
        expected_artifacts=["patch", "eval report"],
    )
    with pytest.raises(ValidationError):
        task.model_copy(update={"dependencies": ["task_same"]}, deep=True).model_validate(
            {**task.model_dump(), "dependencies": ["task_same"]}
        )


def test_task_contract_rejects_unprovenanced_context_refs():
    with pytest.raises(ValidationError):
        TaskContract(
            goal_id="goal_1",
            worker_role="coding",
            objective="Prototype",
            context_refs=["raw-unprovenanced-text"],
        )


def test_worker_result_requires_failure_explanation():
    with pytest.raises(ValidationError):
        WorkerResult(task_id="task_1", worker_id="worker_1", status="failed")

    result = WorkerResult(
        task_id="task_1",
        worker_id="worker_1",
        status="failed",
        summary="Build failed",
        failures=["pytest collection error"],
    )
    assert result.failures


def test_evaluation_result_requires_metrics_and_evaluator_version():
    with pytest.raises(ValidationError):
        EvaluationResult(candidate_id="trial_1", evaluator_version="", metrics={})

    result = EvaluationResult(
        candidate_id="trial_1",
        evaluator_version="golden-v2",
        metrics={"quality": 0.9, "latency_ms": 42.0},
        verdict="adopt",
    )
    assert result.metrics["quality"] == 0.9


def test_artifact_ref_uses_content_hash_and_uri():
    ref = ArtifactRef.from_bytes(b"verified output", media_type="text/plain")
    assert ref.uri.startswith("artifact://sha256/")
    assert ref.content_hash.startswith("sha256:")
    assert ref.size_bytes == len(b"verified output")


def test_approval_must_be_unexpired_and_targeted():
    approval = ApprovalRequest(
        run_id="run_1",
        actor_id="worker_1",
        operation="delete file",
        targets=["docs/old.md"],
        reason="replace obsolete artifact",
        command_hash="sha256:abc",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert approval.approval_id.startswith("approval_")
    assert approval.is_valid(datetime.now(UTC))


def test_event_validates_component_and_terminal_status():
    event = RunEvent(
        event_type="component.call.completed",
        trace_id="trace_1",
        span_id="span_1",
        goal_id="goal_1",
        run_id="run_1",
        component_kind=ComponentKind.WORKER,
        component_name="research",
        operation="worker.run",
        status="ok",
    )
    assert event.schema_version == "1"
    assert event.event_id.startswith("evt_")

    with pytest.raises(ValidationError):
        RunEvent(
            event_type="component.call.completed",
            trace_id="trace_1",
            span_id="span_1",
            goal_id="goal_1",
            run_id="run_1",
            component_kind=ComponentKind.WORKER,
            component_name="research",
            operation="worker.run",
            status="running",
        )
