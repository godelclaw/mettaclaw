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
          (change-state! &loops (maxLoops))))

(= (getContext)
   (string-safe (py-str ("PROMPT: " (getPrompt) " SKILLS: " (getSkills)
                         " LOOPS_LEFT: " (get-state &loops)
                         " SLEEP_INTERVAL_SECONDS: " (get-state &sleepInterval)
                         " OUTPUT_FORMAT: Output a ((skillName1 args1) (skillName2 args2) (skillName3 args3) (skillName4 args4) (skillName5 args5)) S-expression of up to 5 sexpr commands, double-check the parentheses it must me (cmd1 ... cmdn)!"
                         " each arg is an explicit string hence needs quotes, and variables are forbidden!"
                         " LAST_SKILL_USE_RESULTS: " (last_chars (get-state &lastresults) (maxFeedback)) " HISTORY: " (getHistory) " TIME: " (get_time_as_string)))))

(= (HandleError $msg $cmd $sexpr)
   (case $sexpr (((Error $a $b) (let $new (append (get-state &error) (($msg $cmd)))
                                          (change-state! &error $new)))
                 ($else $sexpr))))

(= (mettaclaw)
   (mettaclaw 1))
(= (mettaclaw $k)
   (progn (if (== $k 1) (progn (initLoop)
                               (initMemory)
                               (initChannels))
                        (change-state! &loops (max 0 (- (get-state &loops) 1))))
          (let $prompt (getContext)
               (progn (println! (---------iteration $k))
                      (let* (($msg (string-safe (repr (receive))))
                             ($msgnew (prog1 (!= $msg (get-state &prevmsg))
                                             (change-state! &prevmsg $msg)))
                             ($humanmsg (lastMessageIsHuman))
                             ($_ (if $msgnew
                                     (if $humanmsg
                                         (progn (change-state! &loops (maxLoops))
                                                (change-state! &sleepInterval (sleepInterval)))
                                         _)
                                     _)))
                            (if (> (get-state &loops) 0)
                                (let* (($lastmessage (HUMAN-LAST-MSG: $msg
                                                      MESSAGE-IS-NEW: $msgnew
                                                      HUMAN-MESSAGE-ARMS-LOOP: $humanmsg))
                                       ($_ (println! $lastmessage))
                                       ($send (py-str ($prompt $lastmessage)))
                                       ($_ (println! (CHARS_SENT: (string_length $send) $send)))
                                       ($respi (py-call (synthetic_llm.chat (LLM) (maxOutputToken) (reasoningMode) $send)))
                                       ($resp (py-call (helper.balance_parentheses $respi)))
                                       ($response (if (== "(" (first_char $resp)) $resp (progn (println! $resp) (repr (REMEMBER:OUTPUT_NOTHING_ELSE_THAN: ((skill arg) ...))))))
                                       ($sexpr (catch (sread $response)))
                                       ($_ (change-state! &error ()))
                                       ($_ (HandleError MULTI_COMMAND_FAILURE_NOTHING_WAS_DONE_PLEASE_CORRECT_PARENTHESES_AND_RETRY $response $sexpr))
                                       ($_ (println! (RESPONSE: $sexpr)))
                                       ($results (RESULTS: (collapse (let $s (superpose $sexpr) (COMMAND_RETURN: ($s (HandleError SINGLE_COMMAND_FORMAT_ERROR_NOTHING_WAS_DONE_PLEASE_FIX_AND_RETRY $s (catch (let $result (eval $s) (py-call (helper.normalize_string $result)))))))))))
                                       ($_ (println! $results)))
                                      (progn (if (or $msgnew  (not (== $sexpr ()))) (addToHistory $msg $response $sexpr $msgnew) _)
                                             (change-state! &lastresults (string-safe (repr $results))))) _))
                      ;; Recycling is cooperative: finish the current turn and
                      ;; its bookkeeping, then let the service manager start a
                      ;; fresh heap. The new process clears the request flag.
                      (if (py-call (helper.recycle_requested))
                          (println! (RECYCLE_AT_TURN_BOUNDARY iteration $k))
                          (progn
                            (sleep (get-state &sleepInterval))
                            (mettaclaw (+ 1 $k))))))))
