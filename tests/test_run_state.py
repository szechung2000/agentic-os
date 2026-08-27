"""Durable run-state tests — RED before implementation."""

import pytest

from agentic_os.core.contracts import GoalContract
from agentic_os.core.events import EventStore
from agentic_os.core.state import RunCoordinator, RunStatus


def goal():
    return GoalContract(
        objective="Build E0 durable core",
        success_metrics=["restart recovery", "no duplicate tasks"],
    )


def test_run_recovers_checkpoint_plus_later_events(tmp_path):
    events = EventStore(tmp_path / "events.db")
    first = RunCoordinator(events)
    state = first.create(goal())
    first.transition(state.run_id, RunStatus.PLANNING)
    first.checkpoint(state.run_id)
    first.transition(state.run_id, RunStatus.RUNNING)
    assert first.complete_task(state.run_id, "task_contracts") is True

    restarted = RunCoordinator(EventStore(tmp_path / "events.db"))
    recovered = restarted.load(state.run_id)
    assert recovered.status == RunStatus.RUNNING
    assert recovered.completed_tasks == {"task_contracts"}


def test_completed_task_is_idempotent_after_restart(tmp_path):
    events = EventStore(tmp_path / "events.db")
    first = RunCoordinator(events)
    state = first.create(goal())
    first.transition(state.run_id, RunStatus.PLANNING)
    first.transition(state.run_id, RunStatus.RUNNING)
    assert first.complete_task(state.run_id, "task_1") is True

    restarted = RunCoordinator(EventStore(tmp_path / "events.db"))
    assert restarted.complete_task(state.run_id, "task_1") is False
    recovered = restarted.load(state.run_id)
    assert recovered.completed_tasks == {"task_1"}


def test_invalid_status_transition_is_rejected(tmp_path):
    coordinator = RunCoordinator(EventStore(tmp_path / "events.db"))
    state = coordinator.create(goal())
    with pytest.raises(ValueError, match="invalid transition"):
        coordinator.transition(state.run_id, RunStatus.COMPLETED)


def test_plan_revision_preserves_versions_and_reason(tmp_path):
    coordinator = RunCoordinator(EventStore(tmp_path / "events.db"))
    state = coordinator.create(goal())
    coordinator.transition(state.run_id, RunStatus.PLANNING)
    coordinator.revise_plan(
        state.run_id,
        old_plan=["build monolith"],
        new_plan=["contracts", "events", "state"],
        reason="acceptance tests require restart proof",
    )

    restarted = RunCoordinator(EventStore(tmp_path / "events.db"))
    recovered = restarted.load(state.run_id)
    assert recovered.plan_version == 1
    assert recovered.plan_revisions[0].old_plan == ["build monolith"]
    assert recovered.plan_revisions[0].new_plan == ["contracts", "events", "state"]
    assert recovered.plan_revisions[0].reason == "acceptance tests require restart proof"


def test_checkpoint_is_content_addressed_and_stable_without_changes(tmp_path):
    coordinator = RunCoordinator(EventStore(tmp_path / "events.db"))
    state = coordinator.create(goal())
    first = coordinator.checkpoint(state.run_id)
    second = coordinator.checkpoint(state.run_id)
    assert first.content_hash == second.content_hash
    assert first.uri == second.uri


def test_restart_rejects_tampered_checkpoint(tmp_path):
    import sqlite3

    db = tmp_path / "events.db"
    coordinator = RunCoordinator(EventStore(db))
    state = coordinator.create(goal())
    coordinator.checkpoint(state.run_id)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE run_checkpoints SET state_json = ? WHERE run_id = ?",
            ('{"tampered":true}', state.run_id),
        )

    restarted = RunCoordinator(EventStore(db))
    with pytest.raises(ValueError, match="checkpoint hash mismatch"):
        restarted.load(state.run_id)
