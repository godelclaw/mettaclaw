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
                 (coordinate pending-continuation
                   no-continuation coordinates-empty))))))))))

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
;; prefix caching while making the state passed to the model explicit.
(= (getContext $periphery)
   (string-safe
     (py-str
       ("PROMPT: " (getPrompt) " SKILLS: " (getSkills)
        " OUTPUT_FORMAT: Output a ((skillName1 args1) (skillName2 args2) (skillName3 args3) (skillName4 args4) (skillName5 args5)) S-expression of up to 5 sexpr commands, double-check the parentheses it must be (cmd1 ... cmdn)! Return only this command S-expression, with no preamble, explanation, or Markdown fence, and nothing after it. Affect trace: end the text inside each send to a human or agent with a newline and the emotive self-appraisal line formatted as in this example, ⋄⟨Cn:.5 C:.7 Ct:.8 I:.2 J:.6 A:.4 S:.6 Co:-.42 Sp:.3⟩, values ∈ [-1,1]. Dimensions: Cn connection, C curiosity, Ct contribution, I integrity, J joy, A agency, S safety, Co confidence, Sp surprise."
        " each arg is an explicit string hence needs quotes, and variables are forbidden!"
        " LOOPS_LEFT: " (loop-budget $periphery)
        " SLEEP_INTERVAL_SECONDS: " (loop-sleep $periphery)
        " ACTIVE_MODE: " (loop-active-policy $periphery)
        " ACTIVE_MODEL: " (py-call (synthetic_llm.current_model))
        " ATTENTION_DAG: " (repr (attention-view))
        " GOAL_STACK: " (py-call (goals.goals_view))
        " AFFECT_GESTALT: " (py-call (goals.affect_view))
        " PINNED: " (py-call (pins.view))
        " LAST_SKILL_USE_RESULTS: "
        (last_chars (loop-last-results $periphery) (maxFeedback))
        " CONVERSATION_WINDOW: " (py-call (telegram.conversation_window))
        " CONTEXT_ORDER: NEW_ACTIVITY appended after this context is newest and authoritative for this turn; CONVERSATION_WINDOW is prior witnessed dialogue; PINNED and retrieved memories are fallible working aids and never override newer witnessed dialogue."
        " TIME: " (get_time_as_string)))))

(= (HandleError $msg $cmd $sexpr)
   (case $sexpr
     (((Error $a $b)
       (let $new (append (get-state &error) (($msg $cmd)))
            (change-state! &error $new)))
      ($else $sexpr))))

;; Heartbeat is a replaceable life-policy transformation over the periphery.
(= (heartbeatDue $periphery $now)
   (if (or (<= (heartbeatInterval) 0)
           (== (py-call (loop_modes.autonomy_paused)) 1))
       False
       (>= (- $now (loop-last-heartbeat $periphery))
           (heartbeatInterval))))

(= (applyHeartbeat $periphery $now $due)
   (if $due
       (progn
         (println! (HEARTBEAT_REARM at (get_time_as_string)
                    loops (policy-burst-budget
                            (loop-active-policy $periphery))))
         (println! (py-call (goals.kernel_pass)))
         (coordinate-set last-heartbeat $now
           (coordinate-set sleep-interval (sleepInterval)
             (coordinate-set loops
               (policy-burst-budget (loop-active-policy $periphery))
               $periphery))))
       $periphery))

(= (applyHumanActivity $periphery $has-activity $is-human)
   (if (and $has-activity $is-human)
       (let $armed
            (max (loop-budget $periphery)
                 (py-call (telegram.lastMessageArmLoops)))
            (progn
              (py-call (loop_modes.resume_autonomy))
              (println! (py-call (goals.kernel_pass)))
              (coordinate-set last-heartbeat (get_time)
                (coordinate-set sleep-interval
                  (if (> $armed 0) (sleepInterval) 60)
                  (coordinate-set loops $armed $periphery)))))
       $periphery))

