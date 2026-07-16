#!/usr/bin/env bash
# run.sh — launch a cettaclaw-godel entrypoint on the CeTTa interfaces binary.
#
# The interpreter and its native interfaces live OUTSIDE this repo, in CeTTa
# proper: point CETTA_ROOT at a BUILD=core CeTTa checkout (its dir supplies the
# native lib/ interfaces imported by the focused adapters). Settings and secrets live
# outside the repo too and are never committed.
#
#   ./run.sh                 # start the agent loop (run.metta)
#   ./run.sh smoketest.metta # import-only check; does NOT start the loop
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
CETTA_ROOT="${CETTA_ROOT:-${HOME:-}/repos/cetta-interfaces}"
CETTA="$CETTA_ROOT/cetta"

# Settings + secrets (KEY=VALUE .env files) — outside the repo, never committed.
export CETTACLAW_SETTINGS="${CETTACLAW_SETTINGS:-$HOME/.config/cettaclaw/settings.env}"
export CETTACLAW_SECRETS="${CETTACLAW_SECRETS:-$HOME/.config/cettaclaw/secrets.env}"
for f in "$CETTACLAW_SETTINGS" "$CETTACLAW_SECRETS"; do
    [ -f "$f" ] || echo "warning: config file not found: $f" >&2
done

# Build / verify the CeTTa interfaces binary (BUILD=core; HTTP ships in core).
if [ ! -x "$CETTA" ] || ! "$CETTA" -v 2>/dev/null | grep -q '(core)'; then
    if [ -f "$CETTA_ROOT/Makefile" ]; then
        echo "building $CETTA [BUILD=core]"
        make -C "$CETTA_ROOT" BUILD=core -j2
    fi
fi
if [ ! -x "$CETTA" ]; then
    echo "REFUSING: no cetta binary at $CETTA (set CETTA_ROOT to a CeTTa checkout)" >&2
    exit 1
fi

# Non-secret runtime defaults: memory-shim endpoint + the repository's MCP
# bridge CLI (so MCP resolves regardless of launch CWD).
export METTACLAW_MEMORY_ENDPOINT="${METTACLAW_MEMORY_ENDPOINT:-http://127.0.0.1:8877}"
export METTACLAW_MCP_BRIDGE_CLI="${METTACLAW_MCP_BRIDGE_CLI:-$ROOT/scripts/mcp_bridge_cli.py}"

# Local imports (./src and ./lib_cettaclaw) resolve relative to CWD, so
# always launch from the repo root regardless of where this script was invoked.
cd "$ROOT"

# Default target is the agent loop (run.metta). Pass an alternate repo-relative
# or absolute .metta to run it in this same configured environment, e.g.
#   ./run.sh smoketest.metta   # import-only check; does NOT start the loop
TARGET="${1:-run.metta}"
case "$TARGET" in /*) ;; *) TARGET="$ROOT/$TARGET" ;; esac

exec "$CETTA" --lang he --profile he-extended "$TARGET"
