"""
gemini_client.py — Gemini caller via Vertex AI (google-genai SDK).
Routes through the project's Cloud billing / credit balance instead of
the AI Studio prepay wallet. Uses Application Default Credentials —
no API key needed. Extracted from api.py so background/cron code
(intent.py, dex_cron.py) can call Gemini without importing api.py's
full module.
"""
import os
from google import genai
from google.genai import types

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "seraphic-disk-506702-d2")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
MODEL_NAME = "gemini-3.6-flash"

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    return _client


async def call_gemini(client, messages, max_tokens=1000):
    """
    Kept async + same signature as the old REST version for drop-in
    compatibility, even though the genai SDK call itself is sync
    under the hood (fine for our usage patterns here).
    """
    try:
        vertex_client = _get_client()
    except Exception as e:
        print(f"[call_gemini] client init exception: {e}")
        return None

    contents = []
    system_text = ""
    for m in messages:
        if m["role"] == "system":
            system_text += m["content"] + "\n"
        elif m["role"] == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
        elif m["role"] == "assistant":
            contents.append(types.Content(role="model", parts=[types.Part(text=m["content"])]))

    if not contents:
        return None

    config = types.GenerateContentConfig(max_output_tokens=max_tokens)
    if system_text:
        config.system_instruction = system_text.strip()

    try:
        response = vertex_client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=config,
        )
        text = response.text
        if text:
            return {"reply": text, "model": MODEL_NAME}
        print(f"[call_gemini] empty response text: {response}")
        return None
    except Exception as e:
        print(f"[call_gemini] exception: {e}")
        return None
