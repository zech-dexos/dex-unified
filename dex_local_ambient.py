"""Dedicated local ambient-pulse process.

Run beside the API process. Load the ambient GGUF before the pulse cadence.
No hosted inference fallback is used.
"""
import asyncio
import json
import os
from pathlib import Path
import time

from local_llm import MODEL_PATH, preload_ambient_model
from dex_ambient_daemon import ambient_pulse_loop
from api import ambient_llm_callable


async def main() -> None:
    if os.environ.get("DEX_LOCAL_RUNTIME") != "1":
        raise RuntimeError("Set DEX_LOCAL_RUNTIME=1 through run_dex_local.sh")

    status_name = os.environ.get("DEX_AMBIENT_STATUS_FILE", "").strip()
    status_path = Path(status_name) if status_name else None
    try:
        print(f"[Ambient Runtime] Preloading model: {MODEL_PATH}", flush=True)
        await asyncio.to_thread(preload_ambient_model)
        if status_path:
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps({
                "loaded": True,
                "model_path": MODEL_PATH,
                "pid": os.getpid(),
                "loaded_at": time.time(),
            }), encoding="utf-8")
        print("[Ambient Runtime] Ambient GGUF loaded; starting pulse loop", flush=True)
        await ambient_pulse_loop(ambient_llm_callable)
    finally:
        if status_path:
            try:
                status_path.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
