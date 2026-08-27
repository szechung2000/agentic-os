"""Event-sourced run coordinator with content-addressed checkpoints."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agentic_os.core.contracts import ArtifactRef, ComponentKind, GoalContract, RunEvent
from agentic_os.core.events import EventStore


class RunStatus(StrEnum):
    RECEIVED = "received"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.RECEIVED: {RunStatus.PLANNING, RunStatus.CANCELLED},
    RunStatus.PLANNING: {RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.PLANNING,
        RunStatus.PAUSED,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.PAUSED: {RunStatus.PLANNING, RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: {RunStatus.PLANNING},
    RunStatus.CANCELLED: set(),
}


class PlanRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    old_plan: list[str]
    new_plan: list[str]
    reason: str = Field(min_length=1)


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1"
    run_id: str
    trace_id: str
    goal: GoalContract
    status: RunStatus = RunStatus.RECEIVED
    completed_tasks: set[str] = Field(default_factory=set)
    plan_version: int = 0
    plan_revisions: list[PlanRevision] = Field(default_factory=list)


class RunCoordinator:
    def __init__(self, events: EventStore) -> None:
        self.events = events
        self._states: dict[str, RunState] = {}

    def create(self, goal: GoalContract) -> RunState:
        run_id = f"run_{uuid4().hex}"
        trace_id = f"trace_{uuid4().hex}"
        state = RunState(run_id=run_id, trace_id=trace_id, goal=goal)
        payload = {"goal": goal.model_dump(mode="json")}
        self.events.append(self._event(state, "run.created", payload))
        self._states[run_id] = state
        return state.model_copy(deep=True)

    def load(self, run_id: str) -> RunState:
        checkpoint = self.events.load_checkpoint(run_id)
        after_seq = 0
        state: RunState | None = None
        if checkpoint is not None:
            after_seq, content_hash, state_json = checkpoint
            actual_hash = f"sha256:{hashlib.sha256(state_json.encode()).hexdigest()}"
            if actual_hash != content_hash:
                raise ValueError(f"checkpoint hash mismatch: {run_id}")
            state = RunState.model_validate_json(state_json)

        subsequent = self.events.query(run_id=run_id, after_seq=after_seq)
        for event in subsequent:
            if event.event_type == "run.created":
                state = RunState(
                    run_id=event.run_id,
                    trace_id=event.trace_id,
                    goal=GoalContract.model_validate(event.data["goal"]),
                )
            elif state is not None:
                self._apply(state, event)
        if state is None:
            raise KeyError(f"unknown run: {run_id}")
        self._states[run_id] = state
        return state.model_copy(deep=True)

    def transition(self, run_id: str, target: RunStatus) -> RunState:
        state = self._current(run_id)
        if target not in _ALLOWED_TRANSITIONS[state.status]:
            raise ValueError(f"invalid transition: {state.status} -> {target}")
        event = self._event(
            state,
            "run.status.changed",
            {"from": state.status.value, "to": target.value},
        )
        self.events.append(event)
        self._apply(state, event)
        return state.model_copy(deep=True)

    def complete_task(self, run_id: str, task_id: str) -> bool:
        state = self._current(run_id)
        if task_id in state.completed_tasks:
            return False
        event = self._event(state, "task.completed", {"task_id": task_id})
        self.events.append(event)
        self._apply(state, event)
        return True

    def revise_plan(
        self,
        run_id: str,
        *,
        old_plan: list[str],
        new_plan: list[str],
        reason: str,
    ) -> PlanRevision:
        state = self._current(run_id)
        revision = PlanRevision(
            version=state.plan_version + 1,
            old_plan=old_plan,
            new_plan=new_plan,
            reason=reason,
        )
        event = self._event(state, "plan.revised", revision.model_dump(mode="json"))
        self.events.append(event)
        self._apply(state, event)
        return revision

    def checkpoint(self, run_id: str) -> ArtifactRef:
        state = self._current(run_id)
        state_json = json.dumps(
            state.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        payload = state_json.encode()
        ref = ArtifactRef.from_bytes(payload, media_type="application/json")
        self.events.save_checkpoint(
            run_id,
            event_seq=self.events.max_seq(run_id),
            content_hash=ref.content_hash,
            state_json=state_json,
        )
        return ref

    def _current(self, run_id: str) -> RunState:
        if run_id not in self._states:
            self.load(run_id)
        return self._states[run_id]

    @staticmethod
    def _apply(state: RunState, event: RunEvent) -> None:
        if event.event_type == "run.status.changed":
            state.status = RunStatus(event.data["to"])
        elif event.event_type == "task.completed":
            state.completed_tasks.add(str(event.data["task_id"]))
        elif event.event_type == "plan.revised":
            revision = PlanRevision.model_validate(event.data)
            state.plan_revisions.append(revision)
            state.plan_version = revision.version

    @staticmethod
    def _event(state: RunState, event_type: str, data: dict) -> RunEvent:
        return RunEvent(
            event_type=event_type,
            trace_id=state.trace_id,
            span_id=f"span_{uuid4().hex}",
            goal_id=state.goal.goal_id,
            run_id=state.run_id,
            component_kind=ComponentKind.SUPERVISOR,
            component_name="run-coordinator",
            operation=event_type,
            status="ok",
            data=data,
        )
