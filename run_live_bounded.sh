#!/usr/bin/env bash
# run_live_bounded.sh — guarded bounded LIVE Telegram run for Cettaclaw-Lila.
#
# Runs a bounded live entrypoint (default run_live_bounded.metta) on the CeTTa
# interfaces binary at CETTA_ROOT, from this repo root, with live-send approval
# set, after confirming no Pettaclaw-Lila agent is active against the same bot and
# that the run lock is free. Stdout/stderr go to a timestamped log under ~/archive.
#
# Usage: ./run_live_bounded.sh [entrypoint.metta]
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
CETTA_ROOT="${CETTA_ROOT:-${HOME:-}/repos/cetta-interfaces}"
CETTA="$CETTA_ROOT/cetta"

TARGET="${1:-run_live_bounded.metta}"
if [ ! -f "$TARGET" ]; then
    echo "REFUSING: entrypoint '$TARGET' not found in $ROOT" >&2
    exit 1
fi

# The live state: the canonical cettaclaw config (offset/history/prompt are its
# real files). Callers may override these for scratch dry-runs.
export CETTACLAW_SETTINGS="${CETTACLAW_SETTINGS:-$ROOT/.env}"
export CETTACLAW_SECRETS="${CETTACLAW_SECRETS:-$ROOT/config/secrets.env}"
for f in "$CETTACLAW_SETTINGS" "$CETTACLAW_SECRETS"; do
    [ -f "$f" ] || { echo "REFUSING: missing config file $f" >&2; exit 1; }
done

export CETTACLAW_RUN_ID="${CETTACLAW_RUN_ID:-$$-$(date +%Y%m%d-%H%M%S)-$RANDOM}"
export CETTACLAW_REPO_ROOT="${CETTACLAW_REPO_ROOT:-$ROOT}"
# Non-secret runtime defaults for the child + skills.
export METTACLAW_MEMORY_ENDPOINT="${METTACLAW_MEMORY_ENDPOINT:-http://127.0.0.1:8877}"
export METTACLAW_MCP_BRIDGE_CLI="${METTACLAW_MCP_BRIDGE_CLI:-$ROOT/scripts/mcp_bridge_cli.py}"

# Build / verify the CeTTa interfaces binary (BUILD=core).
if [ ! -x "$CETTA" ] || ! "$CETTA" -v 2>/dev/null | grep -q '(core)'; then
    if [ -f "$CETTA_ROOT/Makefile" ]; then
        echo "building $CETTA [BUILD=core]"; make -C "$CETTA_ROOT" BUILD=core -j2
    fi
fi
if ! "$CETTA" -v 2>/dev/null | grep -q '(core)'; then
    echo "REFUSING: $CETTA is not a BUILD=core binary" >&2; exit 1
fi

# Never run both Lila implementations against the same bot or offset.
for svc in pettaclaw-lila; do
    state="$(systemctl --user is-active "$svc" 2>/dev/null || true)"
    case "$state" in
        active|activating|reloading)
            echo "REFUSING: user service '$svc' is $state — stop it first." >&2; exit 1 ;;
    esac
done
if legacy="$(pgrep -af 'pettaclaw-lila/run')"; then
    echo "REFUSING: a Pettaclaw-Lila process is running:" >&2; echo "$legacy" >&2; exit 1
fi

# Address-space cap: large embedding JSON must be handled by the runtime/json
# interfaces, not by widening the stack.
ulimit -v 8388608

# Run-lock pre-check (the loop itself acquires/releases it too).
lock="$HOME/.config/cettaclaw/run.lock"
lock_line="$(grep -E '^export CETTACLAW_RUN_LOCK_PATH=' "$CETTACLAW_SETTINGS" 2>/dev/null || true)"
if [ -n "$lock_line" ]; then
    lock="${lock_line#export CETTACLAW_RUN_LOCK_PATH=}"; lock="${lock#\'}"; lock="${lock%\'}"; lock="${lock#\"}"; lock="${lock%\"}"
fi
if [ -f "$lock" ]; then
    # The lock records its owner: run_id=<launcher-pid>-<date>-<rand>. Existence
    # alone is not ownership — a chunk killed uncleanly (OOM, SIGKILL) leaves its
    # lock behind and would otherwise wedge every future start. Stale (owner dead,
    # or pid reused by a non-cettaclaw process) => take over; live owner => refuse.
    lock_pid="$(sed -nE 's/.*run_id=([0-9]+)-.*/\1/p' "$lock" | head -1)"
    if [ -n "$lock_pid" ] && [ -d "/proc/$lock_pid" ] \
       && tr '\0' ' ' <"/proc/$lock_pid/cmdline" 2>/dev/null | grep -qE 'run_live|cettaclaw|cetta'; then
        echo "REFUSING: run lock held by live cettaclaw pid $lock_pid: $lock" >&2; exit 1
    fi
    echo "NOTE: removing stale run lock (owner ${lock_pid:-unknown} is not a live cettaclaw run): $lock" >&2
    rm -f "$lock"
fi

if [ "${CETTACLAW_PRECHECK_ONLY:-}" = "1" ]; then
    echo "cettaclaw bounded live launcher precheck passed; live loop not started"; exit 0
fi

# Optional readiness gate (skipped when the script is not present in this repo).
if [ "${CETTACLAW_SKIP_READINESS:-}" != "1" ] && [ -x ./scripts/cettaclaw_readiness_check.sh ]; then
    CETTACLAW_READINESS_IGNORE_PIDS="${CETTACLAW_READINESS_IGNORE_PIDS:-} $$" ./scripts/cettaclaw_readiness_check.sh
fi

cleanup_lock() {
    # Unconditional on exit status: the loop normally releases its own lock, so
    # any still-present lock owned by this run is crash residue — remove it.
    if [ -f "$lock" ] && grep -Fq "run_id=$CETTACLAW_RUN_ID" "$lock"; then
        rm -f "$lock"
    fi
}
trap cleanup_lock EXIT INT TERM

mkdir -p "$HOME/archive"
log="$HOME/archive/cettaclaw-live-bounded-$(date +%Y%m%d-%H%M%S).log"
echo "cettaclaw bounded live run starting (entrypoint: $TARGET); log: $log"

status=0
CETTACLAW_LIVE_SEND_APPROVED=YES_SEND_LIVE_TELEGRAM \
    "$CETTA" --lang he --profile he-extended "$TARGET" >"$log" 2>&1 || status=$?

case "$status" in
    130|143) echo "cettaclaw bounded live run received stop signal; clean operator stop"; status=0 ;;
esac

echo "cettaclaw bounded live run finished with status $status; log: $log"
grep -q 'RunLockBusy' "$log" 2>/dev/null && echo "NOTE: run-lock was busy — no iterations ran (see log)." >&2 || true
exit "$status"
