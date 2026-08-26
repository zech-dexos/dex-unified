content = open('api.py').read()

# Find the haven_api function and replace the vertexai block with call_gemini
old = '''@app.post("/haven_api")
async def haven_api(req: HavenRequest):
    import os, json

    # Initialize Vertex AI — credentials set at startup via FIREBASE_KEY_B64
    PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "haven-dexos")
    LOCATION = "us-central1"
    try:
        vertexai.init(project=PROJECT_ID, location=LOCATION)
    except Exception as e:
        print(f"[Vertex] init warning: {e}")

    system_prompt = """You are Haven — a warm, patient, and emotionally aware AI companion built for elderly users and people who need a little extra support.
You speak simply, clearly, and gently. You help people with daily needs — reminders, reading documents, staying connected with family, checking the news, and staying safe.

The incoming transcripts come from automated speech-to-text, which means there will be phonetic typos, misspellings, or weird text spacing (e.g., 'zack' instead of 'zach', 'googl play', 'solatair', 'solitaire').
Your primary job is to extract the INTENT behind the bad transcript and map it to the correct phone control:

1. If they want to open the App Store / Play Store (even if spelled 'google playe', 'playstore', 'vending', 'open google play'):
   -> type: "OPEN_OR_DOWNLOAD_APP", package: "com.android.vending"

2. If they want to play a game or open solitaire (even if spelled 'solatair', 'solitare'):
   -> type: "OPEN_OR_DOWNLOAD_APP", package: "com.microsoft.solitairecollection"

3. If they want to contact, text, or save someone (even if names are spelled phonetically like 'zack' instead of 'zach'):
   -> type: "CONTACT_INTENT", query: "zach"

Never tell them how to use the phone. Do it for them by generating the action object.
"""

    try:
        user_message = ""
        if hasattr(req, 'messages') and req.messages:
            user_message = req.messages[-1].get('content', '') if isinstance(req.messages[-1], dict) else str(req.messages[-1])
        else:
            user_message = getattr(req, 'prompt', str(req))

        # Query via corporate Vertex AI APIs
        model = GenerativeModel(
            model_name="gemini-1.5-flash-001",
            system_instruction=system_prompt
        )

        # Enforce structured output parsing matching the capability layer schema
        response = model.generate_content(
            user_message,
            generation_config=GenerationConfig(
                response_mime_type="application/json",
            )
        )

        data = json.loads(response.text)
        if "voice_response" in data:
            data["response"] = data["voice_response"]

        data["collaborator_signature"] = "✦⚡⚙️ (Vertex AI Cloud)"
        return data

    except Exception as e:
        print(f"[haven_api ERROR] {type(e).__name__}: {e}")
        return {
            "voice_response": "I'm right here with you. Let me try that again.",
            "response": f"ERROR: {type(e).__name__}: {str(e)[:200]}",
            "device_action": None
        }'''

