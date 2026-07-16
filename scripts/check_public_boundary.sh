#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

fail=0

check_no_tracked_path() {
  local pattern="$1"
  local matches
  matches="$(git ls-files "$pattern" || true)"
  if [[ -n "$matches" ]]; then
    printf 'FAIL: private runtime path is tracked: %s\n%s\n' "$pattern" "$matches" >&2
    fail=1
  fi
}

check_no_tracked_path '.env'
check_no_tracked_path '.env.*'
check_no_tracked_path 'config/local.toml'
check_no_tracked_path 'config/secrets.env'
check_no_tracked_path 'memory/*'
check_no_tracked_path 'telegram_offset.txt'
check_no_tracked_path 'telegram_updates.jsonl'
check_no_tracked_path 'chroma_db/*'
check_no_tracked_path 'episodes/*'
check_no_tracked_path 'chat/*'
check_no_tracked_path 'archive/*'
check_no_tracked_path 'runtime/test_claw_*'
check_no_tracked_path '.cettaclaw-live-child-*'
check_no_tracked_path '.gitmodules'
check_no_tracked_path 'clawlib'

tracked_text_files="$(
  git ls-files \
    ':!scripts/check_public_boundary.sh' \
    | tr '\n' '\0' \
    | xargs -0 -r grep -Il . 2>/dev/null || true
)"

if [[ -n "$tracked_text_files" ]]; then
  if grep -nE \
      'Moltbook|Claude Code OAuth|BEGIN OPENSSH PRIVATE KEY|BEGIN RSA PRIVATE KEY|api[_-]?key[[:space:]]*=|token[[:space:]]*=|password[[:space:]]*=' \
      $tracked_text_files >/tmp/cettaclaw-public-boundary-grep.$$ 2>/dev/null; then
    cat /tmp/cettaclaw-public-boundary-grep.$$ >&2
    rm -f /tmp/cettaclaw-public-boundary-grep.$$
    fail=1
  else
    rm -f /tmp/cettaclaw-public-boundary-grep.$$
  fi
fi

if git grep -nE '(/home/|/shared/|file://)' -- ':!scripts/check_public_boundary.sh' >/tmp/cettaclaw-public-paths.$$ 2>/dev/null; then
  cat /tmp/cettaclaw-public-paths.$$ >&2
  rm -f /tmp/cettaclaw-public-paths.$$
  fail=1
else
  rm -f /tmp/cettaclaw-public-paths.$$
fi

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi

echo "PASS: public/private boundary clean"
