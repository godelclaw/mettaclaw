;; src/channels.metta — the communication + search edges of the CeTTaClaw core.
;;
;; Mirrors pettaclaw-godel/src/channels.metta: receive, send (externally gated),
;; send to a specific chat, and web search. Focused adapters live beside the
;; core: sending uses src/telegram (claw:tg-send); search skills resolve
;; directly to src/search (claw:search / -tavily / -ddg), so they need no
;; wrapper here. The REAL Telegram receive (getUpdates -> queue -> replay) lives
;; in runtime/telegram_receive.metta; it feeds this core through normal Msg
;; values, while offline goldens script &inbox-schedule directly.

!(import! &self str)
!(import! &self system)
!(import! &self ./telegram.metta)
!(import! &self ./text.metta)
!(import! &self ./utils.metta)

;; ---- receive seam ---------------------------------------------------------
;; Return the "latest message" at iteration $k: the $k-th scheduled message,
;; clamped to the last one (a message persists until a newer one arrives),
;; modelling pettaclaw's telegram.getLastMessage. An empty schedule yields a
;; null bot message, so a channel-less run just idles.
(= (claw:sched-at $sched $k)
   (if (== $sched ())
       (Msg bot "")
       (let ($head $tail) (decons-atom $sched)
            (if (or (== $k 1) (== $tail ()))
                $head
                (claw:sched-at $tail (- $k 1))))))
(= (claw:receive $k)
   (claw:sched-at (get-state &inbox-schedule) $k))

;; ---- send (externally gated) ----------------------------------------------
;; By default (send ...) returns the exact outbound text/chat as data but does
;; NOT call sendMessage. To really deliver, start the process with
;; CETTACLAW_LIVE_SEND_APPROVED=YES_SEND_LIVE_TELEGRAM. (This gate is the agent's
;; policy — it reads agent state (&reply-chat) — so it lives here.)
(= (claw:send-approved?)
   (== (system:getenv-or-default "CETTACLAW_LIVE_SEND_APPROVED" "")
       "YES_SEND_LIVE_TELEGRAM"))

(= (claw:send-to-chat $chat-id $text)
   (let $decoded (claw:decode-safe $text)
        (if (or (== $chat-id "") (== $chat-id NotFound))
            (SendNoChat $decoded)
            (if (claw:send-approved?)
                (case (claw:tg-send $chat-id $decoded)
                  (((HttpResult 200 $body) (Sent $chat-id $decoded 200))
                   ((HttpResult $status $body)
                    (SendFailed $chat-id $decoded (HttpStatus $status)))
                   ($other (SendFailed $chat-id $decoded $other))))
                (SendPreview $chat-id $decoded)))))

(= (claw:send $text)
   (claw:send-to-chat (get-state &reply-chat) $text))

(= (claw:send-telegram-chat $chat-id $text)
   (claw:send-to-chat $chat-id $text))
