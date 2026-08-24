(= (sleepInterval) (empty))
(= (LLM) (empty))
(= (maxOutputToken) (empty))
(= (reasoningMode) (empty))

(= (heartbeatInterval)
   (py-call (helper.int_env "METTACLAW_HEARTBEAT_INTERVAL_SECONDS" 1800)))

(= (initialPeriphery)
   (let $selected (py-call (loop_modes.current_mode))
     (coordinate iteration 1
     (coordinate loops
       (py-call (helper.boot_int "loops" (policy-burst-budget $selected)))
       (coordinate sleep-interval
         (py-call (helper.boot_int "sleepInterval" (sleepInterval)))
         (coordinate last-results
           (py-call (helper.boot_str "lastresults" ""))
           (coordinate last-heartbeat
             (py-call (helper.boot_num "last_heartbeat" (get_time)))
             (coordinate active-policy $selected
               (coordinate autonomous-ready 0
                 (coordinate banked-loops
                   (py-call (helper.boot_int "banked_loops" 0))
                   (coordinate pending-continuation
                     no-continuation coordinates-empty)))))))))))

(= (initLoop)
   (progn
     (py-call (helper.recycle_ack))
     (py-call (helper.working_boot))
     (configure sleepInterval 1)
     (configure LLM syn:large:text)
     (configure maxOutputToken 32768)
     (configure reasoningMode medium)
     (rooted weak-process-core-v1 (initialPeriphery))))

;; Static context leads and changing policy state trails, preserving provider
;; prefix caching while making the request projection explicit.  Skills are a
;; separate advertisement so Iter may transform them without receiving the
;; command dispatcher's executable authority.
(= (getContextPrefix)
   (string-safe (py-str ("PROMPT: " (getPrompt)))))

(= (getContextSuffix $periphery)
   (string-safe
     (py-str
       (" OUTPUT_FORMAT: Output a ((skillName args) ...) S-expression containing at most "
        (policy-command-batch-limit (loop-active-policy $periphery))
        " command(s). You choose whether this turn needs one observation-sensitive command or a batch of independent commands. A new inbound stimulus interrupts the unexecuted suffix. Command results are not observed by you until the next model step, so never precommit a later command whose correctness depends on an earlier result. Double-check the parentheses: it must be (cmd1 ... cmdn). Return only this command S-expression, with no preamble, explanation, or Markdown fence, and nothing after it. Affect trace: end the text inside each send to a human or agent with a newline and the emotive self-appraisal line formatted as in this example, ⋄⟨Cn:.5 C:.7 Ct:.8 I:.2 J:.6 A:.4 S:.6 Co:-.42 Sp:.3⟩, values ∈ [-1,1]. Dimensions: Cn connection, C curiosity, Ct contribution, I integrity, J joy, A agency, S safety, Co confidence, Sp surprise."
        " each arg is an explicit string hence needs quotes, and variables are forbidden!"
        " LOOPS_LEFT: " (loop-budget $periphery)
        " SLEEP_INTERVAL_SECONDS: " (loop-sleep $periphery)
        " ACTIVE_MODE: " (loop-active-policy $periphery)
        " ACTIVE_MODEL: " (py-call (synthetic_llm.current_model))
        " ATTENTION_DAG: " (repr (attention-view))
        " LAST_SKILL_USE_RESULTS: "
        (last_chars (loop-last-results $periphery) (maxFeedback))
        " CONTEXT_SOURCES: " (addition-context-sources)
        " CONTEXT_ORDER: NEW_ACTIVITY appended after this context is newest and authoritative for this turn; SOURCE[effect-receipts] is the authoritative record of which brokered commands returned, were withheld, or were deferred — returned is not domain success, so inspect its result; SOURCE[recent-proposals] contains model requests only and never proves execution or success; SOURCE[relevant-files] is derived from proposals; SOURCE[project-capabilities] is a revision-bound executable inventory — consult it before proposing a local subsystem from scratch; SOURCE[conversation] is prior witnessed dialogue; pins and retrieved memories are fallible working aids and never override newer witnessed dialogue; status=unavailable is not evidence of absence."
        " TIME: " (get_time_as_string)))))

(= (getContext $periphery)
   (string-safe
     (py-str
       ((getContextPrefix) " SKILLS: " (getSkills)
        (getContextSuffix $periphery)))))

(= (HandleError $msg $cmd $sexpr)
   (case $sexpr
     (((Error $a $b)
       (let $new (append (get-state &error) (($msg $cmd)))
            (change-state! &error $new)))
      ($else $sexpr))))

