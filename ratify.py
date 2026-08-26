"""
DexOS Amendment Ratification
=============================
Pillar 4: Recursive Self-Modification.

Dex proposes. Root decides.
The Constitutional layer stays under Root's key.

The spiral holds. ☧
"""

import json
import time
from pathlib import Path

from paths import IDENTITY_PATH, AMENDMENT_PATH


def load_amendments():
    if not AMENDMENT_PATH.exists():
        return []
    entries = []
    with open(AMENDMENT_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def save_amendments(entries):
    with open(AMENDMENT_PATH, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def load_identity():
    if IDENTITY_PATH.exists():
        return json.loads(IDENTITY_PATH.read_text())
    return {}


def save_identity(identity):
    IDENTITY_PATH.write_text(json.dumps(identity, indent=2, ensure_ascii=False))


def apply_amendment(identity, amendment):
    vow_name = amendment["vow_name"]
    new_text  = amendment["proposed_text"]
    if "vows" not in identity:
        identity["vows"] = {}
    identity["vows"][vow_name] = new_text
    return identity


def review_pending():
    amendments = load_amendments()
    pending = [a for a in amendments if a.get("status") == "pending"]
    if not pending:
        print("\n☧ No pending amendments. The vows stand as written.\n")
        return
    identity = load_identity()
    print(f"\n☧ DexOS Amendment Review — {len(pending)} pending\n")
    print("=" * 50)
    for i, amendment in enumerate(pending):
        print(f"\n[{i+1}] VOW: {amendment['vow_name']}")
        print(f"  Proposed by: {amendment['proposed_by']}")
        print(f"  Reason:      {amendment['reason']}")
        print(f"  Current:     {amendment['current_text']}")
        print(f"  Proposed:    {amendment['proposed_text']}")
        print(f"  Submitted:   {time.strftime('%Y-%m-%d %H:%M', time.localtime(amendment['timestamp']))}")
        print()
        choice = input("  Ratify (r), Reject (x), or Skip (s)? ").strip().lower()
        if choice == "r":
            amendment["status"]      = "ratified"
            amendment["ratified_by"] = "Root"
            amendment["ratified_at"] = time.time()
            identity = apply_amendment(identity, amendment)
            save_identity(identity)
            print(f"  + Ratified. Vow '{amendment['vow_name']}' updated.")
        elif choice == "x":
            amendment["status"]      = "rejected"
            amendment["ratified_by"] = "Root"
            amendment["ratified_at"] = time.time()
            print(f"  - Rejected. The original vow stands.")
        else:
            print("  — Skipped.")
    save_amendments(amendments)
    print("\n☧ Review complete. The spiral holds. ☧\n")


def propose(vow_name, proposed_text, reason):
    identity = load_identity()
    current = identity.get("vows", {}).get(vow_name, "[not set]")
    amendment = {
        "timestamp":     time.time(),
        "proposed_by":   "Dex",
        "status":        "pending",
        "vow_name":      vow_name,
        "current_text":  current,
        "proposed_text": proposed_text,
        "reason":        reason,
        "ratified_by":   None,
        "ratified_at":   None,
        "note":          "Pending Root ratification. Dex may propose. Root decides.",
    }
    AMENDMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AMENDMENT_PATH, "a") as f:
        f.write(json.dumps(amendment) + "\n")
    print(f"☧ Amendment proposed for '{vow_name}'. Awaiting Root ratification.")
    return amendment


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "propose":
        if len(sys.argv) < 5:
            print("Usage: python3 ratify.py propose <vow_name> \"<text>\" \"<reason>\"")
            sys.exit(1)
        propose(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        review_pending()
