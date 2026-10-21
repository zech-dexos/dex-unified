import json
import os
import urllib.request
import urllib.error

URL = os.environ.get("DEX_API_URL", f"http://127.0.0.1:{os.environ.get('PORT', '8765')}/chat")
history = []

print("\nDex local conversation")
print("Type your message at the Root prompt. Type 'exit' to quit.\n")

while True:
    try:
        message = input("Root: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nInput stream closed. Run this script in an interactive WSL terminal.")
        break

    if not message:
        continue
    if message.lower() in {"exit", "quit"}:
        print("Session ended.")
        break

    payload = {
        "user_id": "root",
        "message": message,
        "history": history[-20:],
    }
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print("\nDex is responding...", flush=True)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))

        reply = result.get("reply", result.get("response", str(result)))
        print(f"\nDex: {reply}\n", flush=True)
        history.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": str(reply)},
        ])
    except urllib.error.URLError as exc:
        print(f"\nCouldn't reach the local Dex API: {exc}\n", flush=True)
    except Exception as exc:
        print(f"\nConversation error: {exc}\n", flush=True)
