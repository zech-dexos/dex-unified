"""Dedicated local ambient-pulse process.

Run this beside the API process. It loads the configured small GGUF before
starting the pulse cadence, and it never uses a hosted inference fallback.
"""
import asyncio
import os

from local_llm import MODEL_PATH, preload_ambient_model
from dex_ambient_daemon import ambient_pulse_loop
from api import ambient_llm_callable


async def main() -> None:
    if os.environ.get("DEX_LOCAL_RUNTIME") != "1":
        raise RuntimeError("Set DEX_LOCAL_RUNTIME=1 through run_dex_local.sh")
    print(f"[Ambient Runtime] Preloading model: {MODEL_PATH}", flush=True)
    await asyncio.to_thread(preload_ambient_model)
    print("[Ambient Runtime] Ambient GGUF loaded; starting pulse loop", flush=True)
    await ambient_pulse_loop(ambient_llm_callable)


if __name__ == "__main__":
    asyncio.run(main())
