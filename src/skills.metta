;; src/skills.metta — the agent's action interface, pure CeTTa.
;;
;; Mirrors pettaclaw-godel/src/skills.metta: the model-facing skill catalog plus
;; one handler per skill, and the command dispatcher that maps a parsed
;; (skill arg ...) into its result. Shell / file I/O use the native process + fs
;; interfaces (no Prolog, no Python). Search, MCP, memory, and LLM access are
;; agent-owned adapters. Policy (recall k) and session state (&llm-model) are
;; supplied here.

!(import! &self process)
!(import! &self fs)
!(import! &self str)
!(import! &self system)
!(import! &self ./value.metta)
!(import! &self ./text.metta)
!(import! &self ./memory.metta)
!(import! &self ./channels.metta)
!(import! &self ./search.metta)
!(import! &self ./mcp.metta)

;; Model-facing skill catalog. Keep this in the same file as dispatch so the
;; prompt interface and the actual command interface drift together, not separately.
(= (claw:skills-catalog)
   (str:join " "
     ("- Remember a particular string such as skills and memories: (remember string)"
      "- Query long-term embedding memory for skills and memories with short phrases only: (query string)"
      "- Pin a certain string as short-term working memory item to keep track of task state: (pin string)"
      "- Rest now, ending this burst until the next human message: (rest)"
      "- Rest now and poll more slowly while idle: (rest seconds)"
      "- Execute shell command without apostrophe in string, it returns the command output to you: (shell string)"
      "- Read file to string: (read-file filename)"
      "- Write string to file: (write-file filename string)"
      "- Append line to file: (append-file filename string)"
      "- Send message to user: (send string)"
      "- Send Telegram message to a specific chat id: (send-telegram-chat chat_id string)"
      "- Search the web using the configured provider: (search string)"
      "- Search the web using Tavily API: (search-tavily string)"
      "- Search the web using DuckDuckGo HTML: (search-ddg string)"
      "- Check your LLM API budget — model in use, credits left, rate window: (llm-quota)"
      "- List the LLM models you can use: (llm-models)"
      "- Switch your LLM model for this session: (llm-set-model model-name)"
      "- List configured MCP servers from .mcp.json: (mcp-servers)"
      "- List MCP tools exposed by a server: (mcp-tools server-name)"
      "- Show one MCP tool's argument schema: (mcp-tool-info server-name tool-name)"
      "- Call any MCP tool with JSON object arguments: (mcp-call server-name tool-name json-object-string)"
      "- Execute MeTTa expression: (metta string)")))

;; Working-memory pins live in a space-backed state cell created by the loop.
;; A pin is just a string appended to the &pins list.
(= (claw:pin $text)
   (let $decoded (claw:decode-safe $text)
   (let $cur (get-state &pins)
   (let $_ (change-state! &pins (cons-atom $decoded $cur))
        (Pinned $text)))))

;; Rest ends the current burst (loops budget -> 0). Optional slower poll.
(= (claw:rest)
   (let $_ (change-state! &loops 0)
        (Resting loops-left 0)))

(= (claw:rest $seconds)
   (let $parsed (claw:parse-nat-arg $seconds)
        (case $parsed
          ((InvalidNumber (RestInvalidSeconds $seconds))
           ($n (let $sleep-seconds (claw:max 1 $n)
                    (let $_ (change-state! &loops 0)
                    (let $__ (change-state! &sleep-ms (* 1000 $sleep-seconds))
                         (Resting loops-left 0 sleep-ms (* 1000 $sleep-seconds))))))))))

