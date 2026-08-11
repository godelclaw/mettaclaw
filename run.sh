#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
PETTA_ROOT="${PETTA_ROOT:-${HOME:-}/repos/PeTTa}"
PETTA_PY_ENV="${PETTA_PY_ENV:-${HOME:-}/miniforge3/envs/petta}"
METTACLAW_ENGINE="${METTACLAW_ENGINE:-petta}"
PLEATTA_ROOT="${PLEATTA_ROOT:-${HOME:-}/repos/LeaTTa-petta}"

if [ -x "$ROOT/initialize.sh" ]; then
    "$ROOT/initialize.sh" >/dev/null
fi

if [ -f "$ROOT/.env" ]; then
    set -a
    . "$ROOT/.env"
    set +a
fi

if [ -f "$ROOT/config/secrets.env" ]; then
    set -a
    . "$ROOT/config/secrets.env"
    set +a
fi

if [ -d "$PETTA_PY_ENV" ]; then
    export LD_LIBRARY_PATH="$PETTA_PY_ENV/lib:${LD_LIBRARY_PATH:-}"
    export PYTHONHOME="$PETTA_PY_ENV"
    export PYTHONNOUSERSITE=1
    # Keep PATH in sync with PYTHONHOME: a bare `python3` (e.g. from a shell
    # skill or subprocess) must resolve to THIS env's interpreter, or it loads
    # the wrong stdlib and dies with "ModuleNotFoundError: encodings".
    export PATH="$PETTA_PY_ENV/bin:$HOME/.local/bin:$PATH"
    # ~/.local/bin: systemd user services run no login shell, so ~/.profile
    # never adds it — without this line the agent lives in a poorer PATH
    # than any interactive shell (claude, cc-telegram, user tools all live there).
else
    echo "warning: PETTA_PY_ENV ($PETTA_PY_ENV) not found; the Python bridge will likely fail. Set petta_py_env in config/local.toml." >&2
fi

# Keep py-call module resolution local and reproducible. This deliberately does
# not inherit an external PYTHONPATH, which would mix venvs again.
export PYTHONPATH="$ROOT/src:$ROOT/channels"

export SYNTHETIC_MODEL="${SYNTHETIC_MODEL:-syn:large:text}"
export METTACLAW_CHROMA_DIR="${METTACLAW_CHROMA_DIR:-$ROOT/chroma_db}"
export METTACLAW_CHROMA_COLLECTION="${METTACLAW_CHROMA_COLLECTION:-memories}"
export METTACLAW_CHROMA_METRIC="${METTACLAW_CHROMA_METRIC:-cosine}"
export METTACLAW_CHROMA_SYNC_THRESHOLD="${METTACLAW_CHROMA_SYNC_THRESHOLD:-20}"
export METTACLAW_MEMORY_LOG_DIR="${METTACLAW_MEMORY_LOG_DIR:-$ROOT/memory/remembered}"
export METTACLAW_TELEGRAM_OFFSET_PATH="${METTACLAW_TELEGRAM_OFFSET_PATH:-$ROOT/telegram_offset.txt}"
export METTACLAW_EMBED_MODEL="${METTACLAW_EMBED_MODEL:-}"
export METTACLAW_EMBED_DIM="${METTACLAW_EMBED_DIM:-1024}"
export METTACLAW_EMBED_DEVICE="${METTACLAW_EMBED_DEVICE:-auto}"
export METTACLAW_EMBED_QUERY_PROMPT_NAME="${METTACLAW_EMBED_QUERY_PROMPT_NAME:-query}"
export METTACLAW_EMBED_NORMALIZE="${METTACLAW_EMBED_NORMALIZE:-1}"
export METTACLAW_EMBED_MAX_TOKENS="${METTACLAW_EMBED_MAX_TOKENS:-4096}"
# One shared embedding daemon for the whole machine; never load Qwen in-process.
export METTACLAW_EMBED_ENDPOINT="${METTACLAW_EMBED_ENDPOINT:-http://127.0.0.1:8876}"

# Cooperative heap recycling. A requester creates the flag; the running loop
# exits after its current turn; this new process removes the acknowledged flag.
STATE_HOME="${XDG_STATE_HOME:-${HOME:-}/.local/state}"
INSTANCE="${METTACLAW_INSTANCE:-$(basename "$ROOT")}"
export METTACLAW_RECYCLE_REQUEST_PATH="${METTACLAW_RECYCLE_REQUEST_PATH:-$STATE_HOME/$INSTANCE/recycle.requested}"
mkdir -p "$(dirname "$METTACLAW_RECYCLE_REQUEST_PATH")"

