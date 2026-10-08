"""
SparkReach — bounded, asynchronous cognitive substrate execution.

SparkReach is not another identity or autonomous agent. It is a bounded
execution limb that Dex can deliberately invoke. A reach is queued and the
caller receives immediately; completion is written back into durable state so
a later cognition cycle can observe and judge the result.

The process runs inside the existing application/container boundary. It is
NOT a hardened security sandbox: Python remains subject to the host/container
filesystem and network boundary. Only Python source is accepted, with an
isolated per-run working directory, timeout, address-space limit, CPU limit,
and file-size limit.
"""

import concurrent.futures
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from paths import _STATE_BASE
from self_state import update_self_state

SPARK_REACH_ROOT = Path(
    os.environ.get("SPARK_REACH_ROOT", str(_STATE_BASE.parent / "tmp" / "spark_reach"))
)
SPARK_REACH_ROOT.mkdir(parents=True, exist_ok=True)

SPARK_TIMEOUT_SECONDS = max(
    1, int(os.environ.get("SPARK_REACH_TIMEOUT_SECONDS", "20"))
)
SPARK_MEMORY_MB = max(
    32, int(os.environ.get("SPARK_REACH_MEMORY_MB", "256"))
)
SPARK_MAX_CODE_BYTES = max(
    1024, int(os.environ.get("SPARK_REACH_MAX_CODE_BYTES", "65536"))
)

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, int(os.environ.get("SPARK_REACH_WORKERS", "2"))),
    thread_name_prefix="spark-reach",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _apply_limits(timeout_seconds: int, memory_mb: int) -> None:
    """Apply Unix process limits when the host supports resource.setrlimit."""
    try:
        import resource

        limit = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (timeout_seconds, timeout_seconds),
        )
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
    except Exception:
        # The surrounding subprocess timeout remains authoritative where
        # platform-level rlimits are unavailable.
        pass


