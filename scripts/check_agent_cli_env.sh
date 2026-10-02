#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/scripts/.env"

load_env_file() {
  local line key value
  [[ -f "$ENV_FILE" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "${line:0:1}" == "#" || "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    [[ -z "$key" || -z "$value" ]] && continue
    if [[ -z "${!key:-}" ]]; then
      export "$key=$value"
    fi
  done < "$ENV_FILE"
}

detect_python_bin() {
  local candidate fallback_candidate=""

  python_has_agent_sdk() {
    "$1" -c 'import claude_agent_sdk' >/dev/null 2>&1
  }

  if [[ -n "${PYTHON_BIN:-}" ]]; then
    candidate="$PYTHON_BIN"
    if [[ "$candidate" != /* ]]; then
      candidate="$ROOT_DIR/$candidate"
    fi
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    echo "Ignoring stale PYTHON_BIN (not executable): $PYTHON_BIN" >&2
  fi
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    candidate="$VIRTUAL_ENV/bin/python"
    if [[ -x "$candidate" ]]; then
      fallback_candidate="$candidate"
      if python_has_agent_sdk "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  fi
  for candidate in \
    "$ROOT_DIR/.venv/bin/python" \
    "$ROOT_DIR/venv/bin/python" \
    "$ROOT_DIR/env/bin/python" \
    "$ROOT_DIR/upgrade/bin/python"; do
    if [[ -x "$candidate" ]]; then
      [[ -n "$fallback_candidate" ]] || fallback_candidate="$candidate"
      if python_has_agent_sdk "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  while IFS= read -r candidate; do
    candidate="${candidate%/pyvenv.cfg}/bin/python"
    if [[ -x "$candidate" ]]; then
      [[ -n "$fallback_candidate" ]] || fallback_candidate="$candidate"
      if python_has_agent_sdk "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done < <(
    find "$ROOT_DIR" -mindepth 1 -maxdepth 4 \
      \( -path '*/.git' -o -path '*/node_modules' -o -path '*/workspace_jobs' \
         -o -path '*/workspace_multi' -o -path '*/simulation_runs' \) -prune \
      -o -name pyvenv.cfg -type f -print 2>/dev/null | sort
  )
  for candidate in "$(command -v python3 2>/dev/null || true)" "$(command -v python 2>/dev/null || true)"; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    [[ -n "$fallback_candidate" ]] || fallback_candidate="$candidate"
    if python_has_agent_sdk "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  if [[ -n "$fallback_candidate" ]]; then
    printf '%s\n' "$fallback_candidate"
    return 0
  fi
  echo "No Python interpreter found. Set PYTHON_BIN=/path/to/venv/bin/python and retry." >&2
  return 1
}

load_env_file
export ROOT_DIR
if [[ -z "${SUPPLY_CHAIN_PROJECT_ROOT:-}" ]]; then
  export SUPPLY_CHAIN_PROJECT_ROOT="$ROOT_DIR"
elif [[ "$SUPPLY_CHAIN_PROJECT_ROOT" != /* ]]; then
  export SUPPLY_CHAIN_PROJECT_ROOT="$ROOT_DIR/$SUPPLY_CHAIN_PROJECT_ROOT"
fi
if [[ ! -d "$SUPPLY_CHAIN_PROJECT_ROOT" ]]; then
  export SUPPLY_CHAIN_PROJECT_ROOT="$ROOT_DIR"
fi
if [[ -z "${SUPPLY_CHAIN_AGENT_ROOT:-}" ]]; then
  export SUPPLY_CHAIN_AGENT_ROOT="$SUPPLY_CHAIN_PROJECT_ROOT/agent"
elif [[ "$SUPPLY_CHAIN_AGENT_ROOT" != /* ]]; then
  export SUPPLY_CHAIN_AGENT_ROOT="$SUPPLY_CHAIN_PROJECT_ROOT/$SUPPLY_CHAIN_AGENT_ROOT"
fi
if [[ ! -d "$SUPPLY_CHAIN_AGENT_ROOT" ]]; then
  export SUPPLY_CHAIN_AGENT_ROOT="$SUPPLY_CHAIN_PROJECT_ROOT/agent"
fi
PYTHON_BIN="$(detect_python_bin)"

echo "Project root: $ROOT_DIR"
echo "Runtime env file: $ENV_FILE"
echo "Python: $PYTHON_BIN"
"$PYTHON_BIN" --version

echo
echo "Agent environment:"
printf '  ANTHROPIC_BASE_URL=%s\n' "${ANTHROPIC_BASE_URL:-<unset>}"
printf '  ANTHROPIC_MODEL=%s\n' "${ANTHROPIC_MODEL:-<unset>}"
if [[ -n "${ANTHROPIC_AUTH_TOKEN:-${ANTHROPIC_API_KEY:-}}" ]]; then
  echo "  auth token/API key: <set>"
else
  echo "  auth token/API key: <unset>"
fi
printf '  NO_PROXY=%s\n' "${NO_PROXY:-${no_proxy:-<unset>}}"

if [[ -f "$ENV_FILE" ]]; then
  echo
  echo "Runtime env file Agent values:"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "${line:0:1}" == "#" || "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    case "$key" in
      ANTHROPIC_BASE_URL|AGENT_GATEWAY_BASE_URL|ANTHROPIC_MODEL|ANTHROPIC_MODEL_LIST|NO_PROXY|no_proxy)
        printf '  %s=%s\n' "$key" "$value"
        ;;
      ANTHROPIC_AUTH_TOKEN|ANTHROPIC_API_KEY)
        if [[ -n "$value" ]]; then
          printf '  %s=<set>\n' "$key"
        else
          printf '  %s=<unset>\n' "$key"
        fi
        ;;
    esac
  done < "$ENV_FILE"
fi

echo
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, os.environ.get("ROOT_DIR", ""))

try:
    from config.environment_config import EnvironmentConfig
except Exception as exc:
    print(f"environment config import failed: {exc}")
else:
    missing = EnvironmentConfig.missing_agent_env_keys()
    if missing:
        print(f"missing Agent Environment config: {', '.join(missing)}")
    else:
        print("Agent Environment config: complete")
    print(f"resolved default model: {EnvironmentConfig.DEFAULT_AGENT_MODEL or '<unset>'}")
    print(f"resolved model list: {EnvironmentConfig.DEFAULT_AGENT_MODEL_LIST}")
    agent_base = EnvironmentConfig.LOCAL_AGENT_GATEWAY_BASE_URL
    simulation_base = EnvironmentConfig.SIMULATION_API_BASE_URL
    if agent_base and simulation_base and agent_base.rstrip("/") == simulation_base.rstrip("/"):
        print("WARNING: ANTHROPIC_BASE_URL equals SIMULATION_API_BASE_URL; Agent calls will hit the simulation backend.")
    if agent_base in {"http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:3000", "http://localhost:3000"}:
        print("WARNING: ANTHROPIC_BASE_URL points to a common local project port, not the model gateway.")

try:
    import claude_agent_sdk
except Exception as exc:
    print(f"claude_agent_sdk import failed: {exc}")
    raise SystemExit(1)

sdk_root = Path(claude_agent_sdk.__file__).resolve().parent
candidate = sdk_root / "_bundled" / "claude"
print(f"claude_agent_sdk: {claude_agent_sdk.__file__}")
print(f"bundled claude: {candidate}")
print(f"bundled claude exists/executable: {candidate.exists()} / {os.access(candidate, os.X_OK)}")
if candidate.exists():
    result = subprocess.run(
        [str(candidate), "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    print(f"claude --version exit={result.returncode}")
    if result.stdout:
        print("stdout:")
        print(result.stdout.strip())
    if result.stderr:
        print("stderr:")
        print(result.stderr.strip())
PY

echo
echo "Claude stderr log path used by runtime:"
echo "  $ROOT_DIR/agent/logs/claude_stderr_$(date +%Y%m%d).log"
