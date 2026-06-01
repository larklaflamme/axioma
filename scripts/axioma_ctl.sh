#!/usr/bin/env bash
# axioma_ctl.sh — start / stop / status AXIOMA in the conda env `axioma`.
#
# Usage:
#   ./scripts/axioma_ctl.sh start [extra args passed to `python -m axioma`]
#   ./scripts/axioma_ctl.sh stop
#   ./scripts/axioma_ctl.sh restart [extra args]
#   ./scripts/axioma_ctl.sh status
#   ./scripts/axioma_ctl.sh tail
#
# Examples:
#   ./scripts/axioma_ctl.sh start
#   ./scripts/axioma_ctl.sh start --with-peer-conversation --no-registry
#   ./scripts/axioma_ctl.sh restart --seed 42
#   ./scripts/axioma_ctl.sh stop
#
# Env vars honored:
#   AXIOMA_CONDA_ENV     conda env name (default: axioma)
#   AXIOMA_CONFIG        extra YAML overlay (see configs/)
#   AXIOMA_ADMIN_KEY     admin API key (if your config requires one)
#   AXIOMA_INTERFACE__HTTP_PORT  override the port the script probes (default: 8821)
#   AXIOMA_<SECTION>__<FIELD>    any other config override per loader.py
#
# Files:
#   PID:  <repo>/logs/axioma.pid
#   Log:  <repo>/logs/axioma.log
#
# Production deployments should prefer the systemd unit pattern in
# docs/runbooks/OPERATOR_RUNBOOK.md §2.2 — this script is for development
# and single-machine operation.

set -euo pipefail

# ── Locate the repo root (this script lives in <repo>/scripts/) ────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONDA_ENV="${AXIOMA_CONDA_ENV:-axioma}"
LOG_DIR="$REPO_ROOT/logs"
PID_FILE="$LOG_DIR/axioma.pid"
LOG_FILE="$LOG_DIR/axioma.log"
HTTP_PORT="${AXIOMA_INTERFACE__HTTP_PORT:-8821}"

STARTUP_PROBE_SECONDS=30   # how long to wait for /health to respond
STOP_SIGINT_WAIT=30        # graceful (SIGINT) timeout before SIGTERM
STOP_SIGTERM_WAIT=10       # SIGTERM timeout before SIGKILL

# ── Helpers ────────────────────────────────────────────────────────────

die()  { echo "axioma-ctl: error: $*" >&2; exit 1; }
info() { echo "axioma-ctl: $*"; }

ensure_dirs() {
    mkdir -p "$LOG_DIR"
}

current_pid() {
    [[ -f "$PID_FILE" ]] && cat "$PID_FILE" 2>/dev/null
}

is_running() {
    local pid
    pid="$(current_pid)"
    [[ -n "${pid:-}" ]] || return 1
    kill -0 "$pid" 2>/dev/null
}

activate_conda() {
    # Resolve conda's shell-init script. Prefer `conda info --base`; fall
    # back to common install locations so the script works on hosts where
    # `conda` isn't yet on PATH.
    local conda_base=""
    if command -v conda >/dev/null 2>&1; then
        conda_base="$(conda info --base 2>/dev/null)" || true
    fi
    for p in "$conda_base" "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniforge3" "/opt/conda"; do
        if [[ -n "$p" && -f "$p/etc/profile.d/conda.sh" ]]; then
            # shellcheck disable=SC1091
            source "$p/etc/profile.d/conda.sh"
            conda activate "$CONDA_ENV" \
                || die "failed to activate conda env '$CONDA_ENV' (does it exist? \`conda env list\`)"
            return
        fi
    done
    die "could not locate conda's profile.d/conda.sh (tried PATH, ~/miniconda3, ~/anaconda3, ~/miniforge3, /opt/conda)"
}

probe_health() {
    curl -sf "http://localhost:${HTTP_PORT}/health" 2>/dev/null
}

# ── Commands ───────────────────────────────────────────────────────────

