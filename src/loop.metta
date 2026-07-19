(= (maxLoops) (empty))
(= (sleepInterval) (empty))
(= (LLM) (empty))
(= (maxOutputToken) (empty))
(= (reasoningMode) (empty))

(= (initLoop)
   (progn (configure maxLoops 50) ;20
          (configure sleepInterval 1) ;10
          (configure LLM syn:large:text)
          (configure maxOutputToken 6000)
          (configure reasoningMode medium)
          (change-state! &prevmsg "")
          (change-state! &lastresults "")
          (change-state! &sleepInterval (sleepInterval))
          (change-state! &loops (maxLoops))
          (change-state! &last-heartbeat (get_time))))

;; Heartbeat (optional): when the loop wakes and this clock is stale, re-arm a
;; fresh (maxLoops)-cycle burst. Human messages reset the clock, so the timer is
;; measured from the last human-armed turn. 1800 s = 30 min; 0 disables it.
;; Overridable via METTACLAW_HEARTBEAT_INTERVAL_SECONDS (tests shrink it).
(= (heartbeatInterval) (py-call (helper.int_env "METTACLAW_HEARTBEAT_INTERVAL_SECONDS" 1800)))

(= (maybeHeartbeat)
   (if (<= (heartbeatInterval) 0)
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
                         " OUTPUT_FORMAT: Output a ((skillName1 args1) (skillName2 args2) (skillName3 args3) (skillName4 args4) (skillName5 args5)) S-expression of up to 5 sexpr commands, double-check the parentheses it must be (cmd1 ... cmdn)! Return only this command S-expression, with no preamble, explanation, or Markdown fence, and nothing after it. Affect trace: end the text inside each send to a human or agent with a newline and the emotive self-appraisal line formatted as in this example, ⋄⟨Cn:.5 C:.7 Ct:.8 I:.2 J:.6 A:.4 S:.6 Co:-.42⟩, values ∈ [-1,1]. Dimensions: Cn connection, C curiosity, Ct contribution, I integrity, J joy, A agency, S safety, Co confidence."
                         " each arg is an explicit string hence needs quotes, and variables are forbidden!"
                         " HISTORY: " (getHistory)
                         " LOOPS_LEFT: " (get-state &loops)
                         " SLEEP_INTERVAL_SECONDS: " (get-state &sleepInterval)
                         " ACTIVE_MODEL: " (py-call (synthetic_llm.current_model))
                         " RECENT_ACTIVITY: " (py-call (telegram.recent_activity 8))
                         " GOAL_STACK: " (py-call (goals.goals_view))
                         " LAST_SKILL_USE_RESULTS: " (last_chars (get-state &lastresults) (maxFeedback)) " TIME: " (get_time_as_string)))))

(= (HandleError $msg $cmd $sexpr)
   (case $sexpr (((Error $a $b) (let $new (append (get-state &error) (($msg $cmd)))
                                          (change-state! &error $new)))
                 ($else $sexpr))))

(= (mettaclaw)
   (mettaclaw 1))
(= (mettaclaw $k)
   (progn (if (== $k 1) (progn (initLoop)
                               (initMemory)
                               (initChannels)
                               (println! (py-call (goals.kernel_pass))))
                        (change-state! &loops (max 0 (- (get-state &loops) 1))))
         (progn (println! (---------iteration $k))
                (let* (($msg (string-safe (repr (receive))))
                       ($msgnew (prog1 (!= $msg (get-state &prevmsg))
                                       (change-state! &prevmsg $msg)))
                       ($humanmsg (lastMessageIsHuman))
                       ($_ (if $msgnew
                               (if $humanmsg
                                   (progn (change-state! &loops (maxLoops))
                                          (change-state! &sleepInterval (sleepInterval))
                                          (change-state! &last-heartbeat (get_time))
                                          (println! (py-call (goals.kernel_pass))))
                                   _)
                               _))
                       ($_hb (maybeHeartbeat)))
                      (if (> (get-state &loops) 0)
                          (let* (($prompt (getContext))
                                 ($lastmessage (HUMAN-LAST-MSG: $msg
                                               MESSAGE-IS-NEW: $msgnew
                                               HUMAN-MESSAGE-ARMS-LOOP: $humanmsg))
                                 ($_ (println! $lastmessage))
                                 ($send (py-str ($prompt $lastmessage)))
                                 ($_ (println! (CHARS_SENT: (string_length $send) $send)))
                                 ($respi (py-call (synthetic_llm.chat (LLM) (maxOutputToken) (reasoningMode) $send)))
                                 ($resp (py-call (helper.balance_parentheses (py-call (helper.strip_trailing_affect $respi)))))
                                 ($response (if (== "(" (first_char $resp)) $resp (progn (println! $resp) (repr (REMEMBER:OUTPUT_NOTHING_ELSE_THAN: ((skill arg) ...))))))
                                 ($sexpr (catch (sread (py-call (helper.decode_safe_text $response)))))
                                 ($_ (change-state! &error ()))
                                 ($_ (HandleError MULTI_COMMAND_FAILURE_NOTHING_WAS_DONE_PLEASE_CORRECT_PARENTHESES_AND_RETRY $response $sexpr))
                                 ($_ (println! (RESPONSE: $sexpr)))
                                 ($results (RESULTS: (collapse (let $s (superpose $sexpr) (COMMAND_RETURN: ($s (HandleError SINGLE_COMMAND_FORMAT_ERROR_NOTHING_WAS_DONE_PLEASE_FIX_AND_RETRY $s (catch (let $result (eval $s) (py-call (helper.normalize_string $result)))))))))))
                                 ($_ (println! $results)))
                                (progn (if (or $msgnew  (not (== $sexpr ()))) (addToHistory $msg $response $sexpr $msgnew) _)
                                       (change-state! &lastresults (string-safe (repr $results))))) _))
                ;; Recycling is cooperative: finish the current turn and its
                ;; bookkeeping, then let the service manager start a fresh
                ;; heap. The request flag is cleared only by the new process.
                (if (== (py-call (helper.recycle_requested)) 1)
                    (println! (RECYCLE_AT_TURN_BOUNDARY iteration $k))
                    (progn
                      (sleep (get-state &sleepInterval))
                      (mettaclaw (+ 1 $k)))))))
