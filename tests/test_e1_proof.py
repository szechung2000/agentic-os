"""Executable E1 proof and CLI output tests."""

from __future__ import annotations

from agentic_os.cli import main
from agentic_os.evals.e1 import run_e1_proof


def test_e1_proof_passes_all_cases_and_persists_history(tmp_path):
    proof = run_e1_proof(tmp_path, candidate="test-candidate")

    assert proof.run.score == 1.0
    assert {case.case_id for case in proof.run.cases} == {
        "same-boundary",
        "pre-start-fallback",
        "workspace-policy",
        "timeout-preserves-lifecycle",
        "bridge-trace",
    }
    assert proof.history_path.exists()


def test_e1_proof_cli_prints_all_cases(tmp_path, capsys):
    code = main(["eval", "e1", "--workdir", str(tmp_path), "--candidate", "cli-proof"])

    assert code == 0
    output = capsys.readouterr().out
    assert "E1 score: 5/5 (100%)" in output
    assert "same-boundary: PASS" in output
    assert "pre-start-fallback: PASS" in output
    assert "timeout-preserves-lifecycle: PASS" in output
    assert str(tmp_path / "eval-history.jsonl") in output
