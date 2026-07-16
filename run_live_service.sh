#!/usr/bin/env bash
# Persistent service wrapper for Godel-on-CeTTa (cettaclaw-godel).
#
# Delegates to the guarded bounded launcher, using the streaming bounded session
# as the service chunk: systemd restarts this process after a clean exit, giving
# persistent service behavior without retaining every turn transcript in the
# CeTTa parent process.
set -euo pipefail
cd "$(dirname "$0")"
exec ./run_live_bounded.sh run_live_session_stream.metta