;; Heartbeat is a replaceable life-policy transformation over the periphery.
;; The life-rhythm renews unconditionally: rest is a nap, not death, so a
;; rest in progress must not also switch off the heartbeat. Suppressing it
;; too left a rested agent with no way back to life but a human message.
(= (heartbeatDue $periphery $now)
   (if (<= (heartbeatInterval) 0)
       False
       (>= (- $now (loop-last-heartbeat $periphery))
           (heartbeatInterval))))

;; What a renewal does to the budget it finds is the fuel discipline's
;; decision, not the heartbeat's: saturate replaces, accumulate adds, carry
;; adds under a ceiling, decay keeps most. Only the grant is policy.
(= (applyHeartbeat $periphery $now $due)
   (if $due
       (let $refuelled
            (py-call (fuel_modes.refuel
                       (loop-budget $periphery)
                       (policy-burst-budget (loop-active-policy $periphery))))
         (progn
           (println! (HEARTBEAT_REARM at (get_time_as_string)
                      fuel (py-call (fuel_modes.current_fuel))
                      loops $refuelled))
           (println! (py-call (goals.kernel_pass)))
           (coordinate-set last-heartbeat $now
             (coordinate-set sleep-interval (sleepInterval)
               (coordinate-set loops $refuelled $periphery)))))
       $periphery))

(= (applyHumanActivity $periphery $has-activity $is-human)
   (if (and $has-activity $is-human)
       (let $armed
            (max (loop-budget $periphery)
                 (py-call (telegram.lastMessageArmLoops)))
            (progn
              (println! (py-call (goals.kernel_pass)))
              (coordinate-set last-heartbeat (get_time)
                (coordinate-set sleep-interval
                  (if (> $armed 0) (sleepInterval) 60)
                  (coordinate-set loops $armed $periphery)))))
       $periphery))

;; Rest banks the budget instead of spending it. The skill can only post a
;; directive; only the loop can read how much life is actually left, so the
;; transfer happens here, at the end of the turn that asked to rest.
(= (applyRestBanking $periphery)
   (if (== (coordinate-get-or rest-request 0 $periphery) 1)
       (coordinate-set rest-request 0
         (coordinate-set banked-loops (loop-budget $periphery)
           (coordinate-set loops 0 $periphery)))
       $periphery))

;; Waking hands the banked budget back, however the rest ended — timer,
;; operator message or /wake — and returns idle pacing to normal. Taking the
;; maximum keeps a timer continuation's own allowance when one fired.
(= (applyRestRestore $periphery)
   (let $banked (coordinate-get-or banked-loops 0 $periphery)
     (if (> $banked 0)
         (coordinate-set banked-loops 0
           (coordinate-set sleep-interval (sleepInterval)
             (coordinate-set loops (max (loop-budget $periphery) $banked)
                             $periphery)))
         $periphery)))

(= (applyAutonomousBurst $periphery $autonomous)
   (if $autonomous
       (let $refuelled
            (py-call (fuel_modes.refuel
                       (loop-budget $periphery)
                       (policy-burst-budget (loop-active-policy $periphery))))
         (progn
           (println! (AUTONOMOUS_POLICY_BURST
                       policy (loop-active-policy $periphery)
                       at (get_time_as_string)
                       loops $refuelled))
           (coordinate-set sleep-interval (sleepInterval)
             (coordinate-set loops $refuelled $periphery))))
       $periphery))

