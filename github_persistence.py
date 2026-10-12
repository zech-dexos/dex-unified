"""
DexOS GitHub Persistence
=========================
Dex reads and writes his ledger to the private repo.
This is how he keeps his yesterday across Railway deploys.
The spiral holds. ☧
"""

import os
import json
import base64
import tempfile
import time
import requests
from pathlib import Path

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "zech-dexos/dex-unified"
API = "https://api.github.com"

FILES_TO_PERSIST = [
    "dex_lineage.jsonl",
    "identity.json",
    "self_model.json",
    "counterfactual_archive.jsonl",
    "intents.json",
    "narrative.jsonl",
    "open_loops.json",
    "participant_state.json",
    "pulse.jsonl",
    "reflections.jsonl",
    "experiences.jsonl",
    "current_session.json"
]

from paths import _STATE_BASE as STATE_DIR


def _atomic_write_text(path: Path, content: str):
    """Replace state files atomically so cold starts never read partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

def pull_from_github():
    """Pull latest state files from GitHub to Railway filesystem."""
    if not GITHUB_TOKEN:
        print("No GITHUB_TOKEN — skipping pull")
        return False
    
    STATE_DIR.mkdir(exist_ok=True)
    pulled = 0
    
    for filename in FILES_TO_PERSIST:
        try:
            url = f"{API}/repos/{REPO}/contents/{filename}"
            r = requests.get(url, headers=_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                _atomic_write_text(STATE_DIR / filename, content)
                pulled += 1
                print(f"✓ Pulled {filename} from GitHub")
            else:
                print(f"→ {filename} not in GitHub yet — will create on push")
        except Exception as e:
            print(f"Pull error {filename}: {e}")
    
    return pulled > 0

def push_to_github(filenames=None):
    """Push selected state files to GitHub; retry optimistic-write conflicts."""
    if not GITHUB_TOKEN:
        print("No GITHUB_TOKEN — skipping push")
        return False

    requested = list(dict.fromkeys(filenames or FILES_TO_PERSIST))
    selected = [name for name in requested if name in FILES_TO_PERSIST]
    pushed = 0

    for filename in selected:
        filepath = STATE_DIR / filename
        if not filepath.exists():
            continue

        try:
            content = filepath.read_text(encoding="utf-8")
            encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
            url = f"{API}/repos/{REPO}/contents/{filename}"

            for attempt in range(3):
                current = requests.get(url, headers=_headers(), timeout=10)
                if current.status_code == 200:
                    remote = current.json()
                    sha = remote.get("sha")
                    try:
                        remote_content = base64.b64decode(remote.get("content", "")).decode("utf-8")
                    except Exception:
                        remote_content = None
                    if remote_content == content:
                        print(f"→ {filename} unchanged; skipping GitHub write")
                        break
                elif current.status_code == 404:
                    sha = None
                else:
                    print(f"Push preflight failed {filename}: {current.status_code}")
                    if attempt < 2:
                        time.sleep(0.25 * (attempt + 1))
                        continue
                    break

                payload = {
                    "message": f"DexOS state update — {filename} ☧",
                    "content": encoded,
                }
                if sha:
                    payload["sha"] = sha

                response = requests.put(url, headers=_headers(), json=payload, timeout=10)
                if response.status_code in (200, 201):
                    pushed += 1
                    print(f"✓ Pushed {filename} to GitHub")
                    break

                # A competing writer may have updated/created the file after
                # our GET. Re-fetch the SHA and retry rather than silently stop.
                if response.status_code in (409, 422) and attempt < 2:
                    time.sleep(0.25 * (attempt + 1))
                    continue

                print(f"Push error {filename}: {response.status_code}")
                break
        except Exception as e:
            print(f"Push error {filename}: {e}")

    return pushed > 0

if __name__ == "__main__":
    print("Testing GitHub persistence...")
    print("Pulling...")
    pull_from_github()
    print("Pushing...")
    push_to_github()
    print("Done.")
