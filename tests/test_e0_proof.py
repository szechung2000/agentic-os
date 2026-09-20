"""Executable E0 acceptance proof — RED before implementation."""

from agentic_os.cli import main
from agentic_os.evals.e0 import run_e0_proof


def test_e0_proof_passes_all_acceptance_cases_and_persists_history(tmp_path):
    proof = run_e0_proof(tmp_path, candidate="test-candidate")
    assert proof.run.score == 1.0
    assert {case.case_id for case in proof.run.cases} == {
        "contract-validation",
        "restart-recovery",
        "trace-integrity-replay",
        "component-kind-coverage",
        "provider-replacement",
    }
    assert proof.trace_report.ok
    assert proof.recovered_completed_tasks == {"contracts"}
    assert proof.recorded_replay_live_calls == 0
    assert proof.replayed_terminal_status == "failed"
    assert proof.history_path.exists()


def test_e0_proof_cli_prints_reproducible_artifact_locations(tmp_path, capsys):
    code = main(["eval", "e0", "--workdir", str(tmp_path), "--candidate", "cli-proof"])
    assert code == 0
    output = capsys.readouterr().out
    assert "E0 score: 5/5 (100%)" in output
    assert "restart-recovery: PASS" in output
    assert "trace-integrity-replay: PASS" in output
    assert "live_calls=0" in output
    assert str(tmp_path / "events.db") in output
    assert str(tmp_path / "eval-history.jsonl") in output
