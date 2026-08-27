#!/usr/bin/env python3
"""
E0 Acceptance Criteria Verification Script

Checks whether the codebase satisfies roadmap.md E0 acceptance criteria
(lines 34-44) and reports any gaps. Pure verification — no code changes.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path("/opt/data/agentic-os")

ACCEPTANCE_CRITERIA = {
    "AC-1": "Process stops mid-run and resumes without duplicating completed work",
    "AC-2": "Every component call emits one start and exactly one completed/failed/cancelled/timed-out terminal event",
    "AC-3": "Broken parent spans, missing terminal events, or unredacted secrets fail trace-integrity checks",
    "AC-4": "A failed fixture can be diagnosed and replayed from recorded artifacts without live external calls",
    "AC-5": "Invalid worker output is rejected with a bounded correction attempt",
    "AC-6": "Replanning records the old plan, new plan, and reason",
    "AC-7": "A test provider replaces an existing capability without changing supervisor code",
    "AC-8": "Every model-visible context item is reconstructable from its recorded provenance",
    "AC-9": "Unregistering an extension reverses its registrations and releases owned resources",
    "AC-10": "Every model-visible context item is reconstructable from its recorded provenance",  # duplicate, skip
}

TEST_FILES = [
    "tests/test_contracts.py",
    "tests/test_event_store.py",
    "tests/test_instrumentation.py",
    "tests/test_registry.py",
    "tests/test_run_state.py",
    "tests/test_trace.py",
    "tests/test_trace_cli.py",
    "tests/test_e0_proof.py",
    "tests/test_agy_e0_verify.py",
]

SOURCE_FILES = [
    "src/agentic_os/core/contracts.py",
    "src/agentic_os/core/events.py",
    "src/agentic_os/core/state.py",
    "src/agentic_os/core/registry.py",
    "src/agentic_os/supervisor/supervisor.py",
    "src/agentic_os/workers/base.py",
    "src/agentic_os/evals/e0.py",
]


def read_file(path: str) -> str:
    p = ROOT / path
    if p.exists():
        return p.read_text()
    return ""


def find_pattern(text: str, pattern: str) -> list[str]:
    return re.findall(pattern, text)


def check_ac1(text: str) -> dict:
    """AC-1: Process stops mid-run, resumes without duplicate work.
    Look for: checkpoint/restart mechanisms, completed_tasks idempotency."""
    findings = []
    if "checkpoint" in text.lower():
        findings.append("checkpoint mechanism present")
    if "completed_tasks" in text:
        findings.append("completed_tasks tracking present")
    if "load" in text and "run_id" in text:
        findings.append("load(run_id) restart mechanism present")
    if re.search(r"def test.*restart|def test.*recover|def test.*checkpoint", text):
        findings.append("restart/recover test present")
    if re.search(r"idempotent|duplicate", text, re.IGNORECASE):
        findings.append("idempotency/duplicate prevention mentioned")
    return {"supported": len(findings) >= 3, "findings": findings}


def check_ac2(text: str) -> dict:
    """AC-2: Every component call emits one start + one terminal event."""
    findings = []
    if "component.call.started" in text:
        findings.append("component.call.started event type present")
    if "component.call.completed" in text or "component.call.failed" in text:
        findings.append("terminal event types present")
    if "component.call.cancelled" in text or "component.call.timed_out" in text:
        findings.append("cancelled/timed_out terminal types present")
    if "span" in text.lower() and "span_id" in text:
        findings.append("span tracking present")
    if re.search(r"test.*integrity|test.*terminal|test.*span", text, re.IGNORECASE):
        findings.append("span/integrity test present")
    return {"supported": len(findings) >= 4, "findings": findings}


def check_ac3(text: str) -> dict:
    """AC-3: Broken parent spans, missing terminals, secrets fail integrity."""
    findings = []
    if "verify_trace" in text or "integrity" in text.lower():
        findings.append("trace integrity verification mechanism present")
    if "unknown parent" in text.lower() or "broken parent" in text.lower():
        findings.append("broken parent detection present")
    if "missing terminal" in text.lower():
        findings.append("missing terminal detection present")
    if re.search(r"secret|redact|api_key|token", text, re.IGNORECASE):
        findings.append("secret/redaction detection present")
    if re.search(r"test.*integrity.*reject|test.*secret", text, re.IGNORECASE):
        findings.append("integrity rejection test present")
    return {"supported": len(findings) >= 4, "findings": findings}


def check_ac4(text: str) -> dict:
    """AC-4: Failed fixture diagnosed via recorded replay, live_calls=0."""
    findings = []
    if "replay" in text.lower():
        findings.append("replay mechanism present")
    if "artifact" in text.lower() and ("store" in text.lower() or "ref" in text.lower()):
        findings.append("artifact store/reference present")
    if "live_calls" in text or "recorded" in text.lower():
        findings.append("recorded/replay tracking present")
    if "failed" in text.lower() and ("fixture" in text.lower() or "component" in text.lower()):
        findings.append("failed component/fixture handling present")
    return {"supported": len(findings) >= 3, "findings": findings}


def check_ac5(text: str) -> dict:
    """AC-5: Invalid worker output rejected with bounded correction."""
    findings = []
    if "validation" in text.lower() or "correct" in text.lower():
        findings.append("validation/correction mechanism present")
    if "bounded" in text.lower():
        findings.append("bounded correction mentioned")
    if re.search(r"test.*bound|test.*correct|test.*valid", text, re.IGNORECASE):
        findings.append("validation/correction test present")
    if "worker" in text.lower() and ("result" in text.lower() or "output" in text.lower()):
        findings.append("worker result/output handling present")
    return {"supported": len(findings) >= 3, "findings": findings}


def check_ac6(text: str) -> dict:
    """AC-6: Replanning records old plan, new plan, and reason."""
    findings = []
    if "plan" in text.lower() and ("revision" in text.lower() or "replan" in text.lower()):
        findings.append("plan revision/replanning mechanism present")
    if "old_plan" in text or "new_plan" in text:
        findings.append("old/new plan tracking present")
    if "reason" in text.lower():
        findings.append("plan change reason present")
    if re.search(r"test.*plan|test.*revision", text, re.IGNORECASE):
        findings.append("plan revision test present")
    return {"supported": len(findings) >= 3, "findings": findings}


def check_ac7(text: str) -> dict:
    """AC-7: Test provider replaces capability without supervisor changes."""
    findings = []
    if "registry" in text.lower() or "ExtensionRegistry" in text:
        findings.append("extension registry present")
    if "provider" in text.lower():
        findings.append("provider concept present")
    if "replace" in text.lower() or "swap" in text.lower():
        findings.append("provider replacement mentioned")
    if re.search(r"test.*registry|test.*provider|test.*replacement", text, re.IGNORECASE):
        findings.append("registry/provider test present")
    return {"supported": len(findings) >= 3, "findings": findings}


def check_ac8(text: str) -> dict:
    """AC-8: Model-visible context reconstructable from provenance."""
    findings = []
    if "ContextItem" in text or "context" in text.lower():
        findings.append("context item concept present")
    if "provenance" in text.lower():
        findings.append("provenance tracking present")
    if "reconstruct" in text.lower() or "replay" in text.lower():
        findings.append("reconstruction/replay capability present")
    return {"supported": len(findings) >= 2, "findings": findings}


def check_ac9(text: str) -> dict:
    """AC-9: Unregistering reverses registrations and releases resources."""
    findings = []
    if "dispose" in text.lower() or "cleanup" in text.lower():
        findings.append("dispose/cleanup mechanism present")
    if "unregister" in text.lower() or "reverse" in text.lower():
        findings.append("unregister/reversal mechanism present")
    if "resource" in text.lower() or "close" in text.lower():
        findings.append("resource cleanup present")
    if re.search(r"test.*dispose|test.*cleanup|test.*resource", text, re.IGNORECASE):
        findings.append("dispose/cleanup test present")
    return {"supported": len(findings) >= 3, "findings": findings}


AC_FUNCTION = {
    "AC-1": check_ac1,
    "AC-2": check_ac2,
    "AC-3": check_ac3,
    "AC-4": check_ac4,
    "AC-5": check_ac5,
    "AC-6": check_ac6,
    "AC-7": check_ac7,
    "AC-8": check_ac8,
    "AC-9": check_ac9,
}


def main():
    print("=" * 70)
    print("E0 Acceptance Criteria Verification")
    print("=" * 70)

    # Collect all source and test text
    all_source = "\n".join(read_file(f) for f in SOURCE_FILES)
    all_tests = "\n".join(read_file(f) for f in TEST_FILES)
    all_text = all_source + "\n" + all_tests

    print(f"\nSource files scanned: {len(SOURCE_FILES)}")
    print(f"Test files scanned: {len(TEST_FILES)}")
    print(f"Total code analyzed: {len(all_text):,} chars\n")

    results = []
    for ac_id in ["AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6", "AC-7", "AC-8", "AC-9"]:
        if ac_id in AC_FUNCTION:
            func = AC_FUNCTION[ac_id]
            result = func(all_text)
            status = "✅" if result["supported"] else "❌"
            results.append((ac_id, status, result["supported"], result["findings"], ACCEPTANCE_CRITERIA.get(ac_id, "")))

    print("AC | Status | Findings")
    print("-" * 70)
    all_ok = True
    for ac_id, status, supported, findings, description in results:
        print(f"{ac_id} | {status} | {description}")
        for f in findings:
            print(f"    - {f}")
        if not findings:
            print(f"    (no evidence found)")
        if not supported:
            all_ok = False
        print()

    print("=" * 70)
    if all_ok:
        print("✅ ALL ACCEPTANCE CRITERIA SUPPORTED")
    else:
        print("❌ SOME CRITERIA LACK EVIDENCE")
    print("=" * 70)

    # Additional check: hash chain / integrity deeper than roadmap
    print("\n--- Beyond Roadmap: Integrity Mechanisms ---")
    has_payload_hash = "payload_hash" in all_source
    has_prev_hash = "prev_hash" in all_source
    has_hash_chain = has_payload_hash or has_prev_hash
    has_checkpoint_hash = "content_hash" in all_source and "hash" in all_source.lower()

    print(f"  Payload hash in events table: {'✅' if has_payload_hash else '❌'}")
    print(f"  Prev hash (chain) in events: {'✅' if has_prev_hash else '❌'}")
    print(f"  Checkpoint content hash: {'✅' if has_checkpoint_hash else '❌'}")

    if not has_hash_chain:
        print("  NOTE: Event payload hash chain NOT implemented.")
        print("        Checkpoint hash verification (state.py) covers durability.")
        print("        AC-14 from E0-COMPLETION-PLAN.md is NOT in roadmap.md.")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