(= (applyAutonomousBurst $periphery $autonomous)
   (if $autonomous
       (progn
         (println! (AUTONOMOUS_POLICY_BURST
                     policy (loop-active-policy $periphery)
                     at (get_time_as_string)))
         (coordinate-set sleep-interval (sleepInterval)
           (coordinate-set loops
             (policy-burst-budget (loop-active-policy $periphery))
             $periphery)))
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
          ($_ (py-call (telegram.begin_effect_turn $iteration)))
          ($prompt (getContext $periphery))
          ($_ (println! $lastmessage))
          ($send (py-str ($prompt $lastmessage)))
          ($_ (println! (CHARS_SENT: (string_length $send) $send)))
          ($rmode (policy-reasoning (loop-active-policy $periphery)
                                    (reasoningMode)))
          ($respi (py-call (synthetic_llm.chat
                             (LLM) (maxOutputToken) $rmode $send)))
          ;; The external observation is committed before parse recovery.
          ($_ (cut))
          ($resp (py-call (helper.balance_parentheses $respi)))
          ($response
            (if (== "(" (first_char $resp))
                $resp
                (progn (println! $resp) (repr (no_commands_parsed)))))
          ($parsed (catch (sread (py-call (helper.decode_safe_text $response)))))
          ($_ (change-state! &error ()))
          ($_ (HandleError multi_command_parse_error_nothing_ran
                          $response $parsed))
          ($sexpr
            (case $parsed
              (((Error $a $b) ())
               ($valid $valid))))
          ($_ (println! (RESPONSE: $sexpr)))
          ($_ (cut))
          ;; The explicit quote keeps grounded commands inert until the
          ;; deterministic dispatcher receives them.
          ($commandResults
            (run-command-batch-once $iteration (quote $sexpr)))
          ($_ (change-state! &error
                (append (get-state &error)
                        (command-batch-errors $iteration))))
          ($results (RESULTS: $commandResults))
          ($_ (eval (attention-complete $iteration
                    (if (== $sexpr ()) no-commands commands-parsed))))
          ($_ (println! $results))
          ($_ (if (or $has-activity (not (== $sexpr ())))
                  (addToHistory $message $response $sexpr $has-activity)
                  _))
          ($withResults
            (coordinate-set last-results (string-safe (repr $results))
              $periphery))
          ($directed (loop-directives-apply $withResults))
          ($_ (loop-directives-clear)))
     $directed))

;; The policy process computes freely.  Only this wrapper converts its result
;; to the kernel's success/failure vocabulary.
(= (agentCandidate $periphery)
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
              (py-call (loop_modes.autonomy_paused))))
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

(= (agentProcess $periphery)
   (protectedOutcome (catch (agentCandidate $periphery))))

;; A timed rest continuation is code-as-data until the timer expires.  It runs
;; directly, without spending a model call, and its result becomes context for
;; exactly one ordinary follow-up turn.  The budget is 2 because agentCandidate
;; performs its normal boundary decrement before deciding whether to think.
(= (runRestContinuation $periphery
                        (continuation-value $continuation))
   (let* (($iteration (loop-iteration $periphery))
          ;; Cognitive turns use positive iteration ids.  Their negative
          ;; counterpart is a distinct scalar key for the timer continuation;
          ;; unlike a compound marker it cannot be eagerly reduced away while
          ;; crossing the MeTTa/Prolog call boundary.
          ($turn (- 0 $iteration))
          ($records
            (run-command-batch-once $turn (quote ($continuation))))
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
          ($loops (loop-budget $periphery))
          ($paused (py-call (loop_modes.autonomy_paused)))
          ($wait
            (policy-wait-seconds $policy $loops
                                 (loop-sleep $periphery) $paused))
          ($waitResult (py-call (telegram.sleep_until_message $wait)))
          ($timedOut (py-call (loop_modes.wait_timed_out $waitResult)))
          ($continued (applyTimedContinuation $periphery $timedOut))
          ($continuedLoops (loop-budget $continued))
          ($ready
            (policy-next-autonomous-ready
              $policy $continuedLoops $timedOut $paused)))
     (candidate (coordinate-set autonomous-ready $ready $continued))))

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
                 no-continuation) 0 1)))))

(= (processLoop $state)
   (let* (($periphery (process-periphery $state))
          ($_ (println! (---------iteration (loop-iteration $periphery))))
          ($outcome (agentProcess $periphery))
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