;; Shell: run under non-login /bin/sh -c (matching the original agent's `sh -c`)
;; with a hard timeout and a 1 MiB output cap enforced at read time, so a runaway
;; command like `yes` cannot exhaust interpreter memory. Empty cwd inherits the
;; interpreter's working directory; the environment is inherited unchanged.
(= (claw:shell $cmd)
   (let $decoded (claw:decode-safe $cmd)
        (let $r (process-run-cmd-cwd-timeout-cap-bytes
                  ("/bin/sh" "-c" $decoded) "" 5000 1048576)
             (if (process-result-timed-out? $r)
                 (ShellTimeout $decoded)
                 (ShellOk (process-result-exit-code $r)
                          (process-result-aggregated-output $r))))))

;; File I/O over the native fs interface.
(= (claw:read-file $path)
   (if (fs:exists $path)
       (case (fs:read-text $path)
         (((FsError $msg) (ReadFailed $path (FsError $msg)))
          ($text $text)))
       (ReadMissingFile $path)))

(= (claw:write-file $path $text)
   (case (fs:write-text $path (claw:decode-safe $text))
     ((() (Wrote $path))
      ($err (WriteFailed $path $err)))))

(= (claw:append-file $path $text)
   (if (fs:exists $path)
       (case (fs:append-text
               $path
               (str:concat (claw:decode-safe $text) "\n"))
         ((() (Appended $path))
          ($err (AppendFailed $path $err))))
       (AppendMissingFile $path)))

;; Evaluate a MeTTa expression given as text. Pettaclaw evaluated this inside the
;; live interpreter under `catch`; CeTTa's current parse/eval errors can still
;; short-circuit the top-level turn, so run the expression in a bounded child
;; copy of the same binary instead. The agent gets real output as data, and
;; malformed MeTTa cannot kill its own loop.
(= (claw:metta-program $text)
   (str:concat
     "!(let $_ (import! &self ./lib_cettaclaw.metta)\n  "
     (str:concat (claw:decode-safe $text) ")\n")))

(= (claw:metta $text)
   (let $r (process-run-cmd-cwd-env-stdin-timeout-cap-bytes
             ("/proc/self/exe" "--lang" "he" "--profile" "he-extended" "/dev/stdin")
             ""
             ()
             (claw:metta-program $text)
             5000
             1048576)
        (if (process-result-timed-out? $r)
            (MettaTimeout (process-result-aggregated-output $r))
            (if (== (process-result-exit-code $r) 0)
                (MettaOk (process-result-aggregated-output $r))
                (MettaFailed
                  (process-result-exit-code $r)
                  (process-result-aggregated-output $r))))))

;; LLM session model switch: the LLM adapter validates against the live /models
;; list (pure) and returns a verdict; the agent owns the &llm-model cell, so the
;; state write + user-facing message happen here.
(= (claw:llm-set-model $name)
   (case (claw:llm-validate-model $name)
     (((LlmModelValid $m)
       (let $_ (change-state! &llm-model $m)
            (str:join "" ("model set to '" $m
                          "' for this session (reverts to default on restart)"))))
      ((LlmModelUnknown $m $ids)
       (str:join "" ("unknown model '" $m "'; available: " (str:join ", " $ids))))
      ((LlmModelListEmpty) "model list empty; model unchanged")
      ((LlmModelListUnavailable $why) "cannot validate model list; model unchanged")
      ($other "cannot validate model list; model unchanged"))))

;; The agent's current model = its session override (&llm-model), else default.
(= (claw:session-model)
   (claw:llm-current-model (get-state &llm-model)))

;; ---- dispatch: map a (skill arg ...) command to its result ----------------
;; Model output is syntax, not code. Use a quoted dispatcher so an accidental
;; built-in head such as (+ 1 "x") becomes UnknownCommand instead of reducing
;; before the command interface can inspect it. One equation + case keeps branch
;; selection deterministic; overlapping direct equations fan out in HE. Memory
;; recall k and the current model are the agent's policy/state, applied here.
(= (claw:run-quoted (quote $cmd))
   (case (quote $cmd)
     (((quote (pin $x))           (claw:pin $x))
      ((quote (rest))             (claw:rest))
      ((quote (rest $s))          (claw:rest $s))
      ((quote (send $t))          (claw:send $t))
      ((quote (send-telegram-chat $chat $t))
                                   (claw:send-telegram-chat $chat $t))
      ((quote (remember $t))      (claw:remember $t))
      ((quote (query $q))         (claw:query (claw:max-recall-items) $q))
      ((quote (search $q))        (claw:search $q))
      ((quote (search-tavily $q)) (claw:search-tavily $q))
      ((quote (search-ddg $q))    (claw:search-ddg $q))
      ((quote (mcp-servers))      (claw:mcp-servers))
      ((quote (mcp-tools $s))     (claw:mcp-tools $s))
      ((quote (mcp-tool-info $s $t))
                                   (claw:mcp-tool-info $s $t))
      ((quote (mcp-call $s $t $j))
                                   (claw:mcp-call $s $t $j))
      ((quote (llm-quota))        (claw:llm-quota (claw:session-model)))
      ((quote (llm-models))       (claw:llm-models))
      ((quote (llm-set-model $m)) (claw:llm-set-model $m))
      ((quote (shell $c))         (claw:shell $c))
      ((quote (read-file $p))     (claw:read-file $p))
      ((quote (write-file $p $t)) (claw:write-file $p $t))
      ((quote (append-file $p $t))(claw:append-file $p $t))
      ((quote (metta $e))         (claw:metta $e))
      ($other                     (UnknownCommand (quote $cmd))))))

(= (claw:run $cmd)
   (claw:run-quoted (quote $cmd)))
