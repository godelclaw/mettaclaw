;; runtime/bounded_eval.metta — child-bounded evaluation of an LLM turn.
;; The balanced command list is parse-preflighted, then run in a bounded child
;; copy of this binary (15m, 1 MiB cap) with the agent state serialized in and
;; the mutated state read back. Malformed MeTTa or a runaway turn cannot kill the
;; parent daemon. The child imports the agent library (lib_cettaclaw.metta) with
;; CWD = repo root, and runs under a passthrough env (send-approval etc.).
!(import! &self fs)
!(import! &self process)
!(import! &self str)
!(import! &self system)
!(import! &self ../src/config.metta)
!(import! &self ../src/wire.metta)
!(import! &self ../src/utils.metta)
!(import! &self ../src/context.metta)

;; PeTTaClaw lets each skill enforce its own bound. The slowest compatible
;; skills (memory and MCP) allow 180s and 120s respectively, and the prompt
;; permits five commands. Keep a final runaway guard without pre-empting those
;; ordinary per-skill limits.
(= (claw:live-command-batch-timeout-ms) 900000)

(= (claw:live-text-contains? $haystack $needle)
   (if (== (collapse (str:find $haystack $needle)) ()) False True))

(= (claw:live-parse-preflight-program $balanced)
   (str:concat "!(parse " (str:concat (repr $balanced) ")\n")))

(= (claw:live-parse-preflight $balanced)
   (process-run-cmd-cwd-env-stdin-timeout-cap-bytes
     ("/proc/self/exe" "--lang" "he" "--profile" "he-extended" "/dev/stdin")
     ""
     ()
     (claw:live-parse-preflight-program $balanced)
     5000
     1048576))

(= (claw:live-parse-error-output? $text)
   (claw:live-text-contains? $text "[(Error (parse "))

(= (claw:live-parse-preflight-ok? $r)
   (if (process-result-timed-out? $r)
       False
       (if (not (== (process-result-exit-code $r) 0))
           False
           (not (claw:live-parse-error-output?
                  (process-result-aggregated-output $r))))))

(= (claw:live-record-response $msg $cmds $results)
   (let $rtext (repr $results)
   (let $old (get-state &history)
   (let $entry (Entry (claw:msg-text $msg) $rtext)
   (let $_ (change-state! &history (cons-atom $entry $old))
   (let $__ (change-state! &last $rtext)
        (LiveActed $cmds $results)))))))

(= (claw:live-child-state-record $results)
   (ChildState
     (get-state &loops)
     (get-state &sleep-ms)
     (get-state &pins)
     (get-state &last)
     (get-state &llm-model)
     $results))

;; Only bounded short-term state crosses the child-eval boundary. The parent
;; owns durable history and last-results; the child needs enough state for
;; command effects, not the full accumulated daemon transcript.
(= (claw:live-max-child-pins) 256)

(= (claw:live-pin-prefix () $remaining) ())
(= (claw:live-pin-prefix $pins $remaining)
   (if (<= $remaining 0)
       ()
       (let ($head $tail) (decons-atom $pins)
            (cons-atom $head
              (claw:live-pin-prefix $tail (- $remaining 1))))))

(= (claw:live-child-pins)
   (claw:live-pin-prefix (get-state &pins) (claw:live-max-child-pins)))

(= (claw:live-child-last)
   (claw:feedback-tail (get-state &last)))

(= (claw:live-child-run-line $balanced $state-path)
   (str:concat
     "!(let $results (claw:run-all-quoted (quote "
     (str:concat $balanced
       (str:concat ")) (let $loops (get-state &loops) (let $sleep-ms (get-state &sleep-ms) (let $pins (get-state &pins) (let $last (get-state &last) (let $llm-model (get-state &llm-model) (fs:write-text "
         (str:concat (repr $state-path)
           " (repr (ChildState $loops $sleep-ms $pins $last $llm-model $results)))))))))")))))

(= (claw:live-child-program $balanced $state-path)
   (let $reply-chat (get-state &reply-chat)
   (let $pending-offset (get-state &pending-offset)
   (let $loops (get-state &loops)
   (let $max-loops (get-state &max-loops)
   (let $sleep-ms (get-state &sleep-ms)
   (let $default-sleep-ms (get-state &default-sleep-ms)
   (let $pins (claw:live-child-pins)
   (let $last (claw:live-child-last)
   (let $llm-model (get-state &llm-model)
        (str:join "\n"
          ("!(import! &self fs)"
           "!(import! &self lib_cettaclaw.metta)"
           (str:concat "!(claw:init "
             (str:concat (repr $max-loops) " ())"))
           (str:concat "!(change-state! &loops "
             (str:concat (repr $loops) ")"))
           (str:concat "!(change-state! &max-loops "
             (str:concat (repr $max-loops) ")"))
           (str:concat "!(change-state! &sleep-ms "
             (str:concat (repr $sleep-ms) ")"))
           (str:concat "!(change-state! &default-sleep-ms "
             (str:concat (repr $default-sleep-ms) ")"))
           (str:concat "!(change-state! &pins "
             (str:concat (repr $pins) ")"))
           (str:concat "!(change-state! &last "
             (str:concat (repr $last) ")"))
           (str:concat "!(change-state! &llm-model "
             (str:concat (repr $llm-model) ")"))
           (str:concat "!(change-state! &reply-chat "
             (str:concat (repr $reply-chat) ")"))
           (str:concat "!(change-state! &pending-offset "
             (str:concat (repr $pending-offset) ")"))
           (claw:live-child-run-line $balanced $state-path)
           ""))))))))))))

