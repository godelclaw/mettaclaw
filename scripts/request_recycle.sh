#!/usr/bin/env bash
# Ask a running Pettaclaw process to exit at its next completed turn boundary.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
STATE_HOME="${XDG_STATE_HOME:-${HOME:-}/.local/state}"
INSTANCE="${METTACLAW_INSTANCE:-$(basename "$ROOT")}"
FLAG="${METTACLAW_RECYCLE_REQUEST_PATH:-$STATE_HOME/$INSTANCE/recycle.requested}"
WAIT_SECONDS="${METTACLAW_RECYCLE_WAIT_SECONDS:-600}"

mkdir -p "$(dirname "$FLAG")"
tmp="${FLAG}.tmp.$$"
printf 'requested_at=%s requester_pid=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$$" >"$tmp"
chmod 660 "$tmp"
mv -f "$tmp" "$FLAG"

deadline=$((SECONDS + WAIT_SECONDS))
while [ -e "$FLAG" ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "recycle request was not acknowledged within ${WAIT_SECONDS}s" >&2
        exit 1
    fi
    sleep 1
done
