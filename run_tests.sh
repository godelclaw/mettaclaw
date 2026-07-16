#!/usr/bin/env bash
# Offline test suite for cettaclaw-godel: the import smoketest + the agent-core
# goldens (loop arming, message keying, turn, send gate, llm skills). No network,
# no secrets, no live send. Usage: ./run_tests.sh [/path/to/cetta]
set -euo pipefail
cd "$(dirname "$0")"
CETTA="${1:-${CETTA_ROOT:-$HOME/repos/cetta-interfaces}/cetta}"
[ -x "$CETTA" ] || { echo "need a cetta (interfaces) binary: ./run_tests.sh /path/to/cetta"; exit 2; }
TEST_PYTHON="${PYTHON:-python3}"
command -v "$TEST_PYTHON" >/dev/null 2>&1 || {
  echo "need a Python interpreter for offline fixtures: set PYTHON or install python3"
  exit 2
}
mkdir -p runtime
agent_name="${CETTACLAW_AGENT_NAME:-$(basename "$PWD")}"

pass=0; fail=0; failed=""

if ./scripts/check_module_boundaries.sh; then
  pass=$((pass + 1))
else
  echo "FAIL  scripts/check_module_boundaries.sh"
  fail=$((fail + 1))
  failed="$failed scripts/check_module_boundaries.sh"
fi

if ./scripts/check_public_boundary.sh; then
  pass=$((pass + 1))
else
  echo "FAIL  scripts/check_public_boundary.sh"
  fail=$((fail + 1))
  failed="$failed scripts/check_public_boundary.sh"
fi

if journal_out="$($TEST_PYTHON -m unittest tests.test_memory_journal tests.test_turn_journal 2>&1)"; then
  echo "PASS  Python memory/turn journal tests"
  pass=$((pass + 1))
else
  echo "FAIL  Python memory/turn journal tests"
  printf '%s\n' "$journal_out"
  fail=$((fail + 1))
  failed="$failed Python-journal-tests"
fi

run_one() {
  local t="$1"
  local out exp
  if [ "$t" = "tests/test_claw_mcp_offline.metta" ]; then
    out="$(
      METTACLAW_MCP_PYTHON="$TEST_PYTHON" \
      METTACLAW_MCP_BRIDGE_CLI="$PWD/tests/fixtures/fake_mcp_bridge_cli.py" \
      timeout 120 "$CETTA" --lang he --profile he-extended "$t" 2>&1
    )"
  else
    out="$(timeout 120 "$CETTA" --lang he --profile he-extended "$t" 2>&1)"
  fi
  exp="${t%.metta}.expected"
  if printf '%s\n' "$out" | grep -qiE 'Error|Missed results|Excessive results'; then
    echo "FAIL  $t"; fail=$((fail + 1)); failed="$failed $t"
  elif [ -f "$exp" ] && ! diff -u "$exp" <(printf '%s\n' "$out"); then
    echo "FAIL  $t (golden mismatch)"; fail=$((fail + 1)); failed="$failed $t"
  else
    echo "PASS  $t"; pass=$((pass + 1))
  fi
}

# Import smoketest (loop NOT started).
run_one smoketest.metta
# Core goldens.
for t in tests/test_claw_*.metta; do run_one "$t"; done

echo "$agent_name: $pass passed, $fail failed${failed:+ (failed:$failed)}"
[ "$fail" = 0 ]
