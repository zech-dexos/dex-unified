#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON="${PYTHON:-python3}"
VENV="$ROOT_DIR/.venv"
MODEL_DIR="$ROOT_DIR/models"
API_LOG="$ROOT_DIR/.dex-local-api.log"
PORT="${PORT:-8765}"

export PORT
export DEX_ENABLE_GITHUB_PERSISTENCE=0
export LOCAL_SLM_PATH="${LOCAL_SLM_PATH:-$MODEL_DIR/qwen2.5-0.5b-instruct-q4_k_m.gguf}"
export LOCAL_CHAT_MODEL_PATH="${LOCAL_CHAT_MODEL_PATH:-$MODEL_DIR/heretic/model_q4_k_m.gguf}"
export LOCAL_CHAT_N_CTX="${LOCAL_CHAT_N_CTX:-3072}"
export LOCAL_CHAT_THREADS="${LOCAL_CHAT_THREADS:-2}"
export PYTHONUNBUFFERED=1

# Install only missing WSL prerequisites needed to build llama-cpp-python and run the launcher.
missing_packages=()
command -v curl >/dev/null 2>&1 || missing_packages+=(curl)
command -v gcc >/dev/null 2>&1 || missing_packages+=(build-essential)
command -v cmake >/dev/null 2>&1 || missing_packages+=(cmake)
command -v ss >/dev/null 2>&1 || missing_packages+=(iproute2)
if [[ ! -x "$VENV/bin/python" ]]; then
  missing_packages+=(python3-venv)
fi
if (( ${#missing_packages[@]} )); then
  echo "[Dex local] Installing required WSL packages: ${missing_packages[*]}"
  if [[ "$(id -u)" == "0" ]]; then
    apt-get update && apt-get install -y "${missing_packages[@]}"
  elif command -v sudo >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y "${missing_packages[@]}"
  else
    echo "Cannot install prerequisites automatically. Install: ${missing_packages[*]}"
    exit 1
  fi
fi
command -v sha256sum >/dev/null 2>&1 || { echo "Missing sha256sum utility."; exit 1; }

if [[ -n "$(ss -ltn 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$" {print $4}')" ]]; then
  echo "[Dex local] Port $PORT is already in use."
  echo "Stop the existing process on port $PORT, or rerun with PORT=8766 bash run_dex_local.sh"
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "[Dex local] Creating isolated Python environment..."
  "$PYTHON" -m venv "$VENV" || {
    echo "Python venv support is missing. Install it with: sudo apt-get install python3-venv"
    exit 1
  }
fi

if [[ ! -f "$VENV/.dex-requirements-installed" || "$ROOT_DIR/requirements.txt" -nt "$VENV/.dex-requirements-installed" ]]; then
  echo "[Dex local] Installing runtime dependencies..."
  "$VENV/bin/python" -m pip install --upgrade pip wheel
  "$VENV/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"
  touch "$VENV/.dex-requirements-installed"
fi

download_model() {
  local url="$1" destination="$2" expected_sha="$3"
  mkdir -p "$(dirname "$destination")"
  if [[ -s "$destination" ]]; then
    if [[ "$expected_sha" == "none" ]] || echo "$expected_sha  $destination" | sha256sum -c --status; then
      echo "[Dex local] Model ready: $destination"
      return
    fi
    echo "[Dex local] Existing model checksum is wrong; replacing: $destination"
    rm -f "$destination"
  fi
  local temp="${destination}.download"
  echo "[Dex local] Downloading/resuming $(basename "$destination") (large first-run download)..."
  local -a resume_args=()
  if [[ -s "$temp" ]]; then
    resume_args=(--continue-at -)
  fi
  curl --fail --location "${resume_args[@]}" --retry 3 --connect-timeout 20 --output "$temp" "$url"
  if [[ "$expected_sha" != "none" ]]; then
    if ! echo "$expected_sha  $temp" | sha256sum -c -; then
      rm -f "$temp"
      echo "[Dex local] Model checksum failed; removed the incomplete download. Rerun to download it again."
      exit 1
    fi
  fi
  mv "$temp" "$destination"
  echo "[Dex local] Download complete: $destination"
}

download_model \
  "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
  "$LOCAL_SLM_PATH" "none"

download_model \
  "https://huggingface.co/tinyopsec/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored-GGUF/resolve/main/model_q4_k_m.gguf" \
  "$LOCAL_CHAT_MODEL_PATH" "0c90de6859205a9df55663b42dba96e1bbb8157cf41234ce462afd414c68f956"

echo "[Dex local] Starting DexOS API on http://127.0.0.1:$PORT ..."
"$VENV/bin/uvicorn" api:app --host 127.0.0.1 --port "$PORT" >"$API_LOG" 2>&1 &
API_PID=$!
cleanup() {
  kill "$API_PID" 2>/dev/null || true
  wait "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ready=0
for _ in $(seq 1 90); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "[Dex local] API stopped during startup. Last log output:"
    tail -n 100 "$API_LOG" || true
    exit 1
  fi
  if curl --silent --fail "http://127.0.0.1:$PORT/health" >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" != "1" ]]; then
  echo "[Dex local] API did not become ready. Last log output:"
  tail -n 100 "$API_LOG" || true
  exit 1
fi

echo "[Dex local] API is ready. Local continuity is authoritative; GitHub state sync is OFF."
echo "[Dex local] Starting Root ↔ Dex conversation. Type 'exit' to stop."
"$VENV/bin/python" "$ROOT_DIR/dex_chat.py"
