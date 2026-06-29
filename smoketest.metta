;; Import-only smoke test for a fresh checkout / fork.
;; Loads the full MeTTaClaw library -- resolving the local ./src and ./channels
;; imports and the petta_lib_chromadb dependency, git-cloned into ./repos on the
;; first run -- but does NOT call (mettaclaw), so no agent loop, communication
;; channel, or LLM request is ever started. A clean run prints SMOKE_OK and exits.
;;
;; Run it in the configured environment with:
;;   ./run.sh smoketest.metta
!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)
!(println! "SMOKE_OK: imports and vendored deps resolved; loop NOT started")
