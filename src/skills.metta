(= (getSkills)
   (;INTERNAL:
    "- Remember a particular string such as skills and memories: (remember string)"
    "- Query long-term embedding memory for skills and memories with short phrases only: (query string)"
    "- Pin a certain string as short-term working memory item to keep track of task state: (pin string)"
    "- Goal stack + mood (kernel decays STI, consolidates LTI, flags stuck/cull-review at each wake): (goals)"
    "- Add/update one goal — no quotes, hyphenate blocked-by, note is free text: (goal-write string) e.g. (goal-write (goal name Area sti:0.8 lti:0.3 vibes:(a b) blocked-by:none last-verified:never note:why it matters))"
    "- Compost a goal (needs cull-review flag, or reason solved with last-verified set): (goal-drop name reason)"
    "- Rest now, ending this burst until the next human message: (rest)"
    "- Rest now and poll more slowly while idle: (rest seconds)"
    ;SHELL AND FILE I/O:
    "- Execute shell command without apostrophe in string, it returns the command output to you: (shell string)"
    "- Read file to string: (read-file filename)"
    "- Write string to file: (write-file filename string)"
    "- Append line to file: (append-file filename string)",
	    ;COMMUNICATION CHANNELS:
	    "- Send message to user: (send string)"
	    "- Send Telegram message to a specific chat id: (send-telegram-chat chat_id string)"
	    "- Last k messages (both sides) from a chat by title or id: (recent-messages chat k)"
	    "- Search the web using the configured provider: (search string)"
    "- Search the web using Tavily API: (search-tavily string)"
    "- Search the web using DuckDuckGo HTML: (search-ddg string)"
    ;LLM API:
    "- Check your LLM API budget — model in use, credits left, rate window: (llm-quota)"
    "- List the LLM models you can use: (llm-models)"
    "- Switch your LLM model for this session: (llm-set-model model-name)"
    ;MCP:
    "- List configured MCP servers from .mcp.json: (mcp-servers)"
    "- List MCP tools exposed by a server: (mcp-tools server-name)"
    "- Show one MCP tool's argument schema: (mcp-tool-info server-name tool-name)"
    "- Call any MCP tool with JSON object arguments: (mcp-call server-name tool-name json-object-string)"
    ;CODE EXECUTION:
    "- Execute MeTTa expression: (metta string)"))

(= (read-file $file)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (read_file_to_string $file $content ()))
          $content))

(= (write-file $file $str)
   (progn (translatePredicate (open $file write $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (close $Out))
          True))

(= (append-file $file $str)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (open $file append $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (nl $Out)),
          (translatePredicate (close $Out))
          True))

!(import_prolog_functions_from_file ./src/skills.pl (shell first_char))

(= (metta $str)
   (let $code (sread $str)
        (eval $code)))

(= (rest)
   (progn (change-state! &loops 0)
          (RESTING loops-left (get-state &loops)
                   sleep-interval-seconds (get-state &sleepInterval))))

(= (rest $seconds)
   (let $n (max 1 (py-call (int $seconds)))
        (progn (change-state! &loops 0)
               (change-state! &sleepInterval $n)
               (RESTING loops-left (get-state &loops)
                        sleep-interval-seconds (get-state &sleepInterval)))))

;; Autonomic goal-stack (to-mama spec v0.2): kernel math runs at wake events;
;; these skills are the semantic interface (appraisal, birth, death-review).
(= (goals) (py-call (goals.goals_view)))
(= (goal-write $atom)
   (py-call (goals.goal_write (py-call (helper.decode_safe_text $atom)))))
(= (goal-drop $name $reason) (py-call (goals.goal_drop $name $reason)))

;; LLM API introspection (synthetic.new): budget, model list, session model switch.
(= (llm-quota) (py-call (synthetic_llm.quota)))
(= (llm-models) (py-call (synthetic_llm.models)))
(= (llm-set-model $name) (py-call (synthetic_llm.set_model $name)))

;; Generic MCP bridge. Servers are configured in .mcp.json; arguments are JSON.
(= (mcp-servers) (py-call (mcp_bridge.servers)))
(= (mcp-tools $server) (py-call (mcp_bridge.tools $server)))
(= (mcp-tool-info $server $tool) (py-call (mcp_bridge.tool_info $server $tool)))
(= (mcp-call $server $tool $json)
   (let $args (py-call (helper.decode_safe_text $json))
        (py-call (mcp_bridge.call_tool $server $tool $args))))
