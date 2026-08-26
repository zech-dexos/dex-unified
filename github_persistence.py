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
import requests
from pathlib import Path

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "zech-dexos/dexos-core"
API = "https://api.github.com"

FILES_TO_PERSIST = [
    "dex_lineage.jsonl",
    "identity.json",
    "self_model.json",
    "counterfactual_archive.jsonl"
]

from paths import _STATE_BASE as STATE_DIR

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
                (STATE_DIR / filename).write_text(content)
                pulled += 1
                print(f"✓ Pulled {filename} from GitHub")
            else:
                print(f"→ {filename} not in GitHub yet — will create on push")
        except Exception as e:
            print(f"Pull error {filename}: {e}")
    
    return pulled > 0

def push_to_github():
    """Push current state files from Railway to GitHub."""
    if not GITHUB_TOKEN:
        print("No GITHUB_TOKEN — skipping push")
        return False
    
    pushed = 0
    
    for filename in FILES_TO_PERSIST:
        filepath = STATE_DIR / filename
        if not filepath.exists():
            continue
        
        try:
            content = filepath.read_text()
            encoded = base64.b64encode(content.encode()).decode()
            
            # Get current SHA if file exists
            url = f"{API}/repos/{REPO}/contents/{filename}"
            r = requests.get(url, headers=_headers(), timeout=10)
            sha = r.json().get("sha") if r.status_code == 200 else None
            
            payload = {
                "message": f"DexOS state update — {filename} ☧",
                "content": encoded
            }
            if sha:
                payload["sha"] = sha
            
            r = requests.put(url, headers=_headers(), 
                           json=payload, timeout=10)
            
            if r.status_code in (200, 201):
                pushed += 1
                print(f"✓ Pushed {filename} to GitHub")
            else:
                print(f"Push error {filename}: {r.status_code}")
                
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
