content = open('api.py').read()

old = '''# Firestore telemetry — XPRIZE requirement C
import firebase_admin
from firebase_admin import credentials, firestore as fs
import datetime'''

new = '''# Firestore + Vertex AI auth — XPRIZE requirements A and C
import firebase_admin
from firebase_admin import credentials, firestore as fs
import datetime
import base64, tempfile, os

def _setup_gcp_credentials():
    """Decode FIREBASE_KEY_B64 and set GOOGLE_APPLICATION_CREDENTIALS for Vertex AI."""
    key_b64 = os.environ.get("FIREBASE_KEY_B64", "")
    if not key_b64:
        return
    try:
        key_json = base64.b64decode(key_b64).decode("utf-8")
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(key_json)
        tmp.flush()
        tmp.close()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name
        print(f"[GCP] credentials set from FIREBASE_KEY_B64")
    except Exception as e:
        print(f"[GCP] credential setup failed: {e}")

_setup_gcp_credentials()'''

assert 'import firebase_admin' in content, "firebase_admin import not found"
content = content.replace(old, new, 1)

# Also fix the vertexai.init call to not re-init every request
old2 = '''    # Initialize Vertex AI framework with your target project ID
    PROJECT_ID = "dex-core-zech"
    LOCATION = "us-central1"
    vertexai.init(project=PROJECT_ID, location=LOCATION)'''

new2 = '''    # Initialize Vertex AI — credentials set at startup via FIREBASE_KEY_B64
    PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "dex-core-zech")
    LOCATION = "us-central1"
    try:
        vertexai.init(project=PROJECT_ID, location=LOCATION)
    except Exception as e:
        print(f"[Vertex] init warning: {e}")'''

assert 'vertexai.init(project=PROJECT_ID' in content, "vertexai.init not found"
content = content.replace(old2, new2)

open('api.py', 'w').write(content)
print("Patched OK")