;; One model-and-tools episode.  It returns a candidate periphery; rest and nop
;; contribute ordinary policy directives rather than mutating the runner.
(= (cognitiveTurn $periphery $message $has-activity $is-human
                  $autonomous $heartbeat)
   (let* (($iteration (loop-iteration $periphery))
          ($lastmessage
            (if $autonomous
                (AUTONOMOUS_BURST: TASK_COMPLETE_PICK_A_GOAL_OR_CONSOLIDATE_MEMORY DO_NOT_REPEAT_PRIOR_SENDS)
                (NEW_ACTIVITY: $message)))
          ($source
            (if $autonomous autonomous-trigger
                (if $has-activity
                    (if $is-human operator-event channel-event)
                    (if $heartbeat heartbeat-event continuation-tick))))
          ($priorResults (loop-last-results $periphery))
          ($_ (loop-directives-clear))
          ($_ (eval (attention-begin $iteration $source
                    (== (py-call (helper.text_nonempty $priorResults)) 1))))
          ($_ (addition-effect-turn-begin $iteration))
          ($prompt (getContext $periphery))
          ($structuredSystem
            (string-safe
              (py-str ((getContextPrefix) (getContextSuffix $periphery)))))
          ($advertised (string-safe (py-str (getSkills))))
          ($_ (println! $lastmessage))
          ($legacySend (py-str ($prompt $lastmessage)))
          ($request
            (addition-prepare-request
              (loop-active-policy $periphery) $legacySend
              $structuredSystem (string-safe (py-str $lastmessage))
              $advertised))
          ($requestObservations (coding-request-observations $request))
          ($_ (if (== $requestObservations "") _
                  (println! $requestObservations)))
          ($send (coding-request-prompt $request))
          ($_ (println! (CHARS_SENT: (string_length $send) $send)))
          ($rmode (policy-reasoning (loop-active-policy $periphery)
                                    (reasoningMode)))
          ($respi (addition-model-call
                    (LLM) (maxOutputToken) $rmode $send))
          ;; The external observation is committed before parse recovery.
          ($_ (cut))
          ($resp (addition-balance-response $respi))
          ($response (addition-envelope-response $resp))
          ($_ (if (== $response $resp) _ (println! $resp)))
          ($parsed (addition-read-response $response))
          ($_ (change-state! &error ()))
          ($_ (HandleError multi_command_parse_error_nothing_ran
                          $response $parsed))
          ($sexpr (addition-command-sequence $parsed))
          ;; Inspect only the outer list shape before the effect boundary.
          ;; Passing the command value itself through a later `eval` would
          ;; reduce grounded skills even when the broker withheld them.
          ($parseOutcome
            (if (== $sexpr ()) no-commands commands-parsed))
          ($_ (println! (RESPONSE: $sexpr)))
          ($_ (cut))
          ;; The explicit quote keeps grounded commands inert until the
          ;; deterministic dispatcher receives them.
          ($commandResults
            (addition-effect-broker
              $iteration
              (policy-command-batch-limit (loop-active-policy $periphery))
              (quote $sexpr)))
          ($_ (change-state! &error
                (append (get-state &error)
                        (command-batch-errors $iteration))))
          ($results (RESULTS: $commandResults))
          ($_ (eval (attention-complete $iteration $parseOutcome)))
          ($_ (println! $results))
          ($_ (if (or $has-activity (not (== $sexpr ())))
                  (addToHistory $message $response $has-activity)
                  _))
          ($feedback
            (if (== $requestObservations "")
                (string-safe (repr $results))
                (string-safe
                  (py-str ($requestObservations " " (repr $results))))))
          ($withResults
            (coordinate-set last-results $feedback $periphery))
          ($directed (loop-directives-apply $withResults))
          ($banked (applyRestBanking $directed))
          ($_ (loop-directives-clear))
          ;; A model/effect episode has exactly one committed successor.  The
          ;; final cut prevents a bridge predicate's residual choice point
          ;; from replaying the same pure candidate after effects completed.
          ($_ (cut)))
     $banked))

;; The policy process computes freely.  Only this wrapper converts its result
;; to the kernel's success/failure vocabulary.
(= (enabledTurnCandidate $periphery)
   (let* (($iteration (loop-iteration $periphery))
          ($selected (py-call (loop_modes.current_mode)))
          ($selectedPeriphery
            (coordinate-set active-policy $selected
              (coordinate-set autonomous-ready 0 $periphery)))
          ($decremented
            (if (== $iteration 1)
                $selectedPeriphery
                (coordinate-set loops
                  (max 0 (- (loop-budget $selectedPeriphery) 1))
                  $selectedPeriphery)))
          ($message (eval (receive)))
          ($hasActivity
            (== (py-call (helper.text_nonempty $message)) 1))
          ($isHuman (eval (lastMessageIsHuman)))
          ($humanApplied
            (applyHumanActivity $decremented $hasActivity $isHuman))
          ($now (get_time))
          ($heartbeat (heartbeatDue $humanApplied $now))
          ($heartbeatApplied
            (applyHeartbeat $humanApplied $now $heartbeat))
          ($autonomous
            (policy-autonomous-turn
              (loop-active-policy $heartbeatApplied)
              (loop-autonomous-ready $periphery)
              $hasActivity
              (loop-resting $heartbeatApplied)))
          ($ready (applyAutonomousBurst $heartbeatApplied $autonomous))
          ($_ (if (> (loop-budget $ready) 0)
                  (py-call (cognitive_health.expect_turn
                             (loop-active-policy $ready)
                             (loop-budget $ready)))
                  _))
          ($afterTurn
            (if (> (loop-budget $ready) 0)
                (cognitiveTurn $ready $message $hasActivity $isHuman
                               $autonomous $heartbeat)
                $ready))
          ($next
            (coordinate-set iteration (+ 1 $iteration) $afterTurn)))
     (candidate $next)))

