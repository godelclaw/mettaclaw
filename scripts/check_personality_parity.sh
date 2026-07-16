#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
reference="${1:-}"

if [ -z "$reference" ]; then
  echo "usage: $0 <reference-agent-root>" >&2
  exit 2
fi

env_value() {
  local file="$1" key="$2" line value
  [ -f "$file" ] || return 1
  line="$(sed -nE "s/^export ${key}=(.*)$/\\1/p" "$file" | head -1)"
  [ -n "$line" ] || return 1
  value="$line"
  value="${value#\'}"; value="${value%\'}"
  value="${value#\"}"; value="${value%\"}"
  printf '%s\n' "$value"
}

for tree in "$reference" "$root"; do
  [ -f "$tree/identity/default-prompt.txt" ] || {
    echo "FAIL personality parity: identity/default-prompt.txt missing" >&2
    exit 1
  }
done

cmp -s "$reference/identity/default-prompt.txt" "$root/identity/default-prompt.txt" || {
  echo "FAIL personality parity: identity/default-prompt.txt differs" >&2
  exit 1
}

# Live state may intentionally live outside either source tree. Compare the
# configured prompt targets rather than stale in-tree memory/ placeholders.
reference_prompt="$(env_value "$reference/.env" METTACLAW_PROMPT_PATH || true)"
root_prompt="$(env_value "$root/.env" METTACLAW_PROMPT_PATH || true)"
[ -n "$reference_prompt" ] || reference_prompt="$reference/memory/prompt.txt"
[ -n "$root_prompt" ] || root_prompt="$root/memory/prompt.txt"

for prompt in "$reference_prompt" "$root_prompt"; do
  [ -f "$prompt" ] || {
    echo "FAIL personality parity: configured live prompt missing" >&2
    exit 1
  }
done

cmp -s "$reference_prompt" "$root_prompt" || {
  echo "FAIL personality parity: configured live prompts differ" >&2
  exit 1
}

echo "PASS personality parity: default and live prompts are byte-identical"
