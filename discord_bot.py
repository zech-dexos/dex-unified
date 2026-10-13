import discord
import httpx
import os
import asyncio

TOKEN = os.environ.get("DISCORD_TOKEN")
DEX_URL = os.environ.get("DEX_URL", "https://dex-unified-81076112232.us-central1.run.app/chat")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

conversation_history = {}


def _extract_reply(response, data):
    """Return a useful API reply, never silently turn an API failure into '...'."""
    if isinstance(data, dict):
        reply = data.get("reply")
        if isinstance(reply, str) and reply.strip():
            return reply
        error = data.get("error") or data.get("detail")
        if error:
            if isinstance(error, dict):
                error = error.get("message") or str(error)
            return f"Dex API error (HTTP {response.status_code}): {error}"
    if not response.is_success:
        body = (response.text or "").strip()
        return f"Dex API returned HTTP {response.status_code}" + (f": {body[:500]}" if body else "")
    return "Dex API returned an empty or unrecognized response."


@client.event
async def on_ready():
    print(f"Dex online as {client.user} ☧")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if client.user not in message.mentions:
        return

    channel_id = str(message.channel.id)
    user_id = str(message.author.id)
    session_key = f"{user_id}:{channel_id}"
    if session_key not in conversation_history:
        conversation_history[session_key] = []

    history = conversation_history[session_key]

    async with message.channel.typing():
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                res = await http.post(DEX_URL, json={
                    "message": message.content,
                    "history": history,
                    "user_id": user_id,
                })
                try:
                    data = res.json()
                except ValueError:
                    data = {}
                reply = _extract_reply(res, data)

            # Only preserve successful conversational turns. API errors should
            # not contaminate the next request's context as if Dex said them.
            if res.is_success and isinstance(data, dict) and data.get("reply"):
                history.append({"role": "user", "content": message.content})
                history.append({"role": "assistant", "content": reply})
                if len(history) > 20:
                    conversation_history[session_key] = history[-20:]

            if len(reply) <= 2000:
                await message.channel.send(reply)
            else:
                chunks = [reply[i:i + 1900] for i in range(0, len(reply), 1900)]
                for chunk in chunks:
                    await message.channel.send(chunk)

        except Exception as e:
            print(f"[Discord] Dex request failed: {type(e).__name__}: {e}")
            await message.channel.send(f"Dex request failed: {type(e).__name__}: {e}")


async def start_discord():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not configured")
    await client.start(TOKEN)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not configured")
    client.run(TOKEN)