mkdir -p "$METTACLAW_CHROMA_DIR" "$METTACLAW_MEMORY_LOG_DIR" "$ROOT/chat" "$ROOT/episodes"

# Local imports (./src, ./memory, ./lib_mettaclaw) and git-import's default
# ./repos clone dir resolve relative to CWD, so always launch from the repo
# root regardless of where this script was invoked from.
cd "$ROOT"

# Default target is the agent loop (run.metta). Pass an alternate repo-relative
# or absolute .metta to run it in this same configured environment, e.g.
#   ./run.sh smoketest.metta   # import-only check; does NOT start the loop
TARGET="${1:-run.metta}"
case "$TARGET" in /*) ;; *) TARGET="$ROOT/$TARGET" ;; esac

# Only the real agent process acknowledges a request. Test and utility targets
# must not clear a flag intended for a concurrently running service.
if [ "$TARGET" = "$ROOT/run.metta" ]; then
    rm -f "$METTACLAW_RECYCLE_REQUEST_PATH"
fi

# Memory-index startup diagnostic and best-effort hard-drift recovery.
# Chroma flushes its HNSW index only every sync_threshold writes; an index far
# behind the write-ahead log segfaults the process when the backlog is replayed
# at query time. This subprocess reports to the service journal, not the model
# prompt. It attempts catch-up only at dangerous drift and reports measured
# before/after state. It remains non-fatal so diagnostics cannot prevent boot.
PYTHONPATH="$ROOT/src:$ROOT/repos/petta_lib_chromadb" \
    "$PETTA_PY_ENV/bin/python3" "$ROOT/src/memory_health.py" 2>&1 || true

case "$METTACLAW_ENGINE" in
    petta)
        exec "$PETTA_ROOT/run.sh" "$TARGET" default
        ;;
    pleatta)
        PLEATTA_BIN="${PLEATTA_BIN:-$PLEATTA_ROOT/.lake/build/bin/pleatta}"
        PLEATTA_PY_WORKER="${PLEATTA_PY_WORKER:-$PLEATTA_ROOT/scripts/pleatta-python-worker.py}"
        if [ ! -x "$PLEATTA_BIN" ]; then
            echo "PLeaTTa executable is unavailable; build it or set PLEATTA_BIN" >&2
            exit 2
        fi
        if [ ! -f "$PLEATTA_PY_WORKER" ]; then
            echo "PLeaTTa Python worker is unavailable; set PLEATTA_PY_WORKER" >&2
            exit 2
        fi
        if [ -x "$PETTA_PY_ENV/bin/python3" ]; then
            export PLEATTA_PYTHON="${PLEATTA_PYTHON:-$PETTA_PY_ENV/bin/python3}"
        else
            export PLEATTA_PYTHON="${PLEATTA_PYTHON:-$(command -v python3)}"
        fi
        export PLEATTA_PY_WORKER
        export PETTA_LIB_ROOT="${PETTA_LIB_ROOT:-$PETTA_ROOT/lib}"
        export PLEATTA_LIBRARY_PATH="${PLEATTA_LIBRARY_PATH:-$ROOT:$ROOT/repos/petta_lib_chromadb}"
        # Host confinement and maximum sleep are optional operator policies.
        # Do not silently change native PeTTa semantics when they are unset.
        unset PLEATTA_CALL_FIXTURE

        TRANSCRIPT_DIR="${METTACLAW_TRANSCRIPT_DIR:-$STATE_HOME/$INSTANCE/pleatta-transcripts}"
        umask 077
        mkdir -p "$TRANSCRIPT_DIR"
        TRANSCRIPT="$TRANSCRIPT_DIR/$(date -u '+%Y%m%dT%H%M%SZ')-$$.json"
        exec "$PLEATTA_BIN" --host-live "$TARGET" "$TRANSCRIPT" \
            "${PLEATTA_FUEL:-4000000}" -- default
        ;;
    *)
        echo "unknown METTACLAW_ENGINE: $METTACLAW_ENGINE" >&2
        exit 2
        ;;
esac
