#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
PETTA_ROOT="${PETTA_ROOT:-${HOME:-}/repos/PeTTa}"
PETTA_PY_ENV="${PETTA_PY_ENV:-${HOME:-}/miniforge3/envs/pettaclaw}"
SESSION_MEMORY_PYTHON="${SESSION_MEMORY_PYTHON:-}"

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
else
    echo "warning: PETTA_PY_ENV ($PETTA_PY_ENV) not found; the Python bridge will likely fail. Set petta_py_env in config/local.toml." >&2
fi

if [ -x "$SESSION_MEMORY_PYTHON" ]; then
    session_memory_site="$("$SESSION_MEMORY_PYTHON" - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)"
    export PYTHONPATH="$session_memory_site${PYTHONPATH:+:$PYTHONPATH}"
fi

export SYNTHETIC_MODEL="${SYNTHETIC_MODEL:-syn:large:text}"
export METTACLAW_CHROMA_DIR="${METTACLAW_CHROMA_DIR:-$ROOT/chroma_db}"
export METTACLAW_CHROMA_COLLECTION="${METTACLAW_CHROMA_COLLECTION:-pettaclaw_ltm}"
export METTACLAW_CHROMA_METRIC="${METTACLAW_CHROMA_METRIC:-cosine}"
export METTACLAW_TELEGRAM_OFFSET_PATH="${METTACLAW_TELEGRAM_OFFSET_PATH:-$ROOT/telegram_offset.txt}"
export METTACLAW_EMBED_MODEL="${METTACLAW_EMBED_MODEL:-}"
export METTACLAW_EMBED_DIM="${METTACLAW_EMBED_DIM:-1024}"
export METTACLAW_EMBED_DEVICE="${METTACLAW_EMBED_DEVICE:-auto}"
export METTACLAW_EMBED_QUERY_PROMPT_NAME="${METTACLAW_EMBED_QUERY_PROMPT_NAME:-query}"
export METTACLAW_EMBED_NORMALIZE="${METTACLAW_EMBED_NORMALIZE:-1}"
export METTACLAW_EMBED_MAX_TOKENS="${METTACLAW_EMBED_MAX_TOKENS:-4096}"

mkdir -p "$METTACLAW_CHROMA_DIR" "$ROOT/chat" "$ROOT/episodes"

# Local imports (./src, ./memory, ./lib_mettaclaw) and git-import's default
# ./repos clone dir resolve relative to CWD, so always launch from the repo
# root regardless of where this script was invoked from.
cd "$ROOT"

# Default target is the agent loop (run.metta). Pass an alternate repo-relative
# or absolute .metta to run it in this same configured environment, e.g.
#   ./run.sh smoketest.metta   # import-only check; does NOT start the loop
TARGET="${1:-run.metta}"
case "$TARGET" in /*) ;; *) TARGET="$ROOT/$TARGET" ;; esac

exec "$PETTA_ROOT/run.sh" "$TARGET" default
