;; run_live_bounded.metta — bounded REAL live loop.
;;
;; End-to-end live edges against exactly the state in the cettaclaw settings/
;; secrets env files: real getUpdates long-poll from the configured offset file,
;; real LLM (via src/llm), real skill execution, real history
;; append + offset commit on each committable turn (commit=True). Live Telegram
;; sends stay independently gated: without CETTACLAW_LIVE_SEND_APPROVED in the
;; parent env a (send ...) turn ends LiveNotCommitted and advances nothing.
;; NOTE a committable no-send turn DOES commit offset+history even without that
;; approval, so point CETTACLAW_SETTINGS at scratch paths for dry runs.
;;
;; Bounded: 20 iterations under the exclusive run lock, then the lock is released
;; and the process exits — no daemonization. If another run holds the lock this
;; prints RunLockBusy and does nothing.
!(import! &self ./lib_cettaclaw.metta)
!(import! &self ./runtime/loop_driver.metta)

!(claw:live-init)
!(claw:live-loop-n-locked-to-path (claw:live-run-lock-path) 20 20 True)
