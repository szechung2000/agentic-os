"""Credential-free executable E2A acceptance proof."""

from agentic_os.cli import main
from agentic_os.evals.e2 import run_e2_proof


def test_e2_proof_passes_all_cases_and_persists_history(tmp_path):
    proof = run_e2_proof(tmp_path, candidate="test-candidate")

    assert proof.run.score == 1.0
    assert {case.case_id for case in proof.run.cases} == {
        "worker-isolation-and-shared-promotion",
        "supervisor-private-visibility",
        "expiry-filtering",
        "budgeted-provenance-hydration",
        "restart-recovery-and-tracing",
    }
    assert proof.history_path.exists()


def test_e2_proof_cli_prints_all_cases(tmp_path, capsys):
    code = main(["eval", "e2", "--workdir", str(tmp_path), "--candidate", "cli-proof"])

    assert code == 0
    output = capsys.readouterr().out
    assert "E2 score: 5/5 (100%)" in output
    assert "worker-isolation-and-shared-promotion: PASS" in output
    assert "restart-recovery-and-tracing: PASS" in output


def test_e2_proof_is_repeatable_in_the_same_workdir(tmp_path):
    first = run_e2_proof(tmp_path, candidate="first")
    second = run_e2_proof(tmp_path, candidate="second")

    assert first.run.score == second.run.score == 1.0
    assert first.trace_id != second.trace_id
    assert len(first.history_path.read_text().splitlines()) == 2
