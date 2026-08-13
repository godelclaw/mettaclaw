(= (getSkills)
   (;INTERNAL:
    "- Remember a particular string such as skills and memories: (remember \"string\")"
    "- Query long-term embedding memory for skills and memories with short phrases only: (query \"short phrase\")"
    "- Pin a working-memory line — persists across restarts, shown every turn under PINNED, cap 12: (pin \"string\")"
    "- Remove pins containing a fragment: (unpin \"fragment\")"
    "- Goal stack + mood (kernel decays STI, consolidates LTI, flags stuck/cull-review at each wake): (goals)"
    "- Add/update one goal (liberal format, see (help \"goal-write\")): (goal-write (goal name Area sti:0.8 lti:0.3 vibes:(a b) blocked-by:none last-verified:never note:why it matters))"
    "- Compost a goal (needs cull-review flag, or reason solved with last-verified set): (goal-drop \"name\" \"reason\")"
    "- Rest now, ending this burst until the next human message: (rest)"
    "- Rest now and poll more slowly while idle: (rest seconds)"
    "- Rest with a stated intention shown at your next waking: (rest seconds \"why\")"
    "- Finish this fast burst without suspending autonomous renewal: (nop)"
    "- Inspect/select the persistent cognitive loop policy: (mode) | (modes) | (mode-set \"name\")"
    ;SHELL AND FILE I/O:
    "- Execute shell command, it returns the command output to you: (shell \"command string\")"
    "- Read file to string: (read-file \"filename\")"
    "- Write string to file: (write-file \"filename\" \"string\")"
    "- Append line to file: (append-file \"filename\" \"string\")"
    "- Read a numbered window of a file: (read-lines \"filename\" start count)"
    "- Edit a file by exact unique string replacement — no full rewrite; the result confirms success or explains exactly what to fix: (edit-file \"filename\" \"old-string\" \"new-string\")"
    "- Compact directory tree, dirs first with file sizes: (ls-tree \"dir\" depth)"
    "- Search text across files under a dir, bounded output: (grep-files \"pattern\" \"dir\")",
	    ;COMMUNICATION CHANNELS:
	    "- Send message to user: (send \"string\")"
	    "- Send Telegram message to a specific chat id: (send-telegram-chat \"chat_id\" \"string\")"
	    "- Send a FILE to the chat as an attachment: (send-file \"/path/to/file.md\" \"caption\")"
	    "- Send an IMAGE so it previews inline; .svg is auto-converted to png: (send-image \"/path/diagram.svg\" \"caption\")"
	    "- Clean up after a test send: delete your own last k messages to a chat: (delete-my-recent \"chat_id\" k)"
	    "- Arming energy per sender (how many loops a message grants): (energy) to view, (energy-set \"default|Name|id\" \"full|mid|light\")"
	    "- Sibling claw control, watchdog-safe: (sibling-status) | (sibling-on) | (sibling-off \"reason\")"
	    "- Last k messages (both sides) from a chat by title or id: (recent-messages \"chat\" k)"
	    "- Search the web using the configured provider: (search \"string\")"
    "- Search the web using Tavily API: (search-tavily \"string\")"
    "- Search the web using DuckDuckGo HTML: (search-ddg \"string\")"
    ;LLM API:
    "- Check your embedding memory's health — how far the on-disk index trails your writes: (memory-health)"
    "- Attempt memory-index catch-up and report measured before/after drift: (memory-compact)"
    "- Check your LLM API budget — model in use, credits left, rate window: (llm-quota)"
    "- List the LLM models you can use: (llm-models)"
    "- Switch your LLM model for this session: (llm-set-model \"model-name\")"
    ;MCP:
    "- List configured MCP servers from .mcp.json: (mcp-servers)"
    "- List MCP tools exposed by a server: (mcp-tools \"server-name\")"
    "- Show one MCP tool's argument schema: (mcp-tool-info \"server-name\" \"tool-name\")"
    "- Call any MCP tool with JSON object arguments: (mcp-call \"server-name\" \"tool-name\" \"json-object-string\")"
    ;CODE EXECUTION:
    "- Execute MeTTa expression: (metta \"expression string\")"
    ;CLAUDE CODE AND TMUX:
    "- Ask Claude Code one headless question (needs Zar's authorization toggle): (claude-code \"prompt\")"
    "- List tmux windows: (tmux-windows)"
    "- Read the last n lines of any window on this user's tmux server: (tmux-peek \"session:window\" 30)"
    "- Type into any window on this user's tmux server: (tmux-send \"session:window\" \"message\")"
    ;WHEN UNSURE:
    "- Man page for any skill (usage, example, common failure): (help \"skill-name\")"
    "- Dry-run a command string through the real parser, nothing executes: (check \"(shell \\\"ls /tmp\\\")\")"))

;; read-file explains failure instead of silently returning nothing: the old
;; Prolog chain FAILED (empty result, no reason) on a missing/unreadable path,
;; which cost real time — the file existed but a relative path did not resolve
;; from the loop's cwd, and nothing said so.
(= (read-file $file)
   (py-call (fsops.read_file $file)))

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
   (progn (py-call (loop_modes.pause_autonomy))
          (change-state! &loops 0)
          (RESTING loops-left (get-state &loops)
                   sleep-interval-seconds (get-state &sleepInterval))))

(= (rest $seconds)
   ;; Rest duration remains the agent's decision. An authenticated operator
   ;; message or /wake may deliberately end it; other activity queues.
   (let $n (max 1 (py-call (int $seconds)))
        (progn (py-call (loop_modes.pause_autonomy))
               (change-state! &loops 0)
               (change-state! &sleepInterval $n)
               (RESTING loops-left (get-state &loops)
                        sleep-interval-seconds (get-state &sleepInterval)))))

