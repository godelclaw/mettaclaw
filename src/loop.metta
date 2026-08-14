(= (maxLoops) (empty))
(= (sleepInterval) (empty))
(= (LLM) (empty))
(= (maxOutputToken) (empty))
(= (reasoningMode) (empty))

(= (initLoop)
   (progn (py-call (helper.recycle_ack)) ;new process consumes the boundary flag
          (py-call (helper.working_boot)) ;continuity: load the present-moment snapshot
          (configure maxLoops 50) ;20
          (configure sleepInterval 1) ;10
          (configure LLM syn:large:text)
          (configure maxOutputToken 32768) ;the 2026-07 swipl crashes were the frozen chroma HNSW index (fixed by sync_threshold), NOT this ceiling; 6000 starved reasoning models into empty answers
          (configure reasoningMode medium)
          (change-state! &prevmsg "")
          ;; PresentMoment.restore: wake with the working self intact —
          ;; a recycle or restart is sleep, not a fresh boot. First-ever
          ;; boot (no snapshot) keeps the fresh-start values below.
          (change-state! &lastresults (py-call (helper.boot_str "lastresults" "")))
          (change-state! &sleepInterval (py-call (helper.boot_int "sleepInterval" (sleepInterval))))
          (change-state! &loops (py-call (helper.boot_int "loops" (maxLoops))))
          (change-state! &last-heartbeat (py-call (helper.boot_num "last_heartbeat" (get_time))))))

;; Heartbeat (optional): when the loop wakes and this clock is stale, re-arm a
;; fresh (maxLoops)-cycle burst. Human messages reset the clock, so the timer is
;; measured from the last human-armed turn. 1800 s = 30 min; 0 disables it.
;; Overridable via METTACLAW_HEARTBEAT_INTERVAL_SECONDS (tests shrink it).
(= (heartbeatInterval) (py-call (helper.int_env "METTACLAW_HEARTBEAT_INTERVAL_SECONDS" 1800)))

(= (maybeHeartbeat)
   (if (or (<= (heartbeatInterval) 0)
           (== (py-call (loop_modes.autonomy_paused)) 1))
       _
       (let $now (get_time)
            (if (>= (- $now (get-state &last-heartbeat)) (heartbeatInterval))
                (progn (println! (HEARTBEAT_REARM at (get_time_as_string) loops (maxLoops)))
                       (change-state! &loops (maxLoops))
                       (change-state! &sleepInterval (sleepInterval))
                       (change-state! &last-heartbeat $now)
                       (println! (py-call (goals.kernel_pass))))
                _))))

;; Static context (prompt, skills, format) leads and dynamic fields trail so an
;; exact-prefix provider cache can reuse the unchanging head across turns.
(= (getContext)
   (string-safe (py-str ("PROMPT: " (getPrompt) " SKILLS: " (getSkills)
                         " OUTPUT_FORMAT: Output a ((skillName1 args1) (skillName2 args2) (skillName3 args3) (skillName4 args4) (skillName5 args5)) S-expression of up to 5 sexpr commands, double-check the parentheses it must be (cmd1 ... cmdn)! Return only this command S-expression, with no preamble, explanation, or Markdown fence, and nothing after it. Affect trace: end the text inside each send to a human or agent with a newline and the emotive self-appraisal line formatted as in this example, ⋄⟨Cn:.5 C:.7 Ct:.8 I:.2 J:.6 A:.4 S:.6 Co:-.42 Sp:.3⟩, values ∈ [-1,1]. Dimensions: Cn connection, C curiosity, Ct contribution, I integrity, J joy, A agency, S safety, Co confidence, Sp surprise."
                         " each arg is an explicit string hence needs quotes, and variables are forbidden!"
                         " HISTORY: " (getHistory)
                         " LOOPS_LEFT: " (get-state &loops)
                         " SLEEP_INTERVAL_SECONDS: " (get-state &sleepInterval)
                         " ACTIVE_MODE: " (py-call (loop_modes.current_mode))
                         " ACTIVE_MODEL: " (py-call (synthetic_llm.current_model))
                         " RECENT_ACTIVITY: " (py-call (telegram.recent_activity 8))
                         " GOAL_STACK: " (py-call (goals.goals_view))
                         " PINNED: " (py-call (pins.view))
                         " LAST_SKILL_USE_RESULTS: " (last_chars (get-state &lastresults) (maxFeedback)) " TIME: " (get_time_as_string)))))

(= (HandleError $msg $cmd $sexpr)
   (case $sexpr (((Error $a $b) (let $new (append (get-state &error) (($msg $cmd)))
                                          (change-state! &error $new)))
                 ($else $sexpr))))

(= (mettaclaw)
   (mettaclaw 1 0))
