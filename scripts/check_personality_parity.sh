#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
reference="${1:-}"

if [ -z "$reference" ]; then
  echo "usage: $0 <reference-agent-root>" >&2
  exit 2
fi

for relative in identity/default-prompt.txt memory/prompt.txt; do
  if [ ! -f "$reference/$relative" ]; then
    echo "FAIL personality parity: reference lacks $relative" >&2
    exit 1
  fi
  if [ ! -f "$root/$relative" ]; then
    echo "FAIL personality parity: Cettaclaw tree lacks $relative" >&2
    exit 1
  fi
  if ! cmp -s "$reference/$relative" "$root/$relative"; then
    echo "FAIL personality parity: $relative differs" >&2
    exit 1
  fi
done

echo "PASS personality parity: default and live prompts are byte-identical"
