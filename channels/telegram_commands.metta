; Lila's operator commands, as the CeTTa Telegram channel service reads them
; (--commands). Declarations only; the service refuses anything else.
;
; help, stop and start are the service's own: it answers them at once, and
; stop holds everything Lila submits until start. Every delegated command is
; asked of Lila's runtime and answered from its own thread, never from her
; cognition; if that answer is late, the service replies with a notice and
; edits it when the answer arrives.
;
; The menu commands (/energy, /engines, /fuels, /modes, /models) are not
; declared yet: they reach Lila as ordinary input and keep their buttons.

(tg-cmd:agent "Lila")

(tg-cmd:command "/help" help "List these commands")
(tg-cmd:command "/stop" stop "Stop cognition and hold everything Lila sends")
(tg-cmd:command "/start" start "Enable cognition and let her messages out again")
(tg-cmd:command "/wake" delegated "End the current rest")
(tg-cmd:command "/activity" delegated "Show whether cognition is working, resting, or idle")
(tg-cmd:command "/health" delegated "Show runtime, channel, and memory health")
(tg-cmd:command "/engine" delegated "Show or switch the evaluator engine")
(tg-cmd:command "/fuel" delegated "Show or switch what a renewal does to the budget")
(tg-cmd:command "/mode" delegated "Show or switch the cognitive loop mode")
(tg-cmd:command "/model" delegated "Show or switch the language model")
(tg-cmd:command "/quota" delegated "Show model budget")
(tg-cmd:command "/delete" delegated "Delete a message: /delete chat message-id")
(tg-cmd:command "/claude_code_authorization" delegated "Toggle Claude Code authorization")