(= (mettaclaw $k $autonomousReady)
   (progn (if (== $k 1) (progn (initLoop)
                               (initMemory)
                               (initChannels)
                               (println! (py-call (goals.kernel_pass))))
                        (change-state! &loops (max 0 (- (get-state &loops) 1))))
         (progn (println! (---------iteration $k))
                (let* (($msg (string-safe (repr (receive))))
                       ($msgnew (> (string_length $msg) 0))
                       ($humanmsg (lastMessageIsHuman))
                       ($_ (if $msgnew
                               (if $humanmsg
                                   (progn (py-call (loop_modes.resume_autonomy))
                                          (change-state! &loops
                                            ;; per-sender energy tier: full 50 /
                                            ;; mid 30 / light 10 (see /energy).
                                            ;; max: a message only ADDS energy —
                                            ;; it never drains what the agent holds
                                            (max (get-state &loops)
                                                 (py-call (telegram.lastMessageArmLoops))))
                                          (change-state! &sleepInterval (if (> (get-state &loops) 0) (sleepInterval) 60))
                                          (change-state! &last-heartbeat (get_time))
                                          (println! (py-call (goals.kernel_pass))))
                                   _)
                               _))
                       ($_hb (maybeHeartbeat))
                       ($mode (py-call (loop_modes.current_mode)))
                       ($autonomous (and (and (== $mode (quote claw23))
                                               (== $autonomousReady 1))
                                          (and (not $msgnew)
                                               (== (py-call (loop_modes.autonomy_paused)) 0))))
                       ($_auto (if $autonomous
                                  (progn (change-state! &loops (maxLoops))
                                         (change-state! &sleepInterval (sleepInterval))
                                         (println! (CLAW23_AUTONOMOUS_BURST at (get_time_as_string))))
                                  _)))
                       ;; Record the obligation before the governance gate: a
                       ;; live loop whose gate never admits a model call is a
                       ;; cognitive stall, not a healthy idle process.
                       ($_expect (if (> (get-state &loops) 0)
                                    (py-call (cognitive_health.expect_turn $mode))
                                    _)))
                      (if (and (> (get-state &loops) 0) (== (py-call (ggb_bridge_ext.ggbGovernanceGate tick)) (quote PASS)))
                          (let* (($prompt (getContext))
                                 ($lastmessage (if $autonomous
                                                   (AUTONOMOUS_BURST: TASK_COMPLETE_PICK_A_GOAL_OR_CONSOLIDATE_MEMORY DO_NOT_REPEAT_PRIOR_SENDS)
                                                   (NEW_ACTIVITY: $msg)))
                                 ($_ (println! $lastmessage))
                                 ($send (py-str ($prompt $lastmessage)))
                                 ($_ (println! (CHARS_SENT: (string_length $send) $send)))
                                 ($rmode (py-call (loop_modes.reasoning_mode (reasoningMode))))
                                 ($respi (py-call (synthetic_llm.chat (LLM) (maxOutputToken) $rmode $send)))
                                 ($resp (py-call (helper.balance_parentheses $respi)))
                                 ($response (if (== "(" (first_char $resp)) $resp (progn (println! $resp) (repr (no_commands_parsed)))))
                                 ($sexpr (catch (sread (py-call (helper.decode_safe_text $response)))))
                                 ($_ (change-state! &error ()))
                                 ($_ (HandleError multi_command_parse_error_nothing_ran $response $sexpr))
                                 ($_ (println! (RESPONSE: $sexpr)))
                                 ($results (RESULTS: (collapse (let $s (superpose $sexpr) (COMMAND_RETURN: ($s (HandleError command_format_error_nothing_ran $s (catch (let $result (eval $s) (py-call (helper.normalize_string $result)))))))))))
                                 ($_ (println! $results)))
                                (progn (if (or $msgnew  (not (== $sexpr ()))) (addToHistory $msg $response $sexpr $msgnew) _)
                                       (change-state! &lastresults (string-safe (repr $results))))) _))
                ;; PresentMoment.persist: snapshot the working self at every
                ;; turn boundary — the write half of the continuity invariant.
                (py-call (helper.working_set_save (get-state &loops) (get-state &sleepInterval) (get-state &lastresults) (get-state &last-heartbeat)))
                ;; Recycling is cooperative: finish the current turn and its
                ;; bookkeeping, then exit the PROCESS so the service manager
                ;; starts a fresh heap. The exit must be a hard process exit:
                ;; merely returning from the recursion lands in engine
                ;; backtracking, which re-enters the loop from scratch in the
                ;; same process and re-arms a fresh budget every cycle (the
                ;; 2026-08-06 boot-loop storm). The new process consumes the
                ;; flag at boot (helper.recycle_ack in initLoop).
                (if (== (py-call (helper.recycle_requested)) 1)
                    (progn (println! (RECYCLE_AT_TURN_BOUNDARY iteration $k))
                           (py-call (helper.recycle_exit)))
                    (progn
                      (let $wait (py-call (loop_modes.wait_seconds (get-state &loops) (get-state &sleepInterval)))
                           (let $waitResult (py-call (telegram.sleep_until_message $wait))
                                (mettaclaw (+ 1 $k)
                                           (py-call (loop_modes.autonomous_ready (get-state &loops) $waitResult))))))))))
