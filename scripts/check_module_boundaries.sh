#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0

require_in() {
  local file="$1" pattern="$2" description="$3"
  if ! grep -qF "$pattern" "$file"; then
    echo "FAIL module boundary: $description"
    fail=1
  fi
}

forbid_in() {
  local file="$1" pattern="$2" description="$3"
  if grep -qF "$pattern" "$file"; then
    echo "FAIL module boundary: $description"
    fail=1
  fi
}

require_in src/loop.metta './context.metta' 'loop must import live context explicitly'
require_in src/skills.metta './memory.metta' 'dispatcher must import memory commands explicitly'
require_in lib_cettaclaw.metta './src/config.metta' 'manifest must own its configuration adapter'
require_in lib_cettaclaw.metta './src/telegram.metta' 'manifest must own its Telegram adapter'
require_in lib_cettaclaw.metta './src/llm.metta' 'manifest must own its LLM adapter'
require_in lib_cettaclaw.metta './src/value.metta' 'numeric compatibility helpers need a focused module'
require_in lib_cettaclaw.metta './src/text.metta' 'text codecs need a focused module'
require_in lib_cettaclaw.metta './src/wire.metta' 'wire normalization needs a focused module'
forbid_in src/memory.metta '(claw:full-context' 'memory client must not own context construction'
forbid_in src/context.metta '(claw:remember' 'context must not own memory commands'
forbid_in src/context.metta '(claw:query' 'context must not own memory commands'

if [ -e .gitmodules ] || [ -e clawlib ]; then
  echo 'FAIL module boundary: the retired clawlib submodule returned'
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  exit 1
fi

echo 'PASS module boundaries: focused adapters are owned here; clawlib is absent'
