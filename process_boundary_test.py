"""
process_boundary_test.py — the acceptance test for Phase 3.1/3.2.

Every step below runs as a SEPARATE subprocess (separate python3
invocation, separate interpreter, no shared memory) — not sequential
function calls in one process. That's the actual claim being tested:
a thought survives the inference that created it, not just survives
staying in the same Python session.

Matches the 10-step spec exactly:
 1. Create a thought.
 2. Persist it.
 3. Terminate the process.
 4. Start a fresh process.
 5. Load the thought.
 6. Verify it still exists.
 7. Update it.
 8. Persist the revision.
 9. Start another fresh process.
10. Verify the revised thought exists with its history intact.
"""

import json
import subprocess
import sys
from pathlib import Path

TEST_PATH = Path("process_boundary_test.state.json")
HERE = Path(__file__).resolve().parent


def run_step(code: str) -> str:
    """Run `code` in a brand new python3 process. Returns stdout, raises on nonzero exit."""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(HERE),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{result.stderr}")
    return result.stdout.strip()


def main():
    if TEST_PATH.exists():
        TEST_PATH.unlink()

    # Steps 1-2: create a thought, persist it — in its own process
    thought_id = run_step(f"""
import thought
from pathlib import Path
t = thought.form_thought(
    "Dex should check whether continuity survives a full process restart.",
    priority="high",
    path=Path("{TEST_PATH.name}"),
)
print(t["thought_id"])
""")
    assert thought_id, "step 1-2: no thought_id returned"

    # Step 3: (implicit — the subprocess above already exited/terminated)

    # Steps 4-6: fresh process, load the thought, verify it exists
    verify_output = run_step(f"""
import json
import thought
from pathlib import Path
t = thought.get_thought("{thought_id}", path=Path("{TEST_PATH.name}"))
assert t is not None, "thought not found in fresh process"
assert t["status"] == "active"
assert t["attention_count"] == 1
print(json.dumps(t))
""")
    loaded = json.loads(verify_output)
    assert loaded["thought_id"] == thought_id
    assert loaded["content"] == "Dex should check whether continuity survives a full process restart."

    # Steps 7-8: fresh process, revisit + update it, persist the revision
    update_output = run_step(f"""
import json
import thought
from pathlib import Path
revisited = thought.revisit_thought("{thought_id}", path=Path("{TEST_PATH.name}"))
assert revisited["attention_count"] == 2, "revisit should have incremented attention_count"
updated = thought.update_thought(
    "{thought_id}",
    decision="continue",
    new_content="Confirmed: continuity survives a full process restart.",
    note="Verified via process_boundary_test step 7-8.",
    path=Path("{TEST_PATH.name}"),
)
print(json.dumps(updated))
""")
    updated = json.loads(update_output)
    assert updated["status"] == "active"
    assert len(updated["revisions"]) == 1

    # Steps 9-10: ANOTHER fresh process, verify the revision persisted with history intact
    final_output = run_step(f"""
import json
import thought
from pathlib import Path
t = thought.get_thought("{thought_id}", path=Path("{TEST_PATH.name}"))
assert t is not None, "thought vanished after second process restart"
assert t["content"] == "Confirmed: continuity survives a full process restart."
assert len(t["revisions"]) == 1, f"expected 1 revision, got {{len(t['revisions'])}}"
assert t["revisions"][0]["previous_content"] == "Dex should check whether continuity survives a full process restart."
assert t["attention_count"] == 2
print(json.dumps(t))
""")
    final = json.loads(final_output)
    assert final["status"] == "active"
    assert final["revisions"][0]["note"] == "Verified via process_boundary_test step 7-8."

    TEST_PATH.unlink()
    print("process_boundary_test.py: ALL 10 STEPS PASSED")
    print("Confirmed across 3 separate process invocations:")
    print("  - a thought formed in process A exists in process B")
    print("  - a revision made in process B exists in process C")
    print("  - revision history and attention_count both survive process termination")


if __name__ == "__main__":
    main()