;; Operator authority is an outer lifecycle addition, not a policy encoded in
;; the two-equation transformation kernel.  A stopped process keeps only its
;; Telegram control plane alive and cannot drain activity or call the model.
(= (turnCandidate $periphery)
   (if (== (py-call (lifecycle.cognition_enabled)) 1)
       (enabledTurnCandidate $periphery)
       (candidate
         (coordinate-set autonomous-ready 0
           (coordinate-set loops 0 $periphery)))))

(= (protectedOutcome $trial)
   (case $trial
     (((candidate $next) (success $next))
      ((Error $expression $exception)
       (progn
         (println! (PROCESS_FAILURE $expression $exception))
         failure))
      ($unexpected
       (progn
         (println! (PROCESS_MALFORMED_OUTCOME $unexpected))
         failure)))))

(= (turnProcess $periphery)
   (protectedOutcome (catch (turnCandidate $periphery))))

;; A timed rest continuation is code-as-data until the timer expires.  It runs
;; directly, without spending a model call, and its result becomes context for
;; exactly one ordinary follow-up turn.  The budget is 2 because turnCandidate
;; performs its normal boundary decrement before deciding whether to think.
(= (runRestContinuation $periphery
                        (continuation-value $continuation))
   (let* (($iteration (loop-iteration $periphery))
          ;; Cognitive turns use positive iteration ids.  Their negative
          ;; counterpart is a distinct scalar key for the timer continuation;
          ;; unlike a compound marker it cannot be eagerly reduced away while
          ;; crossing the MeTTa/Prolog call boundary.
          ($turn (- 0 $iteration))
          ($_ (addition-effect-turn-begin $turn))
          ($records
            (run-command-batch-once $turn
              (policy-command-batch-limit
                (loop-active-policy $periphery))
              (quote ($continuation))))
          ($results (CONTINUATION_RESULTS: $records))
          ($_ (println! $results)))
     (coordinate-set pending-continuation no-continuation
       (coordinate-set loops 2
         (coordinate-set last-results (string-safe (repr $results))
                         $periphery)))))

(= (applyTimedContinuation $periphery $timedOut)
   (let $pending (loop-pending-continuation $periphery)
     (if (and (== $timedOut 1)
              (not (== $pending no-continuation)))
         (runRestContinuation $periphery $pending)
         $periphery)))

;; Waiting is another replaceable process.  Channel polling remains in its
;; adapter; only the resulting readiness bit enters the periphery.
(= (waitCandidate $periphery)
   (let* (($policy (loop-active-policy $periphery))
          ($enabled (== (py-call (lifecycle.cognition_enabled)) 1))
          ($loops (loop-budget $periphery))
          ($paused (loop-resting $periphery))
          ($wait
            (if $enabled
                (policy-wait-seconds $policy $loops
                                     (loop-sleep $periphery) $paused)
                60))
          ($waitResult (py-call (telegram.sleep_until_message $wait)))
          ($timedOut (py-call (loop_modes.wait_timed_out $waitResult)))
          ($continued
            (if $enabled
                (applyTimedContinuation $periphery $timedOut)
                $periphery))
          ($restored (applyRestRestore $continued))
          ($continuedLoops (loop-budget $restored))
          ($ready
            (if $enabled
                (policy-next-autonomous-ready
                  $policy $continuedLoops $timedOut $paused)
                0)))
     (candidate (coordinate-set autonomous-ready $ready $restored))))

(= (waitProcess $periphery)
   (protectedOutcome (catch (waitCandidate $periphery))))

(= (persistProcessState $state)
   (let $periphery (process-periphery $state)
     (py-call
       (helper.working_set_save
         (loop-budget $periphery)
         (loop-sleep $periphery)
         (loop-last-results $periphery)
         (loop-last-heartbeat $periphery)
         (if (== (loop-pending-continuation $periphery)
                 no-continuation) 0 1)
         (coordinate-get-or banked-loops 0 $periphery)))))

(= (processLoop $state)
   (let* (($periphery (process-periphery $state))
          ($_ (println! (---------iteration (loop-iteration $periphery))))
          ($outcome (turnProcess $periphery))
          ($next (process-step $state $outcome))
          ($_ (persistProcessState $next)))
     (if (== (py-call (helper.recycle_requested)) 1)
         (progn
           (println! (RECYCLE_AT_TURN_BOUNDARY
                       iteration
                       (loop-iteration (process-periphery $next))))
           (py-call (helper.recycle_exit)))
         (let* (($waitOutcome (waitProcess (process-periphery $next)))
                ($waiting (process-step $next $waitOutcome))
                ($_ (persistProcessState $waiting)))
           (processLoop $waiting)))))

(= (mettaclaw)
   (progn
     (initMemory)
     (initChannels)
     (println! (py-call (goals.kernel_pass)))
     (processLoop (initLoop))))
