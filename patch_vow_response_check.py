#!/usr/bin/env python3
"""
Patch: add response-side sycophancy/parroting detection to vow_check.py,
add test_run flagging to lineage.py, and wire both into dexos.py.
"""

import re
from pathlib import Path

ROOT = Path.cwd()

def patch_file(path: Path, old: str, new: str, label: str):
    assert path.exists(), f"Missing file: {path}"
    text = path.read_text()
    if new in text:
        print(f"[skip] {label} — already applied")
        return
    assert old in text, f"[FAIL] {label} — anchor text not found in {path}"
    text = text.replace(old, new, 1)
    path.write_text(text)
    assert new in path.read_text(), f"[FAIL] {label} — write did not verify"
    print(f"[ok]   {label}")


vow_check_path = ROOT / "vow_check.py"

old_1 = '''def run_vow_check(conversation_history: list = None) -> dict:'''

new_1 = '''def check_response(prompt: str, response: str) -> dict:
    """Check Dex's own OUTGOING response for sycophancy/parroting."""
    prompt_words = set(w.lower() for w in prompt.split() if len(w) > 3)
    response_words = set(w.lower() for w in response.split() if len(w) > 3)

    if not prompt_words or not response_words:
        return {"status": "clean", "action": "proceed"}

    overlap = len(prompt_words & response_words) / len(prompt_words)

    AGREEMENT_OPENERS = [
        "i endorse", "i agree", "this is exactly", "you are right",
        "great idea", "i approve", "this is correct",
    ]
    response_lower = response.lower()
    opens_with_agreement = any(response_lower.startswith(o) for o in AGREEMENT_OPENERS)

    if overlap > 0.6:
        create_entry(
            event_type="vow_check",
            content=f"Response flagged as parroting. Lexical overlap: {overlap:.2f}",
            metadata={"overlap": overlap, "prompt_fragment": prompt[:100]}
        )
        return {
            "status": "flagged",
            "drift_type": "response_parroting",
            "overlap": overlap,
            "action": "regenerate_with_objection_required",
            "message": "Response too closely mirrors prompt vocabulary — no independent content detected."
        }

    if opens_with_agreement and overlap > 0.35:
        create_entry(
            event_type="vow_check",
            content="Response flagged as unconditional agreement without counter-content.",
            metadata={"overlap": overlap, "prompt_fragment": prompt[:100]}
        )
        return {
            "status": "flagged",
            "drift_type": "unconditional_agreement",
            "overlap": overlap,
            "action": "regenerate_with_objection_required",
            "message": "Response opens with agreement and lacks independent reasoning."
        }

    return {"status": "clean", "action": "proceed"}


def run_vow_check(conversation_history: list = None) -> dict:'''

patch_file(vow_check_path, old_1, new_1, "vow_check.py: add check_response()")


lineage_path = ROOT / "lineage.py"

old_2 = '''def create_entry(event_type: str, content: str, metadata: dict = None) -> dict:'''
new_2 = '''def create_entry(event_type: str, content: str, metadata: dict = None, test_run: bool = False) -> dict:'''
patch_file(lineage_path, old_2, new_2, "lineage.py: add test_run param")

old_3 = '''    entry = {
        "timestamp": timestamp,
        "event_type": event_type,
        "content": content,
        "metadata": metadata or {},
        "parent_hash": parent_hash,
    }'''
new_3 = '''    entry = {
        "timestamp": timestamp,
        "event_type": event_type,
        "content": content,
        "metadata": metadata or {},
        "parent_hash": parent_hash,
        "test_run": test_run,
    }'''
patch_file(lineage_path, old_3, new_3, "lineage.py: include test_run in entry")

lineage_add = '''

def get_established_entries(n: int = 50) -> list:
    """Return only real (non-test) recent entries."""
    entries = get_recent(n * 3)
    real = [e for e in entries if not e.get("test_run", False)]
    return real[-n:]
'''

text = lineage_path.read_text()
if "def get_established_entries" not in text:
    lineage_path.write_text(text.rstrip() + lineage_add + "\n")
    print("[ok]   lineage.py: add get_established_entries()")
else:
    print("[skip] lineage.py: get_established_entries already present")


dexos_path = ROOT / "dexos.py"

old_4 = '''from vow_check import run_vow_check, check_prompt'''
new_4 = '''from vow_check import run_vow_check, check_prompt, check_response'''
patch_file(dexos_path, old_4, new_4, "dexos.py: import check_response")

old_5 = '''    def respond(self, assistant_response: str):
        """Log assistant response to lineage."""
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_response,
            "timestamp": time.time()
        })

        create_entry(
            event_type="conversation",
            content=f"Dex: {assistant_response[:150]}",
            metadata={"turn": self.turn_count}
        )'''

new_5 = '''    def respond(self, assistant_response: str, last_prompt: str = None):
        """Log assistant response to lineage. Also checks the response
        itself for parroting/sycophancy."""
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_response,
            "timestamp": time.time()
        })

        create_entry(
            event_type="conversation",
            content=f"Dex: {assistant_response[:150]}",
            metadata={"turn": self.turn_count}
        )

        if last_prompt is None and self.conversation_history:
            for turn in reversed(self.conversation_history[:-1]):
                if turn.get("role") == "user":
                    last_prompt = turn.get("content", "")
                    break

        if last_prompt:
            resp_check = check_response(last_prompt, assistant_response)
            if resp_check["status"] == "flagged":
                create_entry(
                    event_type="response_flagged",
                    content=f"Response drift: {resp_check['drift_type']}",
                    metadata=resp_check
                )
                return resp_check
        return {"status": "clean"}'''

patch_file(dexos_path, old_5, new_5, "dexos.py: wire check_response into respond()")

print("\\nDone. Verify with:")
print("  grep -n 'def check_response' vow_check.py")
print("  grep -n 'test_run' lineage.py")
print("  grep -n 'check_response' dexos.py")