(= (claw:live-child-program-path)
   (let $run-id (system:getenv-or-default "CETTACLAW_RUN_ID" "manual")
   (let $offset (get-state &pending-offset)
        (str:concat ".cettaclaw-live-child-"
          (str:concat $run-id
            (str:concat "-"
              (str:concat (if (== $offset "") "preview" $offset)
                          ".metta")))))))

(= (claw:live-child-state-path $program-path)
   (str:concat $program-path ".state"))

(= (claw:live-child-repo-root)
   (system:getenv-or-default "CETTACLAW_REPO_ROOT" "."))

(= (claw:live-child-output-error? $text)
   (claw:live-text-contains? $text "[(Error "))

(= (claw:live-child-state-from-parsed $value)
   (case $value
     (((ChildState $loops $sleep-ms $pins $last $llm-model $results)
       (ChildState $loops $sleep-ms $pins $last $llm-model $results))
      ($other (ChildStateBadShape $other)))))

(= (claw:live-child-state-from-path $path)
   (if (fs:exists $path)
       (case (fs:read-text $path)
         (((FsError $msg) (ChildStateReadFailed $msg))
          ($text (claw:live-child-state-from-parsed (parse $text)))))
       ChildStateMissing))

(= (claw:live-apply-child-state
      (ChildState $loops $sleep-ms $pins $last $llm-model $results))
   (let $_a (change-state! &loops $loops)
   (let $_b (change-state! &sleep-ms $sleep-ms)
   (let $_c (change-state! &pins $pins)
   (let $_d (change-state! &last $last)
   (let $_e (change-state! &llm-model $llm-model)
        (ChildStateApplied $loops $sleep-ms)))))))

(= (claw:live-child-state-results
      (ChildState $loops $sleep-ms $pins $last $llm-model $results))
   $results)

(= (claw:live-run-response-child-finish $path $state-path $r)
   (let $state (claw:live-child-state-from-path $state-path)
   (let $_a (if (fs:exists $path) (fs:remove $path) ())
   (let $_b (if (fs:exists $state-path) (fs:remove $state-path) ())
        (if (process-result-timed-out? $r)
            ((ChildCommandsTimeout (process-result-aggregated-output $r)))
            (if (== (process-result-exit-code $r) 0)
                (case $state
                  (((ChildState $loops $sleep-ms $pins $last $llm-model $results)
                    (let $_state (claw:live-apply-child-state $state)
                         (claw:live-child-state-results $state)))
                   ($bad
                    (if (claw:live-child-output-error?
                          (process-result-aggregated-output $r))
                        ((ChildCommandsFailed
                          0
                          (process-result-aggregated-output $r)))
                        ((ChildCommandsStateMissing
                          (process-result-aggregated-output $r)
                          $bad))))))
                ((ChildCommandsFailed
                  (process-result-exit-code $r)
                  (process-result-aggregated-output $r)))))))))

;; The child runs in a WIPED environment (the native side clearenv()s and
;; replaces with this list — it does not augment). So pass through the vars the
;; skills need: send-approval (WITHOUT this every (send ...) only previews and
;; never reaches Telegram — the regression that made Gödel silent), the
;; config/secrets paths, run-id, repo root, and HOME/PATH for file/shell skills.
(= (claw:live-child-env)
   ((Env "CETTACLAW_LIVE_SEND_APPROVED"
         (system:getenv-or-default "CETTACLAW_LIVE_SEND_APPROVED" ""))
    (Env "CETTACLAW_SETTINGS"
         (system:getenv-or-default "CETTACLAW_SETTINGS"
           (str:concat (claw:home) "/.config/cettaclaw/settings.env")))
    (Env "CETTACLAW_SECRETS"
         (system:getenv-or-default "CETTACLAW_SECRETS"
           (str:concat (claw:home) "/.config/cettaclaw/secrets.env")))
    (Env "CETTACLAW_RUN_ID" (system:getenv-or-default "CETTACLAW_RUN_ID" "child"))
    (Env "CETTACLAW_REPO_ROOT" (system:getenv-or-default "CETTACLAW_REPO_ROOT" "."))
    (Env "HOME" (system:getenv-or-default "HOME" (claw:home)))
    (Env "PATH"
         (system:getenv-or-default "PATH" "/usr/local/bin:/usr/bin:/bin"))))

(= (claw:live-run-response-child $balanced)
   (let $path (claw:live-child-program-path)
   (let $state-path (claw:live-child-state-path $path)
   (let $program (claw:live-child-program $balanced $state-path)
   (let $_clear (if (fs:exists $state-path) (fs:remove $state-path) ())
        (case
          (once
            (process-run-cmd-cwd-env-stdin-timeout-cap-bytes
              ("/proc/self/exe" "--lang" "he" "--profile" "he-extended" "/dev/stdin")
              (claw:live-child-repo-root)
              (claw:live-child-env)
              $program
              (claw:live-command-batch-timeout-ms)
              1048576))
          (($r (claw:live-run-response-child-finish
                 $path $state-path $r)))))))))

(= (claw:live-run-response $msg $raw)
   (let $balanced (claw:balance-parens $raw)
   (let $preflight (claw:live-parse-preflight $balanced)
        (if (claw:live-parse-preflight-ok? $preflight)
            (claw:live-record-response
              $msg
              (ParsedCommands $balanced)
              (claw:live-run-response-child $balanced))
            (claw:live-record-response
              $msg
              (ParseFailed $balanced)
              ((CommandParseFailed
                 (process-result-aggregated-output $preflight))))))))
