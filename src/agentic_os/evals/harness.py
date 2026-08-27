"""Versioned, append-only evaluation harness."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    evaluate: Callable[[], dict[str, Any]]
    tags: list[str] = field(default_factory=list)


class EvalCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    tags: list[str]
    passed: bool
    metrics: dict[str, Any]


class EvalRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(default_factory=lambda: f"evalrun_{uuid4().hex}")
    suite_name: str
    suite_version: str
    candidate: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    score: float = Field(ge=0, le=1)
    cases: list[EvalCaseResult]


class EvalSuite:
    def __init__(self, *, name: str, version: str, cases: list[EvalCase]) -> None:
        if not cases:
            raise ValueError("eval suite requires at least one case")
        self.name = name
        self.version = version
        self.cases = cases

    def run(self, *, candidate: str) -> EvalRun:
        results: list[EvalCaseResult] = []
        for case in self.cases:
            metrics = case.evaluate()
            passed = bool(metrics.get("passed", False))
            results.append(
                EvalCaseResult(
                    case_id=case.case_id,
                    tags=list(case.tags),
                    passed=passed,
                    metrics=metrics,
                )
            )
        score = sum(result.passed for result in results) / len(results)
        return EvalRun(
            suite_name=self.name,
            suite_version=self.version,
            candidate=candidate,
            score=score,
            cases=results,
        )


class EvalHistory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, run: EvalRun) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(run.model_dump_json() + "\n")

    def load(self) -> list[EvalRun]:
        if not self.path.exists():
            return []
        return [
            EvalRun.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


@dataclass(frozen=True)
class EvalComparison:
    baseline_id: str
    candidate_id: str
    regressions: list[str]
    improvements: list[str]
    acceptable: bool


def compare_runs(baseline: EvalRun, candidate: EvalRun) -> EvalComparison:
    if (baseline.suite_name, baseline.suite_version) != (
        candidate.suite_name,
        candidate.suite_version,
    ):
        raise ValueError("cannot compare different eval suite versions")
    base = {case.case_id: case for case in baseline.cases}
    current = {case.case_id: case for case in candidate.cases}
    if set(base) != set(current):
        raise ValueError("cannot compare runs with different case sets")
    regressions = sorted(
        case_id for case_id in base if base[case_id].passed and not current[case_id].passed
    )
    improvements = sorted(
        case_id for case_id in base if not base[case_id].passed and current[case_id].passed
    )
    return EvalComparison(
        baseline_id=baseline.run_id,
        candidate_id=candidate.run_id,
        regressions=regressions,
        improvements=improvements,
        acceptable=not regressions,
    )
