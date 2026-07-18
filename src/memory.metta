;Configured at runtime memory and history in amount of characters:
(= (maxFeedback) (empty))
(= (maxRecallItems) (empty))
(= (maxHistory) (empty))

(= (initMemory)
   (progn (println! "Initializing memory")
          (configure maxFeedback 50000)
          (configure maxRecallItems 20)
          (configure maxHistory 30000)))

(= (getPrompt)
   (read-file (py-call (helper.path_from_env "METTACLAW_PROMPT_PATH" "./memory/prompt.txt"))))

;; Anchored window (not a sliding tail): byte-stable start so the provider
;; prompt cache keeps hitting as history appends; re-anchors only when the
;; window outgrows its cap.
(= (getHistory)
   (py-call (helper.history_window
              (py-call (helper.path_from_env "METTACLAW_HISTORY_PATH" "./memory/history.metta")))))

(= (addToHistory $lastmessage $response $sexpr $msgnew)
   (if $msgnew
       (if (== (get-state &error) ())
           (appendToHistory ((get_time_as_string) (newline) "HUMAN_MESSAGE: " $lastmessage (newline) $response (newline)))
           (appendToHistory ((get_time_as_string) (newline) "HUMAN_MESSAGE: " $lastmessage (newline) $response (newline) ERROR_FEEDBACK: (get-state &error))))
       (if (== (get-state &error) ())
           (appendToHistory ((get_time_as_string) (newline) $response (newline)))
           (appendToHistory ((get_time_as_string) (newline) $response (newline) ERROR_FEEDBACK: (get-state &error))))))

(= (appendToHistory $addition)
   (append-file (py-call (helper.path_from_env "METTACLAW_HISTORY_PATH" "./memory/history.metta")) (swrite $addition)))

(= (remember $str)
   (let $memory (py-call (helper.decode_safe_text $str))
        (let $embedding (py-call (qwen_embed.embed_document (string-safe $memory)))
             (py-call (lib_chromadb.remember $memory $embedding (get_time_as_string))))))

(= (query $str)
   (let $query (py-call (helper.decode_safe_text $str))
        (let $embedding (py-call (qwen_embed.embed_query (string-safe $query)))
             (py-call (lib_chromadb.query $embedding (maxRecallItems))))))
