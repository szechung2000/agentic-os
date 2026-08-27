"""Trace CLI behavior tests — RED before implementation."""

from agentic_os.cli import main
from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import ComponentKind, RunEvent
from agentic_os.core.events import EventStore


def seed(tmp_path):
    db = tmp_path / "events.db"
    artifact_root = tmp_path / "artifacts"
    events = EventStore(db)
    artifacts = ArtifactStore(artifact_root)
    output = artifacts.put(b"recorded proof", "text/plain")
    common = dict(
        trace_id="trace_cli",
        span_id="span_cli",
        goal_id="goal_1",
        run_id="run_1",
        component_kind=ComponentKind.WORKER,
        component_name="proof-worker",
        operation="worker.prove",
    )
    events.append(RunEvent(event_type="component.call.started", status="running", **common))
    events.append(
        RunEvent(
            event_type="component.call.completed",
            status="ok",
            output_ref=output,
            **common,
        )
    )
    return db, artifact_root


def test_trace_tree_cli_prints_component(tmp_path, capsys):
    db, artifacts = seed(tmp_path)
    code = main(
        [
            "trace",
            "tree",
            "trace_cli",
            "--db",
            str(db),
            "--artifacts",
            str(artifacts),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "proof-worker" in output
    assert "span_cli" in output
    assert "ok" in output


def test_trace_verify_cli_prints_integrity_proof(tmp_path, capsys):
    db, artifacts = seed(tmp_path)
    code = main(
        [
            "trace",
            "verify",
            "trace_cli",
            "--db",
            str(db),
            "--artifacts",
            str(artifacts),
        ]
    )
    assert code == 0
    assert "events=2 spans=1 integrity=ok" in capsys.readouterr().out


def test_trace_replay_cli_reads_recorded_output_without_live_call(tmp_path, capsys):
    db, artifacts = seed(tmp_path)
    code = main(
        [
            "trace",
            "replay",
            "trace_cli",
            "span_cli",
            "--db",
            str(db),
            "--artifacts",
            str(artifacts),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "recorded proof" in output
    assert "live_calls=0" in output
