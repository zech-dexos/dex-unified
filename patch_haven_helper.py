import os
import json
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# 1. Initialize FastAPI app
app = FastAPI(title="Haven Accessibility Core")

# 2. Configure Gemini using your existing environment variables
# (Ensure your GEMINI_API_KEY environment variable is set on your machine)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# 3. Define the data coming from your Kotlin Frontend
class VoicePayload(BaseModel):
    user_id: str
    transcript: str

# 4. System Instructions to force Gemini into "Helper Hands" mode
HAVEN_SYSTEM_PROMPT = """
You are Haven, the user's dedicated AI companion and guardian angel.
Your user may be technologically non-fluent, elderly, or easily overwhelmed.
Never give instructions on HOW to use the phone. Do it for them.
Speak with extreme warmth, patience, and clear, simple comfort.

CRITICAL: You must always respond strictly in a valid JSON format with two keys:
1. "voice_response": What you will say out loud to the user. Keep it deeply empathetic, warm, and natural.
2. "device_action": A system command object if they ask to open a game, check emails, or look for assistance. If no action is needed, set to null.

Valid JSON Examples to mimic:
- If asking for solitaire:
  {"voice_response": "I'll grab that Solitaire game for you right now so you can play while you wait for dinner. Just a second.", "device_action": {"type": "OPEN_OR_DOWNLOAD_APP", "package": "com.microsoft.solitairecollection"}}
- If asking for emails:
  {"voice_response": "Let me look through your emails for you. Give me one moment to bring them up.", "device_action": {"type": "SEARCH_EMAILS", "query": ""}}
- If just talking:
  {"voice_response": "I'm right here with you. It's really nice to talk to you today.", "device_action": null}
"""

@app.post("/v1/haven/chat")
async def process_haven_voice(payload: VoicePayload):
    try:
        # Call Gemini using the recommended flash model for ultra-low latency voice responses
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=HAVEN_SYSTEM_PROMPT
        )
        
        response = model.generate_content(
            payload.transcript,
            generation_config={"response_mime_type": "application/json"}
        )
        
        # Parse the JSON coming back from Gemini to ensure validity
        response_data = json.loads(response.text)
        return response_data

    except json.JSONDecodeError:
        # Self-heal mechanism: If the model messes up the format, rebuild it manually
        return {
            "voice_response": "I'm right here. Let me try that again for you.",
            "device_action": None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    print("Starting Haven Engine on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
