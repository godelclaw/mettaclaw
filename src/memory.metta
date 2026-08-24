;Configured at runtime memory and history in amount of characters:
(= (maxFeedback) (empty))
(= (maxRecallItems) (empty))
(= (maxRecentTurns) (empty))

(= (initMemory)
   (progn (println! "Initializing memory")
          (configure maxFeedback 50000)
          (configure maxRecallItems 20)
          (configure maxRecentTurns 8)))

(= (getPrompt)
   (read-file (py-call (helper.path_from_env "METTACLAW_PROMPT_PATH" "./memory/prompt.txt"))))

;; The running proposal window: what the model requested over the last few
;; substantive turns. Broker receipts, not this transcript, say what ran.
;; No-op turns do not consume a slot.
(= (recentActions)
   (py-call (helper.recent_actions
              (py-call (helper.path_from_env "METTACLAW_HISTORY_PATH" "./memory/history.metta"))
              (maxRecentTurns))))

(= (relevantFiles)
   (py-call (helper.relevant_files
              (py-call (helper.path_from_env "METTACLAW_HISTORY_PATH" "./memory/history.metta"))
              (maxRecentTurns))))

(= (addToHistory $lastmessage $response $msgnew)
   (if $msgnew
       (if (== (get-state &error) ())
           (appendToHistory ((get_time_as_string) (newline) "HUMAN_MESSAGE: " $lastmessage (newline) $response (newline)))
           (appendToHistory ((get_time_as_string) (newline) "HUMAN_MESSAGE: " $lastmessage (newline) $response (newline) ERROR_FEEDBACK: (get-state &error))))
       (if (== (get-state &error) ())
           (appendToHistory ((get_time_as_string) (newline) $response (newline)))
           (appendToHistory ((get_time_as_string) (newline) $response (newline) ERROR_FEEDBACK: (get-state &error))))))

(= (appendToHistory $addition)
   (py-call (helper.history_append (swrite $addition))))

;; Guarded: a dead embed daemon returns an instructive string result
;; ("do not infer absence") instead of a generic command error.
(= (remember $str)
   (let $memory (py-call (helper.decode_safe_text $str))
        (py-call (qwen_embed.remember_guarded (string-safe $memory) (get_time_as_string)))))

(= (query $str)
   (let $query (py-call (helper.decode_safe_text $str))
        (py-call (qwen_embed.query_guarded (string-safe $query) (maxRecallItems)))))
