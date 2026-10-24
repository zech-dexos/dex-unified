#!/usr/bin/env bash
# Local-first DexOS supervisor. Run: bash ./run_dex_local.sh start
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${DEX_PYTHON:-$ROOT/venv/bin/python}"
HOST="${DEX_HOST:-127.0.0.1}"
PORT="${DEX_PORT:-8765}"
RUNTIME_DIR="${DEX_RUNTIME_DIR:-$HOME/.local/state/dex-unified}"
PID_DIR="$RUNTIME_DIR/pids"
LOG_DIR="$RUNTIME_DIR/logs"
API_PID="$PID_DIR/api.pid"
AMBIENT_PID="$PID_DIR/ambient.pid"
API_LOG="$LOG_DIR/api.log"
AMBIENT_LOG="$LOG_DIR/ambient.log"
mkdir -p "$PID_DIR" "$LOG_DIR" "$RUNTIME_DIR/state-backups"

STATE_FILES=(identity.json self_model.json experiences.jsonl dex_lineage.jsonl participant_state.json current_session.json sigils.json open_loops.json reflections.jsonl pulse.jsonl narrative.jsonl intents.json counterfactual_archive.jsonl amendments.jsonl memory_seeds.jsonl)
say() { printf '[DexOS] %s\n' "$*"; }

alive() {
  [[ -f "$1" ]] || return 1
  local p
  p="$(cat "$1" 2>/dev/null || true)"
  [[ "$p" =~ ^[0-9]+$ ]] && kill -0 "$p" 2>/dev/null
}
stop_one() {
  local f="$1" label="$2" p
  if alive "$f"; then
    p="$(cat "$f")"; say "Stopping $label (PID $p)"
    kill "$p" 2>/dev/null || true
    for _ in {1..15}; do kill -0 "$p" 2>/dev/null || break; sleep 1; done
    kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null || true
  fi
  rm -f "$f"
}

sync_code() {
  git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { say "Not a Git checkout: $ROOT"; return 1; }
  git -C "$ROOT" diff --cached --quiet || { say "Update refused: staged changes exist."; return 1; }

  local path allowed
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    allowed=0
    for f in "${STATE_FILES[@]}"; do [[ "$path" == "$f" ]] && allowed=1; done
    [[ "$allowed" -eq 1 ]] || { say "Update refused to protect local code edit: $path"; return 1; }
  done < <(git -C "$ROOT" diff --name-only)

  local upstream
  upstream="$(git -C "$ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  [[ -n "$upstream" ]] || { say "No Git upstream configured for current branch."; return 1; }

  local backup_dir
  backup_dir="$RUNTIME_DIR/state-backups/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup_dir"
  for f in "${STATE_FILES[@]}"; do
    if [[ -e "$ROOT/$f" ]]; then cp -a "$ROOT/$f" "$backup_dir/$f"; touch "$backup_dir/.present.$f"; fi
    if git -C "$ROOT" ls-files --error-unmatch "$f" >/dev/null 2>&1; then
      git -C "$ROOT" checkout -- "$f"
    else
      rm -f "$ROOT/$f"
    fi
  done

  say "Fetching latest code; preserving local identity and continuity records."
  local ok=0
  if git -C "$ROOT" fetch --prune origin && git -C "$ROOT" merge --ff-only "$upstream"; then ok=1; else say "Fast-forward update failed."; fi
  for f in "${STATE_FILES[@]}"; do
    [[ -f "$backup_dir/.present.$f" ]] && cp -a "$backup_dir/$f" "$ROOT/$f"
  done
  [[ "$ok" -eq 1 ]] || { say "Update failed safely; continuity records restored."; return 1; }
  say "Code now at $(git -C "$ROOT" rev-parse --short HEAD); local state restored."
}

