;; smoketest.metta — import-only check for a fresh checkout / fork.
;; Loads the full CeTTaClaw library and focused src/ adapters against the CeTTa
;; interfaces provided by CETTA_ROOT, but does
;; NOT call the loop, so no agent loop, Telegram channel, or LLM request is ever
;; started. A clean run prints SMOKE_OK and exits.
;;
;; Run it in the configured environment with:
;;   ./run.sh smoketest.metta
!(import! &self ./lib_cettaclaw.metta)
!(println! "SMOKE_OK: agent core + adapters resolved; loop NOT started")
