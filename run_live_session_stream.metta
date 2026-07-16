;; run_live_session_stream.metta — daemon-friendly bounded LIVE loop.
;;
;; The service chunk: real getUpdates long-poll → LLM → bounded child run →
;; committable-only history+offset commit, under the exclusive run lock. The
;; parent keeps only a small count summary (not every turn transcript), so
;; systemd can restart this bounded chunk for persistent service with a regular
;; process-level memory reset. Live sends stay gated on CETTACLAW_LIVE_SEND_APPROVED.
!(import! &self ./lib_cettaclaw.metta)
!(import! &self ./runtime/loop_driver.metta)

!(claw:live-init)
!(claw:live-loop-n-stream-locked-to-path (claw:live-run-lock-path) 120 20 True)