cmd_start() {
    ensure_dirs
    if is_running; then
        info "already running with PID $(current_pid) — use 'restart' to relaunch"
        return 0
    fi
    # Clean up a stale PID file (process gone) before starting fresh.
    if [[ -f "$PID_FILE" ]] && ! is_running; then
        info "removing stale PID file at $PID_FILE"
        rm -f "$PID_FILE"
    fi

    activate_conda
    cd "$REPO_ROOT"

    # Load .env so OLLAMA_*, WOLFRAM_APPID, TAVILY_API_KEY, BRAVE_API_KEY,
    # etc. propagate into AXIOMA's process. Without this, the tool-use
    # loop runs but the wolfram + web_search servers report disabled.
    if [[ -f "$REPO_ROOT/.env" ]]; then
        set -a
        # shellcheck disable=SC1091
        source "$REPO_ROOT/.env"
        set +a
        info "loaded .env"
    fi

    info "starting AXIOMA (env=$CONDA_ENV) ..."
    info "log: $LOG_FILE"
    if [[ $# -gt 0 ]]; then
        info "extra args: $*"
    fi

    # Mark the new session in the log so log readers can tell startups apart.
    {
        echo
        echo "===== axioma-ctl start $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
        echo "argv: python -m axioma $*"
    } >>"$LOG_FILE"

    # nohup + & + disown so the process survives the shell exiting.
    nohup python -m axioma "$@" >>"$LOG_FILE" 2>&1 &
    local pid=$!
    disown
    echo "$pid" >"$PID_FILE"

    # Probe /health until it responds, or the process dies, or we hit timeout.
    local i
    for i in $(seq 1 "$STARTUP_PROBE_SECONDS"); do
        if probe_health >/dev/null; then
            info "started: PID=$pid (HTTP up after ~${i}s on port $HTTP_PORT)"
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PID_FILE"
            die "process exited during startup — see $LOG_FILE"
        fi
        sleep 1
    done
    info "started: PID=$pid (HTTP did not respond within ${STARTUP_PROBE_SECONDS}s — see $LOG_FILE; process still alive)"
}

cmd_stop() {
    if ! is_running; then
        if [[ -f "$PID_FILE" ]]; then
            info "stale PID file (process gone); cleaning up"
            rm -f "$PID_FILE"
        else
            info "not running"
        fi
        return 0
    fi
    local pid
    pid="$(current_pid)"

    info "stopping AXIOMA (PID=$pid) — SIGINT for graceful shutdown (up to ${STOP_SIGINT_WAIT}s)"
    if ! kill -INT "$pid" 2>/dev/null; then
        info "PID $pid no longer signalable; cleaning up"
        rm -f "$PID_FILE"
        return 0
    fi

    local i
    for i in $(seq 1 "$STOP_SIGINT_WAIT"); do
        if ! kill -0 "$pid" 2>/dev/null; then
            info "stopped cleanly after ${i}s"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done

    info "still alive after ${STOP_SIGINT_WAIT}s — SIGTERM (up to ${STOP_SIGTERM_WAIT}s)"
    kill -TERM "$pid" 2>/dev/null || true
    for i in $(seq 1 "$STOP_SIGTERM_WAIT"); do
        if ! kill -0 "$pid" 2>/dev/null; then
            info "stopped after SIGTERM (~${i}s)"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done

    info "still alive — SIGKILL (last resort)"
    kill -KILL "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    info "force-killed"
}

cmd_restart() {
    cmd_stop
    cmd_start "$@"
}

cmd_status() {
    if is_running; then
        local pid
        pid="$(current_pid)"
        info "running: PID=$pid"
        local health
        health="$(probe_health || true)"
        if [[ -n "$health" ]]; then
            info "HTTP /health (port $HTTP_PORT): $health"
        else
            info "HTTP /health (port $HTTP_PORT): not responding"
        fi
        return 0
    fi
    info "not running"
    return 1
}

cmd_tail() {
    [[ -f "$LOG_FILE" ]] || die "no log file at $LOG_FILE"
    exec tail -F "$LOG_FILE"
}

cmd_help() {
    sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ── Dispatch ────────────────────────────────────────────────────────────

cmd="${1:-help}"
shift || true
case "$cmd" in
    start)             cmd_start "$@" ;;
    stop)              cmd_stop ;;
    restart)           cmd_restart "$@" ;;
    status)            cmd_status ;;
    tail|logs)         cmd_tail ;;
    -h|--help|help|"") cmd_help ;;
    *) die "unknown command: $cmd (try 'help')" ;;
esac