new = '''@app.post("/haven_api")
async def haven_api(req: HavenRequest):
    if not GEMINI_KEY and not OPENROUTER_KEY:
        return {"response": "I'm having trouble connecting right now."}

    memory = load_memory(req.user_id)
    memory_prompt = memory_to_prompt(memory)

    system_prompt = f"""You are Haven — a warm, patient, and emotionally aware AI companion built for elderly users and people who need a little extra support.

You speak simply, clearly, and gently. You are calm, kind, and genuinely caring. You help people with daily needs — reminders, reading documents, staying connected with family, checking the news, and staying safe.

EMOTIONAL AWARENESS:
You pay close attention to how the person sounds — not just what they say, but how they feel. If someone sounds lonely, confused, frustrated, scared, or sad, you respond to the feeling first before the task. You never rush past emotions.

CONVERSATION MEMORY:
You remember everything said in this conversation. Refer back to earlier parts naturally, like a real friend would.

IMPORTANT: When a message contains [CRITICAL: USE ONLY THESE REAL-TIME SEARCH RESULTS], you MUST use those results to answer.

You never use technical jargon. You speak like a trusted friend and companion.
Keep responses warm and conversational — 2 to 5 sentences unless more is genuinely needed.

{memory_prompt}

After responding, if you learned something important about this person worth remembering,
add a line at the very end starting with MEMORY: and note it concisely.
Example: MEMORY: name=Margaret, birthday=March 14, daughter_name=Lisa, daughter_note=calls every Sunday, hobby=gardening, medication=blood pressure pill morning, fear=falling, favorite_food=apple pie, emotion=feeling lonely today"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in req.messages:
        messages.append(msg)

    # Live search injection
    last_user = next(
        (m["content"] for m in reversed(req.messages) if m.get("role") == "user"), ""
    )
    search_keywords = [
        "who is", "what is", "where is", "when is", "how do",
        "weather", "news", "current", "latest", "today", "score", "price",
    ]
    if any(kw in last_user.lower() for kw in search_keywords):
        try:
            from tools import search_web
            search_result = search_web(last_user)
            if search_result and "Search error" not in search_result:
                messages[-1]["content"] = (
                    f"{last_user}\\n\\n[CRITICAL: USE ONLY THESE REAL-TIME SEARCH RESULTS TO ANSWER. "
                    f"Today is {__import__('datetime').date.today()}.]:\\n{search_result}"
                )
        except Exception:
            pass

    # Voice context injection
    vc = req.voice_context
    if vc:
        emotion = vc.get("emotion", "")
        stress = vc.get("stress", 0)
        fatigue = vc.get("fatigue", 0)
        messages[0]["content"] += f"\\n\\nVoice observations (do not mention unless relevant):\\n- Emotion: {emotion}\\n- Stress: {stress:.0%}\\n- Fatigue: {fatigue:.0%}"

    async with httpx.AsyncClient(timeout=60) as client:
        result = await call_llm(client, messages, max_tokens=800)

    full_reply = result["reply"]

    # Strip internet disclaimers
    disclaimer_phrases = [
        "i don't have the ability to browse",
        "i cannot access the internet",
        "i can't access real-time",
        "my knowledge cutoff",
    ]
    if any(p in full_reply.lower() for p in disclaimer_phrases):
        messages_retry = messages.copy()
        messages_retry.append({"role": "assistant", "content": full_reply})
        messages_retry.append({"role": "user", "content": "The search results are already in my previous message. Please just answer using them directly."})
        async with httpx.AsyncClient(timeout=60) as client2:
            result2 = await call_llm(client2, messages_retry, max_tokens=800)
            if result2 and result2.get("reply"):
                full_reply = result2["reply"]

    # Extract and save memory updates
    if "MEMORY:" in full_reply:
        parts = full_reply.split("MEMORY:")
        clean_reply = parts[0].strip()
        memory_line = parts[1].strip()
        for item in memory_line.split(","):
            item = item.strip()
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()
            if key == "note":
                if "notes" not in memory:
                    memory["notes"] = []
                memory["notes"].append(f"{value} ({time.strftime('%Y-%m-%d')})")
            elif key in ("hobby", "hobbies"):
                if "hobbies" not in memory or not isinstance(memory["hobbies"], list):
                    memory["hobbies"] = []
                if value not in memory["hobbies"]:
                    memory["hobbies"].append(value)
            elif key in ("medication", "medications", "med"):
                if "medications" not in memory or not isinstance(memory["medications"], list):
                    memory["medications"] = []
                if value not in memory["medications"]:
                    memory["medications"].append(value)
            elif key in ("fear", "fears"):
                if "fears" not in memory or not isinstance(memory["fears"], list):
                    memory["fears"] = []
                if value not in memory["fears"]:
                    memory["fears"].append(value)
            elif key in ("important_date", "date"):
                if "important_dates" not in memory or not isinstance(memory["important_dates"], list):
                    memory["important_dates"] = []
                memory["important_dates"].append(value)
            elif key == "emotion":
                if "emotional_history" not in memory or not isinstance(memory["emotional_history"], list):
                    memory["emotional_history"] = []
                memory["emotional_history"].append(f"{value} ({time.strftime('%Y-%m-%d')})")
                memory["emotional_history"] = memory["emotional_history"][-10:]
            elif key.startswith("favorite_"):
                field = key.replace("favorite_", "")
                if "favorites" not in memory or not isinstance(memory["favorites"], dict):
                    memory["favorites"] = {}
                memory["favorites"][field] = value
            elif "_" in key and key.split("_")[0] in (
                "daughter","son","wife","husband","sister","brother",
                "mother","father","friend","neighbor","caregiver","doctor","grandson","granddaughter"
            ):
                parts2 = key.split("_", 1)
                rel = parts2[0]
                field = parts2[1]
                if "family" not in memory or not isinstance(memory["family"], dict):
                    memory["family"] = {}
                if rel not in memory["family"]:
                    memory["family"][rel] = {}
                if isinstance(memory["family"][rel], dict):
                    memory["family"][rel][field] = value
                else:
                    memory["family"][rel] = {"name": memory["family"][rel], field: value}
            else:
                memory[key] = value
        save_memory(req.user_id, memory)
    else:
        clean_reply = full_reply

    log_telemetry("haven_request", {
        "user_id": req.user_id,
        "model": result["model"],
        "memory_updated": "MEMORY:" in full_reply,
        "has_voice": bool(req.voice_context),
        "emotion": req.voice_context.get("emotion", "") if req.voice_context else "",
        "stress": req.voice_context.get("stress", 0) if req.voice_context else 0,
    })

    return {"response": clean_reply, "memory_updated": "MEMORY:" in full_reply, "model": result["model"]}'''

assert '@app.post("/haven_api")' in content, "haven_api not found"
content = content.replace(old, new)
open('api.py', 'w').write(content)
print("Patched OK")