def _execute(run_id: str, code: str, timeout_seconds: int, memory_mb: int) -> Dict[str, Any]:
    run_dir = SPARK_REACH_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()

    try:
        code_path = run_dir / "spark.py"
        code_path.write_text(code, encoding="utf-8")

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "SPARK_REACH_RUN_ID": run_id,
        }

        proc = subprocess.run(
            [sys.executable, "-I", "-u", str(code_path)],
            cwd=str(run_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            preexec_fn=(lambda: _apply_limits(timeout_seconds, memory_mb)) if os.name == "posix" else None,
        )

        status = "success" if proc.returncode == 0 else "error"
        if proc.returncode < 0:
            status = "halted"

        return {
            "run_id": run_id,
            "status": status,
            "stdout": proc.stdout[-20000:],
            "stderr": proc.stderr[-20000:],
            "return_code": proc.returncode,
            "execution_time_ms": round((time.monotonic() - started) * 1000),
            "artifacts": [
                p.name for p in run_dir.iterdir()
                if p.name != "spark.py" and p.is_file()
            ],
            "sandboxed": True,
            "timeout_seconds": timeout_seconds,
            "memory_mb": memory_mb,
            "working_directory": str(run_dir),
            "completed_at": _now_iso(),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "run_id": run_id,
            "status": "timeout",
            "stdout": (exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-20000:] if isinstance(exc.stderr, str) else "",
            "return_code": None,
            "execution_time_ms": round((time.monotonic() - started) * 1000),
            "artifacts": [],
            "sandboxed": True,
            "timeout_seconds": timeout_seconds,
            "memory_mb": memory_mb,
            "working_directory": str(run_dir),
            "completed_at": _now_iso(),
        }
    except Exception as exc:
        return {
            "run_id": run_id,
            "status": "error",
            "stdout": "",
            "stderr": str(exc),
            "return_code": None,
            "execution_time_ms": round((time.monotonic() - started) * 1000),
            "artifacts": [],
            "sandboxed": True,
            "timeout_seconds": timeout_seconds,
            "memory_mb": memory_mb,
            "working_directory": str(run_dir),
            "completed_at": _now_iso(),
        }


def _complete(
    invocation: Dict[str, Any],
    future: concurrent.futures.Future,
) -> None:
    try:
        result = future.result()
    except Exception as exc:
        result = {
            "run_id": invocation["run_id"],
            "status": "error",
            "stdout": "",
            "stderr": str(exc),
            "return_code": None,
            "execution_time_ms": None,
            "artifacts": [],
            "sandboxed": True,
            "completed_at": _now_iso(),
        }

    packet = {
        **invocation,
        "spark_result": _json_safe(result),
        "completed_at": _now_iso(),
        "awaiting_dex_judgment": True,
    }

    try:
        state = update_self_state({})
        pending = list(state.get("pending_spark_reaches", []))
        pending.append(packet)
        pending = pending[-10:]

        signals = list(state.get("pending_signals", []))
        signals.append({
            "signal_type": "SPARK_REACH_COMPLETED",
            "timestamp": _now_iso(),
            "run_id": invocation["run_id"],
            "intention": invocation.get("intention"),
            "status": result.get("status"),
        })
        signals = signals[-20:]

        update_self_state({
            "pending_spark_reaches": pending,
            "pending_signals": signals,
            "last_spark_reach": packet,
        })
    except Exception as exc:
        print(f"[SparkReach] completion state update failed: {exc}")

    # Best-effort cleanup of the source file. Artifacts are retained per run
    # when the spark deliberately creates them.
    try:
        source = SPARK_REACH_ROOT / invocation["run_id"] / "spark.py"
        source.unlink(missing_ok=True)
    except Exception:
        pass

    print(
        f"[SparkReach] completed run={invocation['run_id']} "
        f"status={result.get('status')} "
        f"origin={invocation.get('invocation_origin')}"
    )


def submit_spark_reach(
    *,
    intention: str,
    reach_objective: str,
    code: str,
    selected_context: Optional[list] = None,
    invocation_origin: str = "self_directed",
    initiated_by: str = "ambient_cognition",
    timeout_seconds: Optional[int] = None,
    memory_mb: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Queue a SparkReach without blocking the caller.

    The architecture records why the reach was chosen before execution.
    The result is deliberately returned later as an observation requiring
    Dex judgment before integration.
    """
    if not isinstance(code, str) or not code.strip():
        return {"status": "rejected", "reason": "empty_code"}

    encoded = code.encode("utf-8")
    if len(encoded) > SPARK_MAX_CODE_BYTES:
        return {
            "status": "rejected",
            "reason": "code_too_large",
            "max_code_bytes": SPARK_MAX_CODE_BYTES,
        }

    timeout = (
        SPARK_TIMEOUT_SECONDS
        if timeout_seconds is None
        else max(1, min(int(timeout_seconds), 30))
    )
    memory = (
        SPARK_MEMORY_MB
        if memory_mb is None
        else max(32, min(int(memory_mb), 512))
    )

    run_id = f"sr-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    invocation = {
        "run_id": run_id,
        "invocation_origin": invocation_origin,
        "initiated_by": initiated_by,
        "intention": str(intention or "").strip(),
        "reach_objective": str(reach_objective or "").strip(),
        "selected_context": list(selected_context or [])[:10],
        "submitted_at": _now_iso(),
        "status": "queued",
        "sandboxed": True,
        "timeout_seconds": timeout,
        "memory_mb": memory,
    }

    # Persist the causal origin before handing work to the background worker.
    state = update_self_state({})
    active = list(state.get("active_spark_reaches", []))
    active.append(invocation)
    active = active[-10:]
    update_self_state({
        "active_spark_reaches": active,
        "last_spark_reach": invocation,
    })

    future = _EXECUTOR.submit(_execute, run_id, code, timeout, memory)
    future.add_done_callback(lambda f: _complete(invocation, f))

    return {
        "status": "queued",
        "run_id": run_id,
        "invocation_origin": invocation_origin,
        "initiated_by": initiated_by,
        "intention": invocation["intention"],
        "reach_objective": invocation["reach_objective"],
        "selected_context": invocation["selected_context"],
        "timeout_seconds": timeout,
        "memory_mb": memory,
        "sandboxed": True,
        "awaiting_observation": True,
    }


def pending_spark_reaches(limit: int = 5) -> list:
    from self_state import load_self_state
    state = load_self_state()
    return list(state.get("pending_spark_reaches", []))[-max(1, min(limit, 10)):]