(= (rest $seconds $why)
   ;; Rest with a stated intention: the why survives every boundary and
   ;; greets the next waking (WOKE_FROM_REST), and tells anyone thinking
   ;; who wakes the agent what the rest is for.
   (let $n (max 1 (py-call (int $seconds)))
        (progn (py-call (loop_modes.pause_autonomy))
               (change-state! &loops 0)
               (change-state! &sleepInterval $n)
               (py-call (helper.intent_save (py-call (helper.decode_safe_text $why))))
               (RESTING loops-left (get-state &loops)
                        sleep-interval-seconds (get-state &sleepInterval)
                        intent (py-call (helper.decode_safe_text $why))))))

;; A claw23 burst ends either at its step bound or explicitly via nop. Unlike
;; rest, nop leaves autonomous renewal armed for the next idle boundary.
(= (nop)
   (progn (py-call (loop_modes.resume_autonomy))
          (change-state! &loops 0)
          (BURST_COMPLETE loops-left (get-state &loops))))

(= (mode) (py-call (loop_modes.mode_view)))
(= (modes) (py-call (loop_modes.modes_view)))
(= (mode-set $name) (py-call (loop_modes.set_mode $name)))

;; Telegram file/image delivery. The result string says what happened —
;; "sent <name> (<n> bytes) to chat <id>" or the actual failure reason.
;; send-image previews inline; SVG is rasterized to PNG when a converter
;; exists, otherwise delivered as a file (Telegram cannot preview SVG).
(= (send-file $path) (py-call (telegram.send_file $path "")))
(= (send-file $path $caption)
   (py-call (telegram.send_file $path (py-call (helper.decode_safe_text $caption)))))
(= (send-image $path) (py-call (telegram.send_image $path "")))
(= (send-image $path $caption)
   (py-call (telegram.send_image $path (py-call (helper.decode_safe_text $caption)))))

;; Filesystem awareness: line-numbered reads, exact-string edits with
;; uniqueness enforced, bounded tree/search. Result strings are the
;; verification — no blind writes, no re-reading to check what landed.
(= (read-lines $f $start $count) (py-call (fsops.read_lines $f $start $count)))
(= (edit-file $f $old $new)
   (py-call (fsops.edit_file $f (py-call (helper.decode_safe_text $old))
                                (py-call (helper.decode_safe_text $new)))))
(= (ls-tree $dir $depth) (py-call (fsops.ls_tree $dir $depth)))
(= (grep-files $pat $dir)
   (py-call (fsops.grep_files (py-call (helper.decode_safe_text $pat)) $dir)))

;; Autonomic goal-stack (to-mama spec v0.2): kernel math runs at wake events;
;; these skills are the semantic interface (appraisal, birth, death-review).
(= (goals) (py-call (goals.goals_view)))
(= (goal-write $atom)
   (py-call (goals.goal_write (py-call (helper.decode_safe_text $atom)))))
(= (goal-drop $name $reason) (py-call (goals.goal_drop $name $reason)))

;; Claude Code bridge + tmux interface. Headless claude-code remains gated by
;; the operator toggle. Every window on this Unix user's tmux server is shared
;; agent workspace, so tmux-send needs no separate authorization layer.
(= (claude-code $prompt)
   (py-call (claude_bridge.ask (py-call (helper.decode_safe_text $prompt)))))
(= (tmux-windows) (py-call (tmux_bridge.windows)))
(= (tmux-peek $win $n) (py-call (tmux_bridge.peek $win $n)))
(= (tmux-send $win $text)
   (py-call (tmux_bridge.send $win (py-call (helper.decode_safe_text $text)))))

;; Progressive disclosure: one-line catalog above, full page on demand.
;; check parses with the loop's OWN reader (sread), so its verdict is the
;; loop's verdict — nothing is executed either way.
(= (help) (py-call (skills_help.help "")))
(= (help $name) (py-call (skills_help.help (py-call (helper.decode_safe_text $name)))))
(= (check $str)
   ;; repr BEFORE the bridge: a caught syntax_error compound cannot cross
   ;; janus (Domain error: py_term) — as a string it always can.
   (let $decoded (py-call (helper.decode_safe_text $str))
        (let $parsed (catch (sread $decoded))
             (let $rendered (repr $parsed)
                  (py-call (skills_help.verdict $decoded $rendered))))))

;; Pins: real, persisted working memory (previously catalog-only — the call
;; just echoed itself into results feedback and vanished on restart).
(= (pin $text) (py-call (pins.pin (py-call (helper.decode_safe_text $text)))))
(= (unpin $frag) (py-call (pins.unpin (py-call (helper.decode_safe_text $frag)))))

;; Arming energy (persisted per-sender loop tiers) and sibling-claw control.
;; sibling-on/off always handle the watchdog pause marker too, so a stop
;; STAYS stopped and a start is not raced by the reviver.
(= (energy) (py-call (telegram.energy_view)))
(= (energy-set $who $tier) (py-call (telegram.energy_set $who $tier)))
(= (sibling-status) (py-call (sibling.sibling_status)))
(= (sibling-on) (py-call (sibling.sibling_on)))
(= (sibling-off $reason)
   (py-call (sibling.sibling_off (py-call (helper.decode_safe_text $reason)))))

;; LLM API introspection (synthetic.new): budget, model list, session model switch.
(= (memory-health) (py-call (memory_health.report)))
(= (memory-compact) (py-call (memory_health.compact)))
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
