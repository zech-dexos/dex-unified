"""
gemini_client.py — standalone Gemini REST caller, no vertexai dependency.
Extracted from api.py so background/cron code (intent.py, dex_cron.py) can
call Gemini without importing api.py's full module (which pulls in
vertexai at import time and is meant for the live request path only).
"""
import os

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")


async def call_gemini(client, messages, max_tokens=1000):
    if not GEMINI_KEY:
        return None
    contents = []
    system_text = ""
    for m in messages:
        if m["role"] == "system":
            system_text += m["content"] + "\n"
        elif m["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif m["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": m["content"]}]})
    if not contents:
        return None
    payload = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text.strip()}]}
    try:
        res = await client.post(
            f"{GEMINI_URL}?key={GEMINI_KEY}",
            headers={"Content-Type": "application/json"},
            json=payload,
        )
        data = res.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            if text:
                return {"reply": text, "model": "gemini-2.5-flash"}
    except Exception:
        pass
    return None
