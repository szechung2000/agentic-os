"""Minimal versioned eval harness tests — RED before implementation."""

import json

from agentic_os.evals.harness import EvalCase, EvalHistory, EvalSuite, compare_runs


def test_eval_suite_records_case_metrics_and_tags():
    suite = EvalSuite(
        name="e0-core",
        version="1",
        cases=[
            EvalCase(
                case_id="restart",
                tags=["state", "durability"],
                evaluate=lambda: {"passed": True, "latency_ms": 2.5},
            ),
            EvalCase(
                case_id="trace",
                tags=["observability"],
                evaluate=lambda: {"passed": True, "span_count": 3},
            ),
        ],
    )
    run = suite.run(candidate="working-tree")
    assert run.score == 1.0
    assert run.cases[0].metrics["latency_ms"] == 2.5
    assert run.cases[1].tags == ["observability"]
    assert run.suite_version == "1"


def test_eval_history_is_append_only_jsonl(tmp_path):
    suite = EvalSuite(
        name="e0-core",
        version="1",
        cases=[EvalCase(case_id="one", evaluate=lambda: {"passed": True})],
    )
    history = EvalHistory(tmp_path / "history.jsonl")
    first = suite.run(candidate="baseline")
    second = suite.run(candidate="candidate")
    history.append(first)
    history.append(second)

    lines = (tmp_path / "history.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["candidate"] == "baseline"
    assert [run.candidate for run in history.load()] == ["baseline", "candidate"]


def test_compare_runs_detects_case_regression():
    baseline = EvalSuite(
        name="e0-core",
        version="1",
        cases=[EvalCase(case_id="restart", evaluate=lambda: {"passed": True})],
    ).run(candidate="baseline")
    candidate = EvalSuite(
        name="e0-core",
        version="1",
        cases=[EvalCase(case_id="restart", evaluate=lambda: {"passed": False})],
    ).run(candidate="candidate")

    comparison = compare_runs(baseline, candidate)
    assert comparison.regressions == ["restart"]
    assert not comparison.acceptable
