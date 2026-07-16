;; runtime/turn_driver.metta — one live turn: receive → LLM → bounded run →
;; finalize. live-init hoists the loop state cells plus the live counters
;; (&live-k, &live-last-msg); live-one-turn-from-msg is the real-LLM turn (the
;; provider claw:llm-chat is supplied by the entrypoint — lib_cettaclaw.metta for
;; real, tests/fixtures/llm.metta offline). The *-with-response variants inject a raw
;; model reply for offline goldens.
!(import! &self time)
!(import! &self ../src/value.metta)
!(import! &self ../src/loop.metta)
!(import! &self ./telegram_receive.metta)
!(import! &self ./bounded_eval.metta)
!(import! &self ./commit.metta)

(= (claw:live-init)
   (let $_ (claw:init (claw:max-loops) ())
   (let $__ (change-state! &tg-queue (TgQueue ()))
   (let $___ (bind! &live-k (new-state 1))
   (let $____ (bind! &live-last-msg (new-state NoLiveMessage))
        ClawReady)))))

(= (claw:live-tick)
   (let $k (get-state &live-k)
   (let $_ (change-state! &live-k (+ $k 1))
        (claw:tick $k))))

(= (claw:live-sleep-seconds)
   (/ (get-state &sleep-ms) 1000))

(= (claw:live-context $msg $msgnew $humanmsg)
   (claw:full-context (claw:msg-text $msg)
                      (get-state &loops)
                      (claw:live-sleep-seconds)
                      $msgnew
                      $humanmsg
                      (get-state &last)))

(= (claw:live-one-turn-from-msg-with-response $msg $raw $commit)
   (let $_ (claw:live-tick)
   (let $msgnew (claw:note-prevmsg (claw:msg-key $msg))
   (let $humanmsg (claw:is-human $msg)
   (let $__ (if (and $msgnew $humanmsg) (claw:arm-msg $msg) ClawNoop)
   (let $heartbeat (claw:maybe-heartbeat)
        (if (and (claw:live-real-message? $msg) (> (get-state &loops) 0))
            (let $acted (claw:live-run-response $msg $raw)
            (let $results (case $acted (((LiveActed $cmds $r) $r) ($o ())))
            (let $finish (claw:live-finalize-new $msg $raw $results $msgnew $commit)
                 (LiveTurn $msg $msgnew $humanmsg $acted $finish))))
            (LiveTurn
              $msg $msgnew $humanmsg LiveIdle
              (if (and $commit (not (== (get-state &pending-offset) "")))
                  (claw:live-commit-pending-offset)
                  LiveNoCommit)))))))))

(= (claw:live-sleep-current)
   (time:sleep-ms (get-state &sleep-ms)))

(= (claw:live-loop-step-from-msg-with-response $msg $raw $commit)
   (let $turn (claw:live-one-turn-from-msg-with-response $msg $raw $commit)
   (let $slept (claw:live-sleep-current)
        (LiveLoopStep $turn $slept))))

(= (claw:live-one-turn-from-body-with-response $body $raw $commit)
   (claw:live-one-turn-from-msg-with-response
     (claw:live-receive-from-body $body) $raw $commit))

;; Real LLM path. The provider (claw:llm-chat) is supplied by the entrypoint —
;; lib_cettaclaw.metta imports src/llm for real runs (the test fixture stays
;; under tests/fixtures); the model + policy are the agent's, resolved here.
(= (claw:live-one-turn-from-msg $msg $commit)
   (let $_ (claw:live-tick)
   (let $msgnew (claw:note-prevmsg (claw:msg-key $msg))
   (let $humanmsg (claw:is-human $msg)
   (let $__ (if (and $msgnew $humanmsg) (claw:arm-msg $msg) ClawNoop)
   (let $heartbeat (claw:maybe-heartbeat)
        (if (and (claw:live-real-message? $msg) (> (get-state &loops) 0))
            (let $ctx (claw:live-context $msg $msgnew $humanmsg)
            (let $raw (claw:llm-chat (claw:session-model)
                                     (claw:max-output-tokens)
                                     (claw:reasoning-effort)
                                     $ctx)
            (let $acted (claw:live-run-response $msg $raw)
            (let $results (case $acted (((LiveActed $cmds $r) $r) ($o ())))
            (let $finish (claw:live-finalize-new $msg $raw $results $msgnew $commit)
                 (LiveTurn $msg $msgnew $humanmsg $raw $acted $finish))))))
            (LiveTurn
              $msg $msgnew $humanmsg "()" LiveIdle
              (if (and $commit (not (== (get-state &pending-offset) "")))
                  (claw:live-commit-pending-offset)
                  LiveNoCommit)))))))))

(= (claw:live-one-turn $timeout-s $commit)
   (claw:live-one-turn-from-msg (claw:live-receive $timeout-s) $commit))

(= (claw:live-one-turn-preview $timeout-s)
   (claw:live-one-turn $timeout-s False))

(= (claw:live-one-turn-commit $timeout-s)
   (claw:live-one-turn $timeout-s True))