find_model() {
  local requested="$1" kind="$2" found=""
  [[ -n "$requested" && -f "$requested" ]] && { printf '%s\n' "$requested"; return 0; }
  local roots=()
  [[ -d "$HOME/dev/llm/models" ]] && roots+=("$HOME/dev/llm/models")
  [[ -d "$ROOT/models" ]] && roots+=("$ROOT/models")
  [[ -d "$HOME/dev/haven/dex-unified-self-model-integration/models" ]] && roots+=("$HOME/dev/haven/dex-unified-self-model-integration/models")
  [[ -d "$HOME/dev/haven/dex-unified-self-model-integration" ]] && roots+=("$HOME/dev/haven/dex-unified-self-model-integration")
  [[ -d "$HOME/dev/haven" ]] && roots+=("$HOME/dev/haven")
  [[ -d "$ROOT" ]] && roots+=("$ROOT")
  [[ -d "$HOME/models" ]] && roots+=("$HOME/models")
  [[ -d /app/models ]] && roots+=(/app/models)
  [[ ${#roots[@]} -gt 0 ]] || return 1
  if [[ "$kind" == "chat" ]]; then
    found="$(find "${roots[@]}" -type d \( -name .git -o -name venv -o -name .venv -o -name node_modules \) -prune -o -type f -path '*heretic*' -iname '*.gguf' -print -quit 2>/dev/null || true)"
    [[ -n "$found" ]] || found="$(find "${roots[@]}" -type d \( -name .git -o -name venv -o -name .venv -o -name node_modules \) -prune -o -type f -iname '*heretic*.gguf' -print -quit 2>/dev/null || true)"
  else
    found="$(find "${roots[@]}" -type d \( -name .git -o -name venv -o -name .venv -o -name node_modules \) -prune -o -type f -iname 'qwen2.5-0.5b-instruct-q4_k_m.gguf' -print -quit 2>/dev/null || true)"
    [[ -n "$found" ]] || found="$(find "${roots[@]}" -type d \( -name .git -o -name venv -o -name .venv -o -name node_modules \) -prune -o -type f -iname '*qwen*0.5b*.gguf' -print -quit 2>/dev/null || true)"
  fi
  [[ -n "$found" ]] || return 1
  printf '%s\n' "$found"
}

resolve_models() {
  CHAT_MODEL="$(find_model "${LOCAL_CHAT_MODEL_PATH:-${DEX_CHAT_MODEL_PATH:-$HOME/dev/llm/models/llama-3.2-3b-heretic/model_q4_k_m.gguf}}" chat || true)"
  AMBIENT_MODEL="$(find_model "${LOCAL_SLM_PATH:-/app/models/qwen2.5-0.5b-instruct-q4_k_m.gguf}" ambient || true)"
  [[ -n "$CHAT_MODEL" ]] || { say "Heretic GGUF missing. Set LOCAL_CHAT_MODEL_PATH to its real path."; return 1; }
  [[ -n "$AMBIENT_MODEL" ]] || { say "Ambient Qwen 0.5B GGUF missing. Set LOCAL_SLM_PATH to its real path. No substitute model will be silently loaded."; return 1; }
  say "Chat GGUF: $CHAT_MODEL"
  say "Ambient GGUF: $AMBIENT_MODEL"
}

check_dependencies() {
  [[ -x "$PYTHON" ]] || { say "Project venv Python missing: $PYTHON"; return 1; }
  if ! "$PYTHON" -c 'import fastapi, uvicorn, llama_cpp, gtts, firebase_admin, stripe' >/dev/null 2>&1; then
    say "Installing missing project dependencies into the existing venv."
    "$PYTHON" -m pip install -r "$ROOT/requirements.txt"
  fi
  "$PYTHON" -c 'import fastapi, uvicorn, llama_cpp, gtts, firebase_admin, stripe'
}

start_runtime() {
  sync_code
  check_dependencies
  resolve_models
  if alive "$API_PID" || alive "$AMBIENT_PID"; then
    say "A process is already running. Use restart to replace both."; return 1
  fi
  if curl -fsS --max-time 2 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    say "Port $PORT is already serving an API not managed by this launcher. Choose DEX_PORT or stop it."
    return 1
  fi
  : > "$API_LOG"; : > "$AMBIENT_LOG"; rm -f "$RUNTIME_DIR/ambient.loaded"

  say "Starting API; it preloads the interactive GGUF before serving chat."
  (
    cd "$ROOT"
    nohup env -u GITHUB_TOKEN -u LOCAL_CHAT_BASE_URL DEX_LOCAL_RUNTIME=1 DEXOS_STATE_DIR="$ROOT" DEX_AMBIENT_STATUS_FILE="$RUNTIME_DIR/ambient.loaded" LOCAL_CHAT_MODEL_PATH="$CHAT_MODEL" DEX_CHAT_MODEL_PATH="$CHAT_MODEL" LOCAL_SLM_PATH="$AMBIENT_MODEL" "$PYTHON" -m uvicorn api:app --host "$HOST" --port "$PORT" >>"$API_LOG" 2>&1 < /dev/null &
    echo "$!" > "$API_PID"
  )
  say "Starting independent ambient process; it preloads the pulse GGUF before its loop."
  (
    cd "$ROOT"
    nohup env -u GITHUB_TOKEN -u LOCAL_CHAT_BASE_URL DEX_LOCAL_RUNTIME=1 DEXOS_STATE_DIR="$ROOT" DEX_AMBIENT_STATUS_FILE="$RUNTIME_DIR/ambient.loaded" LOCAL_CHAT_MODEL_PATH="$CHAT_MODEL" DEX_CHAT_MODEL_PATH="$CHAT_MODEL" LOCAL_SLM_PATH="$AMBIENT_MODEL" "$PYTHON" "$ROOT/dex_local_ambient.py" >>"$AMBIENT_LOG" 2>&1 < /dev/null &
    echo "$!" > "$AMBIENT_PID"
  )

  local api_ready=0 body
  for _ in {1..240}; do
    if ! alive "$API_PID"; then say "API exited; log follows:"; tail -80 "$API_LOG"; stop_one "$AMBIENT_PID" ambient; return 1; fi
    if ! alive "$AMBIENT_PID"; then say "Ambient process exited; log follows:"; tail -80 "$AMBIENT_LOG"; stop_one "$API_PID" API; return 1; fi
    if body="$(curl -fsS --max-time 2 "http://$HOST:$PORT/health" 2>/dev/null)"; then
      if printf '%s' "$body" | "$PYTHON" -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("local_runtime") and d.get("models",{}).get("chat",{}).get("loaded") else 1)' 2>/dev/null; then api_ready=1; fi
    fi
    if [[ "$api_ready" -eq 1 && -f "$RUNTIME_DIR/ambient.loaded" ]]; then break; fi
    sleep 1
  done
  if [[ "$api_ready" -ne 1 ]] || [[ ! -f "$RUNTIME_DIR/ambient.loaded" ]]; then
    say "Startup timed out before both models were confirmed loaded."
    say "===== API LOG ====="; tail -80 "$API_LOG"
    say "===== AMBIENT LOG ====="; tail -80 "$AMBIENT_LOG"
    stop_one "$AMBIENT_PID" ambient; stop_one "$API_PID" API; return 1
  fi
  say "DEX LOCAL RUNTIME READY — chat GGUF loaded, ambient GGUF loaded, pulse loop running."
  say "API: http://$HOST:$PORT"
  say "Logs: $API_LOG and $AMBIENT_LOG"
}

status_runtime() {
  say "Repo: $ROOT"
  say "Branch/commit: $(git -C "$ROOT" branch --show-current 2>/dev/null || echo unknown) / $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if alive "$API_PID"; then say "API process running (PID $(cat "$API_PID"))"; else say "API process stopped"; fi
  if alive "$AMBIENT_PID"; then say "Ambient process running (PID $(cat "$AMBIENT_PID"))"; else say "Ambient process stopped"; fi
  curl -fsS --max-time 3 "http://$HOST:$PORT/health" 2>/dev/null || true
  printf '\n'
  [[ -f "$AMBIENT_LOG" ]] && grep -E 'Ambient Runtime|llama.cpp|Ambient Daemon' "$AMBIENT_LOG" | tail -8 || true
}

case "${1:-start}" in
  start) start_runtime ;;
  stop) stop_one "$AMBIENT_PID" ambient; stop_one "$API_PID" API; say "Stopped." ;;
  restart) stop_one "$AMBIENT_PID" ambient; stop_one "$API_PID" API; start_runtime ;;
  status) status_runtime ;;
  logs) touch "$API_LOG" "$AMBIENT_LOG"; tail -n 80 -F "$API_LOG" "$AMBIENT_LOG" ;;
  update) sync_code ;;
  *) echo "Usage: bash $0 {start|stop|restart|status|logs|update}" >&2; exit 2 ;;
esac
