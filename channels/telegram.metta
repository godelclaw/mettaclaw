; Lila's Telegram client, in MeTTa.
;
; The CeTTa Telegram channel service owns the bot: it polls, routes, records
; every update before anyone sees it, sends, and answers operator commands.
; This client is Lila's side of it. It reads the service's tasks through
; lib/cwp, turns messages into her activity, keeps her conversation ledger,
; arms her loop by sender, sends and deletes through the service, rests until
; she is woken, and answers the operator commands the service asks about.
;
; One store: an incoming message stays pending in the service until the
; turn that read it is in history (tg:ack-activity-batch). A restart reads
; it again from the service; there is no offset or receipt file here.
;
; Python still provides, through channels/telegram.py: the button menus and
; attachment downloads (both call the Bot API directly), file and image
; uploads, and the ledger readers used by her Python context and health code,
; which read state this client publishes there.

!(import! &self str)
!(import! &self json)
!(import! &self fs)
!(import! &self cwp)
!(import! &self system)

;; ---------------------------------------------------------------- lists
;; A list built by cons-atom onto a computed tail may be an open PeTTa cell.
;; car-atom and cdr-atom read both kinds; decons-atom inside an equation and
;; native operations such as str:join do not on every engine path. So lists
;; are taken apart with tg:uncons, and a list built here is made flat with
;; tg:list before a native operation reads it.
(= (tg:uncons $items)
   (let $head (car-atom $items)
     (let $tail (cdr-atom $items) ($head $tail))))
(= (tg:items $items)
   (if (== $items ()) (empty)
     (superpose ((car-atom $items) (tg:items (cdr-atom $items))))))
(= (tg:list $items) (collapse (tg:items $items)))

;; ---------------------------------------------------------------- state
;; add-atom stores its argument as data: every value is bound with let
;; before it is added.

(= (tg:get $name $default)
   (case (collapse (match &self (tg:var $name $value) $value))
     ((() $default)
      (($value) $value)
      ($many (car-atom $many)))))

(= (tg:set $name $value)
   (let $old (collapse (match &self (tg:var $name $v) $v))
     (let $gone (tg:drop-vars $name $old)
       (let $added (add-atom &self (tg:var $name $value)) $value))))

(= (tg:drop-vars $name $values)
   (if (== $values ()) ()
     (let ($head $tail) (tg:uncons $values)
       (let $gone (remove-atom &self (tg:var $name $head))
         (tg:drop-vars $name $tail)))))

(= (tg:next-number $name)
   (let $n (+ (tg:get $name 0) 1) (tg:set $name $n)))

;; -------------------------------------------------------- configuration

(= (tg:env $name $default) (system:getenv-or-default $name $default))

; Whether this client, not channels/telegram.py, is Lila's Telegram client.
(= (tg:client-metta?) (== (tg:env "METTACLAW_TELEGRAM_CLIENT" "python") "metta"))

(= (tg:split-ids $raw)
   (tg:nonempty (tg:trim-all (str:split "," $raw))))
(= (tg:trim-all $items)
   (if (== $items ()) ()
     (let ($head $tail) (tg:uncons $items)
       (let $trimmed (str:trim $head)
         (let $rest (tg:trim-all $tail) (cons-atom $trimmed $rest))))))
(= (tg:nonempty $items)
   (if (== $items ()) ()
     (let ($head $tail) (tg:uncons $items)
       (let $rest (tg:nonempty $tail)
         (if (== $head "") $rest (cons-atom $head $rest))))))

(= (tg:member $x $items)
   (if (== $items ()) False
     (let ($head $tail) (tg:uncons $items)
       (if (== $x $head) True (tg:member $x $tail)))))

; Comma-separated ids, compared as text.
(= (tg:csv $raw) (str:join "" (str:split " " $raw)))
(= (tg:csv-member? $id $raw)
   (let $haystack (format-args ",{}," ((tg:csv $raw)))
     (let $needle (format-args ",{}," ($id))
       (case (str:find $haystack $needle)
         (((TextNotFound $n) False)
          ($at True))))))
(= (tg:csv-empty? $raw) (== (str:join "" (str:split "," (tg:csv $raw))) ""))

(= (tg:socket) (tg:env "METTACLAW_TELEGRAM_SERVICE_SOCKET" ""))
(= (tg:ledger) (tg:env "METTACLAW_TELEGRAM_LOG_PATH" ""))
(= (tg:primary) (str:trim (tg:env "METTACLAW_TELEGRAM_PRIMARY_CHAT_ID" "")))
(= (tg:allowed-chats)
   (let $a (tg:env "METTACLAW_TELEGRAM_CHAT_ID" "")
     (let $b (tg:env "TELEGRAM_CHAT_ID" "")
       (let $c (tg:env "METTACLAW_TELEGRAM_ALLOWED_CHAT_IDS" "")
         (format-args "{},{},{}" ($a $b $c))))))
(= (tg:timeout-ms)
   (let $s (tg:env "METTACLAW_TELEGRAM_SERVICE_TIMEOUT" "30")
     (let $n (parse $s) (if (< $n 1) 1000 (* 1000 $n)))))

(= (tg:operator? $id)
   (and (not (== $id "")) (tg:csv-member? $id (tg:env "METTACLAW_TELEGRAM_OPERATOR_IDS" ""))))
(= (tg:wake-peer? $id)
   (and (not (== $id "")) (tg:csv-member? $id (tg:env "METTACLAW_TELEGRAM_WAKE_IDS" ""))))

;; ------------------------------------------------------------ json data
;; Compatibility JSON values: (JsonObject ((JsonPair key value) ...)),
;; (JsonArray (...)), (JsonString s), (JsonNumber lexeme), (JsonBool b),
;; JsonNull. A missing field is JsonNull.

(= (tg:at $object $key)
   (case $object
     (((JsonObject $pairs) (tg:pair $pairs $key))
      ($other JsonNull))))
(= (tg:pair $pairs $key)
   (if (== $pairs ()) JsonNull
     (let ($head $tail) (tg:uncons $pairs)
       (case $head
         (((JsonPair $key $value) $value)
          ($other (tg:pair $tail $key)))))))

; The value as Python's str() of a JSON scalar would show it; "" if absent.
(= (tg:str $value)
   (case $value
     (((JsonString $s) $s)
      ((JsonNumber $n) $n)
      ((JsonBool $b) (if $b "True" "False"))
      ($other ""))))

; Python truthiness of a JSON value.
(= (tg:truthy $value)
   (case $value
     ((JsonNull False)
      ((JsonBool $b) (if $b True False))
      ((JsonString "") False)
      ((JsonNumber "0") False)
      ((JsonObject ()) False)
      ((JsonArray ()) False)
      ($other True))))

(= (tg:jstr $s) (JsonString $s))
(= (tg:jbool $b) (if $b (JsonBool True) (JsonBool False)))
(= (tg:jnum $n) (JsonNumber (format-args "{}" ($n))))
(= (tg:quote $s) (json-stringify (JsonString $s)))

;; ------------------------------------------------------------ transport

(= (tg:call $code $name $body)
   (let $path (tg:socket) (cwp:call $path $code $name $body 5000)))

; Pending tasks after the given task, oldest first, up to limit.
(= (tg:tasks-after $after $limit)
   (if (== $limit 0) ()
     (case (tg:call 1 $after "")
       (((cwp:reply 65 $task $body)
         (let $rest (tg:tasks-after $task (- $limit 1))
           (cons-atom ($task $body) $rest)))
        ($other ())))))

(= (tg:acknowledge $task)
   (case (tg:call 2 $task "[]")
     (((cwp:reply 66 $n $b) True)
      ((cwp:reply 68 $n $b) True)
      ($other False))))

(= (tg:answer-task $task $text)
   (let $cut (if (> (str:length $text) 3800) (str:slice $text 0 3800) $text)
     (let $body (json-stringify (JsonArray ((JsonString "answer") (JsonString $cut))))
       (case (tg:call 2 $task $body)
         (((cwp:reply 66 $n $b) True)
          ((cwp:reply 68 $n $b) True)
          ((cwp:reply 69 $n $b) True)
          ($other False))))))

;; --------------------------------------------------------------- clocks

(= (tg:now-iso) (py-call (time.strftime "%Y-%m-%dT%H:%M:%S%z")))
(= (tg:now) (py-call (time.time)))
(= (tg:clock $epoch)
   (if (== $epoch "") "" (py-call (helper.local_clock $epoch))))
(= (tg:sleep $seconds) (py-call (time.sleep $seconds)))

;; ------------------------------------------------------------ formatting

(= (tg:compact $text $limit)
   (let $flat (str:join " " (str:split-whitespace $text))
     (if (> (str:length $flat) $limit)
       (let $head (str:slice $flat 0 (- $limit 1)) (str:concat $head "…"))
       $flat)))

; key="value" for a present value, () when empty.
(= (tg:field $key $text)
   (let $value (tg:compact $text 160)
     (if (== $value "") ()
       (let $quoted (tg:quote $value) ((format-args "{}={}" ($key $quoted)))))))
(= (tg:flag $key $truth)
   ((format-args "{}={}" ($key (if $truth "true" "false")))))

(= (tg:display-user $user)
   (if (not (tg:truthy $user)) ""
     (let $username (tg:str (tg:at $user "username"))
       (if (not (== $username "")) (str:concat "@" $username)
         (let $first (tg:str (tg:at $user "first_name"))
           (if (not (== $first "")) $first (tg:str (tg:at $user "id"))))))))

(= (tg:display-chat $chat)
   (if (not (tg:truthy $chat)) ""
     (let $title (tg:str (tg:at $chat "title"))
       (if (not (== $title "")) $title
         (let $username (tg:str (tg:at $chat "username"))
           (if (not (== $username "")) (str:concat "@" $username)
             (let $first (tg:str (tg:at $chat "first_name"))
               (if (not (== $first "")) $first (tg:str (tg:at $chat "id"))))))))))

(= (tg:message-text $message)
   (let $text (tg:str (tg:at $message "text"))
     (if (not (== $text "")) $text (tg:str (tg:at $message "caption")))))

(= (tg:excerpt $message)
   (if (not (tg:truthy $message)) "" (tg:compact (tg:message-text $message) 180)))

(= (tg:append $front $back)
   (if (== $front ()) $back
     (let ($head $tail) (tg:uncons $front)
       (let $rest (tg:append $tail $back) (cons-atom $head $rest)))))
(= (tg:concat-lists $lists)
   (if (== $lists ()) ()
     (let ($head $tail) (tg:uncons $lists)
       (let $rest (tg:concat-lists $tail) (tg:append $head $rest)))))

(= (tg:forward-fields $message)
   (let $origin (tg:at $message "forward_origin")
     (if (tg:truthy $origin)
       (let $type (tg:str (tg:at $origin "type"))
         (let $who
              (if (== $type "user")
                (let $user (tg:at $origin "sender_user")
                  (tg:concat-lists ((tg:field "forward_from" (tg:display-user $user))
                                    (tg:field "forward_from_id" (tg:str (tg:at $user "id"))))))
                (if (== $type "hidden_user")
                  (tg:field "forward_from" (tg:str (tg:at $origin "sender_user_name")))
                  (if (or (== $type "chat") (== $type "channel"))
                    (let $c1 (tg:at $origin "sender_chat")
                      (let $chat (if (tg:truthy $c1) $c1 (tg:at $origin "chat"))
                        (tg:concat-lists ((tg:field "forward_from_chat" (tg:display-chat $chat))
                                          (tg:field "forward_from_chat_id" (tg:str (tg:at $chat "id")))))))
                    ())))
           (tg:concat-lists ((tg:flag "forwarded" True) (tg:field "forward_type" $type) $who
                             (tg:field "forward_message_id" (tg:str (tg:at $origin "message_id")))
                             (tg:field "forward_signature" (tg:str (tg:at $origin "author_signature")))))))
       (let $user (tg:at $message "forward_from")
         (let $chat (tg:at $message "forward_from_chat")
           (let $name (tg:str (tg:at $message "forward_sender_name"))
             (if (or (tg:truthy $user) (or (tg:truthy $chat) (not (== $name ""))))
               (let $shown (tg:display-user $user)
                 (tg:concat-lists ((tg:flag "forwarded" True)
                                   (tg:field "forward_from" (if (== $shown "") $name $shown))
                                   (tg:field "forward_from_id" (tg:str (tg:at $user "id")))
                                   (tg:field "forward_from_chat" (tg:display-chat $chat))
                                   (tg:field "forward_from_chat_id" (tg:str (tg:at $chat "id")))
                                   (tg:field "forward_signature" (tg:str (tg:at $message "author_signature"))))))
               (tg:flag "forwarded" False))))))))

(= (tg:reply-fields $message)
   (let $reply (tg:at $message "reply_to_message")
     (let $external (tg:at $message "external_reply")
       (let $quote (tg:at $message "quote")
         (let $own
              (if (tg:truthy $reply)
                (let $sender (tg:at $reply "from")
                  (tg:concat-lists ((tg:flag "is_reply" True)
                                    (tg:field "reply_to_message_id" (tg:str (tg:at $reply "message_id")))
                                    (tg:field "reply_to_from" (tg:display-user $sender))
                                    (tg:field "reply_to_from_id" (tg:str (tg:at $sender "id")))
                                    (tg:field "reply_to_chat" (tg:display-chat (tg:at $reply "chat")))
                                    (tg:field "reply_to_excerpt" (tg:excerpt $reply)))))
                (tg:flag "is_reply" False))
           (let $ext
                (if (tg:truthy $external)
                  (tg:concat-lists ((tg:field "external_reply_origin" (json-stringify (tg:at $external "origin")))
                                    (tg:field "external_reply_excerpt" (tg:excerpt $external))))
                  ())
             (let $q (if (tg:truthy $quote) (tg:field "quote" (tg:str (tg:at $quote "text"))) ())
               (tg:concat-lists ($own $ext $q)))))))))

(= (tg:format-message $update $kind $message $text)
   (let $chat (tg:at $message "chat")
     (let $sender (tg:at $message "from")
       (let $sender-chat (tg:at $message "sender_chat")
         (let $via (tg:at $message "via_bot")
           (let $header
                (tg:concat-lists (("telegram")
                                  (tg:field "update_id" (tg:str (tg:at $update "update_id")))
                                  (tg:field "kind" $kind)
                                  (tg:field "chat_id" (tg:str (tg:at $chat "id")))
                                  (tg:field "chat_type" (tg:str (tg:at $chat "type")))
                                  (tg:field "chat_title" (tg:display-chat $chat))
                                  (tg:field "message_id" (tg:str (tg:at $message "message_id")))
                                  (tg:field "sent_at" (tg:clock (tg:str (tg:at $message "date"))))
                                  (tg:field "edited_at" (tg:clock (tg:str (tg:at $message "edit_date"))))
                                  (tg:field "thread_id" (tg:str (tg:at $message "message_thread_id")))
                                  (tg:flag "is_topic" (tg:truthy (tg:at $message "is_topic_message")))
                                  (tg:field "from" (tg:display-user $sender))
                                  (tg:field "from_id" (tg:str (tg:at $sender "id")))
                                  (tg:flag "from_is_bot" (tg:truthy (tg:at $sender "is_bot")))
                                  (tg:field "sender_chat" (tg:display-chat $sender-chat))
                                  (tg:field "sender_chat_id" (tg:str (tg:at $sender-chat "id")))
                                  (tg:field "via_bot" (tg:display-user $via))
                                  (tg:flag "automatic_forward" (tg:truthy (tg:at $message "is_automatic_forward")))
                                  (tg:forward-fields $message)
                                  (tg:reply-fields $message)))
             (let $line (str:join " " (tg:list $header))
               (format-args "[{}]\n{}" ($line $text)))))))))

;; -------------------------------------------------------------- ledger
;; The append-only conversation ledger, one JSON object per line, in the
;; format the Python readers (conversation window, recent activity) expect.

(= (tg:ledger-append $record)
   (let $path (tg:ledger)
     (if (== $path "") True
       (let $line (json-stringify $record)
         (let $done (fs:append-text $path (str:concat $line "\n")) True)))))

(= (tg:log-update $update $kind $message $allowed $queued $note)
   (let $chat (tg:at $message "chat")
     (let $sender (tg:at $message "from")
       (let $stamp (tg:now-iso)
         (tg:ledger-append
           (JsonObject ((JsonPair "received_at" (JsonString $stamp))
                        (JsonPair "update_id" (tg:at $update "update_id"))
                        (JsonPair "kind" (JsonString $kind))
                        (JsonPair "allowed" (tg:jbool $allowed))
                        (JsonPair "queued" (tg:jbool $queued))
                        (JsonPair "note" (JsonString $note))
                        (JsonPair "chat_id" (JsonString (tg:str (tg:at $chat "id"))))
                        (JsonPair "chat_type" (JsonString (tg:str (tg:at $chat "type"))))
                        (JsonPair "chat_title" (JsonString (tg:display-chat $chat)))
                        (JsonPair "message_id" (tg:at $message "message_id"))
                        (JsonPair "from" (JsonString (tg:display-user $sender)))
                        (JsonPair "from_id" (JsonString (tg:str (tg:at $sender "id"))))
                        (JsonPair "from_is_bot" (tg:jbool (tg:truthy (tg:at $sender "is_bot"))))
                        (JsonPair "text" (if $allowed (tg:at $message "text") JsonNull))
                        (JsonPair "caption" (if $allowed (tg:at $message "caption") JsonNull))
                        (JsonPair "raw" (if $allowed $update JsonNull)))))))))

(= (tg:log-outbound $chat $text $message-id)
   (let $stamp (tg:now-iso)
     (let $title (tg:chat-title $chat)
       (tg:ledger-append
         (JsonObject ((JsonPair "received_at" (JsonString $stamp))
                      (JsonPair "kind" (JsonString "outbound"))
                      (JsonPair "allowed" (tg:jbool True))
                      (JsonPair "queued" (tg:jbool False))
                      (JsonPair "note" (JsonString "own_send"))
                      (JsonPair "chat_id" (JsonString $chat))
                      (JsonPair "chat_title" (JsonString $title))
                      (JsonPair "from" (JsonString "me"))
                      (JsonPair "from_is_bot" (tg:jbool True))
                      (JsonPair "message_id" (tg:jnum $message-id))
                      (JsonPair "text" (JsonString $text))))))))

(= (tg:log-own-delete $chat $message-id $note)
   (let $stamp (tg:now-iso)
     (tg:ledger-append
       (JsonObject ((JsonPair "received_at" (JsonString $stamp))
                    (JsonPair "kind" (JsonString "outbound_delete"))
                    (JsonPair "allowed" (tg:jbool True))
                    (JsonPair "queued" (tg:jbool False))
                    (JsonPair "note" (JsonString $note))
                    (JsonPair "chat_id" (JsonString $chat))
                    (JsonPair "from" (JsonString "me"))
                    (JsonPair "from_is_bot" (tg:jbool True))
                    (JsonPair "message_id" (tg:jnum $message-id))
                    (JsonPair "text" JsonNull))))))

(= (tg:chat-title $chat)
   (case (collapse (match &self (tg:title $chat $title) $title))
     ((($title) $title)
      ($other $chat))))

(= (tg:remember-title $chat $title)
   (if (== $title "") ()
     (let $old (collapse (match &self (tg:title $chat $t) $t))
       (let $gone (tg:drop-titles $chat $old)
         (let $added (add-atom &self (tg:title $chat $title))
           (py-call (telegram.metta_publish "title" (format-args "{}:{}" ($chat $title)))))))))
(= (tg:drop-titles $chat $titles)
   (if (== $titles ()) ()
     (let ($head $tail) (tg:uncons $titles)
       (let $gone (remove-atom &self (tg:title $chat $head)) (tg:drop-titles $chat $tail)))))

;; ------------------------------------------------------------- energy
;; Per-sender arming tiers, in the JSON file the operator's /energy menu and
;; Lila's energy skills both edit.

(= (tg:energy-path) (tg:env "METTACLAW_ENERGY_PATH" "memory/energy.json"))

(= (tg:energy)
   (let $path (tg:energy-path)
     (if (py-call (os.path.exists $path))
       (case (json-parse (fs:read-text $path))
         (((JsonObject $pairs) (JsonObject $pairs))
          ($other (JsonObject ()))))
       (JsonObject ()))))

(= (tg:tier? $tier) (tg:member $tier ("full" "mid" "light")))

(= (tg:default-tier)
   (let $d (tg:str (tg:at (tg:energy) "default"))
     (if (tg:tier? $d) $d "full")))

(= (tg:tier-for $sender-id)
   (let $t (tg:str (tg:at (tg:at (tg:energy) "senders") $sender-id))
     (if (tg:tier? $t) $t (tg:default-tier))))

(= (tg:tier-loops $tier)
   (let $override (tg:str (tg:at (tg:at (tg:energy) "tier_loops") $tier))
     (if (not (== $override ""))
       (let $n (parse $override) (if (< $n 1) 1 $n))
       (let $name (case $tier (("mid" "METTACLAW_LOOPS_MID") ("light" "METTACLAW_LOOPS_LIGHT") ($f "METTACLAW_LOOPS_FULL")))
         (let $default (case $tier (("mid" "30") ("light" "10") ($f "50")))
           (let $n (parse (tg:env $name $default)) (if (< $n 1) 1 $n)))))))

;; ----------------------------------------------------------- activity

(= (tg:activity-add $task $chat $text $from-bot $tier $update-id $wake)
   (let $seq (tg:next-number activity-seq)
     (let $added (add-atom &self (tg:pending $seq $task $chat $text $from-bot $tier $update-id))
       (let $epoch (tg:next-number activity-epoch)
         (let $published (py-call (telegram.metta_publish "activity_epoch" $epoch))
           (if (== $wake False) True (tg:wake-request $wake)))))))

(= (tg:pending-items)
   (collapse (match &self (tg:pending $seq $task $chat $text $bot $tier $uid)
               ($seq $task $chat $text $bot $tier $uid))))

(= (tg:prepared-items)
   (let $upto (tg:get prepared-upto 0)
     (tg:upto (tg:pending-items) $upto)))
(= (tg:upto $items $limit)
   (if (== $items ()) ()
     (let ($head $tail) (tg:uncons $items)
       (let $rest (tg:upto $tail $limit)
         (let ($seq $task $chat $text $bot $tier $uid) $head
           (if (<= $seq $limit) (cons-atom $head $rest) $rest))))))

(= (tg:sorted-items $items) (sort-atom $items))

(= (tg:texts $items)
   (if (== $items ()) ()
     (let ($head $tail) (tg:uncons $items)
       (let ($seq $task $chat $text $bot $tier $uid) $head
         (let $rest (tg:texts $tail) (cons-atom $text $rest))))))

(= (tg:update-ids $items)
   (if (== $items ()) ()
     (let ($head $tail) (tg:uncons $items)
       (let ($seq $task $chat $text $bot $tier $uid) $head
         (let $rest (tg:update-ids $tail)
           (if (== $uid "") $rest (cons-atom $uid $rest)))))))

; Reply routing and arming follow the newest human message, else the newest
; message; a batch of runtime events only arms a burst.
(= (tg:route-batch $items $human $newest $runtime)
   (if (== $items ())
     (if (not (== $human ())) $human
       (if (not (== $newest ())) $newest
         (if (not (== $runtime ())) (runtime $runtime) ())))
     (let ($head $tail) (tg:uncons $items)
       (let ($seq $task $chat $text $bot $tier $uid) $head
         (if (== $chat "runtime")
           (tg:route-batch $tail $human $newest $tier)
           (tg:route-batch $tail (if $bot $human ($chat $bot $tier)) ($chat $bot $tier) $runtime))))))

(= (tg:ledger-size)
   (let $path (tg:ledger)
     (if (== $path "") 0
       (if (py-call (os.path.exists $path)) (py-call (os.path.getsize $path)) 0))))

(= (tg:activity-batch)
   (let $polled (tg:poll)
     (let $prepared (tg:prepared-items)
       (let $items
            (if (not (== $prepared ())) (tg:sorted-items $prepared)
              (let $pending (tg:sorted-items (tg:pending-items))
                (if (== $pending ()) ()
                  (let ($last) (tg:last-seq $pending)
                    (let $set (tg:set prepared-upto $last)
                      (let $frontier (tg:ledger-size)
                        (let $ids (str:join "," (tg:list (tg:update-ids $pending)))
                          (let $epoch (tg:get activity-epoch 0)
                            (let $p1 (py-call (telegram.metta_publish "context_frontier" $frontier))
                              (let $p2 (py-call (telegram.metta_publish "batch_update_ids" $ids))
                                (let $p3 (py-call (telegram.metta_publish "context_epoch" $epoch))
                                  $pending)))))))))))
         (if (== $items ())
           (let $a (tg:set last-human 0)
             (let $b (tg:set last-tier "full")
               (let $frontier (tg:ledger-size)
                 (let $p1 (py-call (telegram.metta_publish "context_frontier" $frontier))
                   (let $p2 (py-call (telegram.metta_publish "batch_update_ids" ""))
                     (let $epoch (tg:get activity-epoch 0)
                       (let $p3 (py-call (telegram.metta_publish "context_epoch" $epoch)) "")))))))
           (let $routed (tg:route-batch $items () () ())
             (let $applied (tg:apply-route $routed)
               (let $published (tg:publish-counts)
                 (str:join "\n" (tg:list (tg:texts $items)))))))))))

(= (tg:last-seq $items)
   (let ($head $tail) (tg:uncons $items)
     (let ($seq $task $chat $text $bot $tier $uid) $head
       (if (== $tail ()) ($seq) (tg:last-seq $tail)))))

(= (tg:apply-route $routed)
   (case $routed
     ((() True)
      ((runtime $tier)
       (let $a (tg:set last-human 1) (let $b (tg:set last-tier $tier) True)))
      (($chat $bot $tier)
       (let $a (tg:set reply-chat $chat)
         (let $p (py-call (telegram.metta_publish "reply_chat" $chat))
           (let $b (tg:set last-human (if $bot 0 1))
             (let $c (tg:set last-tier (if $bot "full" $tier)) True))))))))

(= (tg:ack-activity-batch)
   (let $prepared (tg:sorted-items (tg:prepared-items))
     (if (== $prepared ()) 1
       (if (tg:ack-all $prepared)
         (let $receipt (tg:log-activity-ack (tg:list (tg:update-ids $prepared)))
         (let $gone (tg:forget-items $prepared)
           (let $reset (tg:set prepared-upto 0)
             (let $p (py-call (telegram.metta_publish "batch_update_ids" ""))
               (let $c (tg:publish-counts) 1)))))
         0))))

; The Python client's acknowledgement record, so either client, and a
; switch between them, reads the ledger the same way.
(= (tg:log-activity-ack $ids)
   (if (== $ids ()) True
     (let $stamp (tg:now-iso)
       (tg:ledger-append
         (JsonObject ((JsonPair "received_at" (JsonString $stamp))
                      (JsonPair "kind" (JsonString "activity_ack"))
                      (JsonPair "update_ids" (JsonArray (tg:list (tg:json-strings $ids))))))))))
(= (tg:json-strings $items)
   (if (== $items ()) ()
     (let ($head $tail) (tg:uncons $items)
       (let $rest (tg:json-strings $tail) (cons-atom (JsonString $head) $rest)))))

(= (tg:ack-all $items)
   (if (== $items ()) True
     (let ($head $tail) (tg:uncons $items)
       (let ($seq $task $chat $text $bot $tier $uid) $head
         (if (if (== $task "") True (tg:acknowledge $task))
           (tg:ack-all $tail)
           False)))))

(= (tg:forget-items $items)
   (if (== $items ()) ()
     (let ($head $tail) (tg:uncons $items)
       (let ($seq $task $chat $text $bot $tier $uid) $head
         (let $gone (remove-atom &self (tg:pending $seq $task $chat $text $bot $tier $uid))
           (let $unseen (tg:unsee $task) (tg:forget-items $tail)))))))

(= (tg:pending-count) (size-atom (tg:pending-items)))
(= (tg:prepared-count) (size-atom (tg:prepared-items)))

(= (tg:publish-counts)
   (let $p (tg:pending-count)
     (let $q (tg:prepared-count)
       (let $a (py-call (telegram.metta_publish "pending_count" $p))
         (py-call (telegram.metta_publish "prepared_count" $q))))))

(= (tg:last-message-is-human) (tg:get last-human 0))
(= (tg:last-message-arm-loops)
   (let $tier (tg:get last-tier "full")
     (tg:tier-loops (if (tg:tier? $tier) $tier "full"))))

;; ---------------------------------------------------------- the service

(= (tg:seen? $task) (== (collapse (match &self (tg:seen $task) True)) (True)))
(= (tg:see $task) (add-atom &self (tg:seen $task)))
(= (tg:unsee $task)
   (if (== $task "") () (remove-atom &self (tg:seen $task))))

; Read every task not yet seen and act on it. Messages stay pending until
; their turn is acknowledged; everything else is answered here.
(= (tg:poll)
   (let $tasks (tg:tasks-after "" 256)
     (let $done (tg:handle-tasks $tasks)
       (let $events (tg:drain-runtime-events)
         (let $now (tg:now)
           (py-call (telegram.metta_publish "last_poll" $now)))))))

(= (tg:handle-tasks $tasks)
   (if (== $tasks ()) ()
     (let ($head $tail) (tg:uncons $tasks)
       (let ($task $body) $head
         (let $done (if (tg:seen? $task) () (tg:handle $task (json-parse $body)))
           (tg:handle-tasks $tail))))))

(= (tg:handle $task $value)
   (case $value
     (((JsonArray ((JsonString "input") (JsonString $lane) (JsonString $kind) (JsonString $role) $update))
       (let $seen (tg:see $task) (tg:intake $task $lane $kind $role $update)))
      ((JsonArray ((JsonString "delivery") (JsonString $key) (JsonNumber $pos) (JsonNumber $count) $result))
       (let $position (parse $pos)
         (let $outcome (tg:result $result)
           (let $r (if (tg:own-key? $key) (add-atom &self (tg:receipt $key $position $outcome))
                     (py-call (telegram.metta_foreign_receipt (json-stringify $value))))
             (tg:acknowledge $task)))))
      ((JsonArray ((JsonString "rejected") (JsonString $key) (JsonString $reason)))
       (let $r (if (tg:own-key? $key) (add-atom &self (tg:receipt $key -1 (rejected $reason)))
                 (py-call (telegram.metta_foreign_receipt (json-stringify $value))))
         (tg:acknowledge $task)))
      ((JsonArray ((JsonString "released") (JsonString $lane) (JsonString $key) (JsonNumber $pos)))
       (let $position (parse $pos)
         (let $r (if (tg:own-key? $key) (add-atom &self (tg:receipt $key $position (released)))
                   (py-call (telegram.metta_foreign_receipt (json-stringify $value))))
           (tg:acknowledge $task))))
      ((JsonArray ((JsonString "command") (JsonString $key) (JsonString $name) (JsonString $args) (JsonString $lane)))
       (let $seen (tg:see $task) (tg:command $task $name $args $lane)))
      ((JsonArray ((JsonString "input-too-large") (JsonString $lane) (JsonString $kind) (JsonString $role)))
       (tg:acknowledge $task))
      ($other (tg:acknowledge $task)))))

(= (tg:own-key? $key) (== (collapse (match &self (tg:own-key $key) True)) (True)))

(= (tg:result $value)
   (case $value
     (((JsonArray ((JsonString "delivered") (JsonNumber $id))) (delivered $id))
      ((JsonArray ((JsonString "failed") (JsonNumber $code))) (failed $code))
      ((JsonArray ((JsonString "not-sent"))) (not-sent))
      ((JsonArray ((JsonString "uncertain") (JsonString $why))) (uncertain $why))
      ($other (uncertain "unreadable")))))

;; --------------------------------------------------------------- intake

(= (tg:message-of $update)
   (let $m (tg:at $update "message")
     (if (tg:truthy $m) ("message" $m)
       (let $e (tg:at $update "edited_message")
         (if (tg:truthy $e) ("edited_message" $e)
           (let $c (tg:at $update "channel_post")
             (if (tg:truthy $c) ("channel_post" $c)
               (let $ec (tg:at $update "edited_channel_post")
                 (if (tg:truthy $ec) ("edited_channel_post" $ec) ("unsupported" JsonNull))))))))))

; Operator controls the service does not answer itself (the button menus,
; and commands addressed with @bot) are Python's, as before.
(= (tg:local-control? $text $sender-id)
   (if (not (str:starts-with $text "/")) False
     (let $head (car-atom (str:split-whitespace $text))
       (let $name (car-atom (str:split "@" $head))
         (and (tg:member $name ("/start" "/stop" "/model" "/models" "/mode" "/modes" "/engine" "/engines"
                                "/fuel" "/fuels" "/quota" "/wake" "/energy" "/health" "/activity"
                                "/delete" "/claude_code_authorization"))
              (or (tg:operator? $sender-id) (> (size-atom (str:split "@" $head)) 1)))))))

(= (tg:intake $task $lane $kind $role $update)
   (if (tg:truthy (tg:at $update "callback_query"))
     (let $note (py-call (telegram.metta_callback_query (json-stringify $update)))
       (let $message (tg:at (tg:at $update "callback_query") "message")
         (let $l (tg:log-update $update "callback_query" $message True False $note)
           (tg:acknowledge $task))))
     (let ($mkind $message) (tg:message-of $update)
       (if (== $mkind "unsupported")
         (let $l (tg:log-update $update $mkind JsonNull False False "unsupported_update") (tg:acknowledge $task))
         (let $chat (tg:at $message "chat")
           (let $chat-id (tg:str (tg:at $chat "id"))
             (let $t (tg:remember-title $chat-id (tg:display-chat $chat))
               (let $text (tg:message-text $message)
                 (let $sender (tg:at $message "from")
                   (let $sender-id (tg:str (tg:at $sender "id"))
                     (if (and (not (== $text "")) (tg:local-control? $text $sender-id))
                       (let $note (py-call (telegram.metta_slash_command (json-stringify $update) $mkind))
                         (let $l (tg:log-update $update $mkind $message True False $note) (tg:acknowledge $task)))
                       (if (py-call (telegram.metta_has_attachment (json-stringify $message)))
                         (let $w (tg:wake-for $sender-id $chat-id)
                           (let $l (tg:log-update $update $mkind $message True False "attachment_dispatched")
                             (let $d (py-call (telegram.metta_attachment (json-stringify $update) $mkind $text))
                               (tg:acknowledge $task))))
                         (if (== $text "")
                           (let $l (tg:log-update $update $mkind $message True False "no_text_or_caption") (tg:acknowledge $task))
                           (let $l (tg:log-update $update $mkind $message True True "")
                             (let $formatted (tg:format-message $update $mkind $message $text)
                               (let $bot (tg:truthy (tg:at $sender "is_bot"))
                                 (let $tier (tg:tier-for $sender-id)
                                   (let $wake (tg:wake-reason-for $sender-id)
                                     (let $added (tg:activity-add $task $chat-id $formatted $bot $tier (tg:str (tg:at $update "update_id")) $wake)
                                       (let $notice (if (== $wake False) (tg:maybe-rest-notice $chat-id $sender-id) ())
                                         (tg:publish-counts)))))))))))))))))))))

(= (tg:wake-reason-for $sender-id)
   (if (tg:operator? $sender-id) "operator message"
     (if (and (not (== $sender-id "")) (tg:wake-peer? $sender-id)) "peer message" False)))

(= (tg:wake-for $sender-id $chat-id)
   (let $wake (tg:wake-reason-for $sender-id)
     (if (== $wake False) (tg:maybe-rest-notice $chat-id $sender-id) (tg:wake-request $wake))))

;; Runtime events and finished attachments, queued by Python threads.
(= (tg:drain-runtime-events)
   (let $lines (py-call (telegram.metta_take_runtime_events))
     (tg:runtime-events (json-parse $lines))))
(= (tg:runtime-events $value)
   (case $value
     (((JsonArray $items) (tg:runtime-items $items))
      ($other ()))))
(= (tg:runtime-items $items)
   (if (== $items ()) ()
     (let ($head $tail) (tg:uncons $items)
       (let $only (tg:str (tg:at $head "wake_only"))
       (if (not (== $only "")) (let $w (tg:wake-request $only) (tg:runtime-items $tail))
       (let $chat (tg:str (tg:at $head "chat"))
         (let $text (tg:str (tg:at $head "text"))
           (let $bot (tg:truthy (tg:at $head "from_bot"))
             (let $tier (tg:str (tg:at $head "tier"))
               (let $wake (tg:str (tg:at $head "wake"))
                 (let $added (tg:activity-add "" $chat $text $bot (if (tg:tier? $tier) $tier "full")
                                              (tg:str (tg:at $head "update_id"))
                                              (if (== $wake "") False $wake))
                   (tg:runtime-items $tail))))))))))))

;; ----------------------------------------------------------------- rest

(= (tg:wake-request $reason)
   (let $a (tg:set wake-reason $reason) True))

(= (tg:resting?) (> (tg:get sleep-until 0) (tg:now)))

(= (tg:maybe-rest-notice $chat-id $sender-id)
   (if (and (tg:resting?) (and (tg:operator? $sender-id) (== (tg:get rest-notice 0) 0)))
     (let $set (tg:set rest-notice 1)
       (let $left (- (tg:get sleep-until 0) (tg:now))
         (let $text (py-call (helper.rest_notice_text $left))
           (tg:send $text $chat-id))))
     ()))

(= (tg:sleep-until-message $seconds)
   (let $n (if (< $seconds 0) 0 $seconds)
     (let $deadline (+ (tg:now) $n)
       (let $a (tg:set wake-reason "")
         (let $b (tg:set rest-notice 0)
           (let $c (tg:set sleep-until $deadline)
             (let $p (py-call (telegram.metta_publish "sleep_until" $deadline))
               (let $result (tg:rest-loop $deadline $n)
                 (let $d (tg:set sleep-until 0)
                   (let $q (py-call (telegram.metta_publish "sleep_until" 0))
                     (let $e (tg:set wake-reason "") $result)))))))))))

(= (tg:rest-loop $deadline $seconds)
   (let $polled (tg:poll)
     (let $reason (tg:get wake-reason "")
       (if (not (== $reason "")) (format-args "woken by {}" ($reason))
         (if (>= (tg:now) $deadline) (format-args "rested {}s" ($seconds))
           (let $slept (tg:sleep 0.25) (tg:rest-loop $deadline $seconds)))))))

;; ----------------------------------------------------------------- send

(= (tg:reply-target $chat)
   (if (not (== $chat "")) $chat
     (let $primary (tg:primary)
       (if (not (== $primary "")) $primary (tg:get reply-chat "")))))

(= (tg:chat-allowed? $chat)
   (let $allowed (tg:allowed-chats)
     (or (tg:csv-empty? $allowed) (or (tg:csv-member? $chat $allowed) (== $chat (tg:primary))))))

(= (tg:next-key $chat)
   (let $now (py-call (time.time_ns))
     (let $last (tg:get last-sequence 0)
       (let $sequence (if (> $now $last) $now (+ $last 1))
         (let $set (tg:set last-sequence $sequence)
           (let $padded (py-call (helper.pad20 $sequence))
             (format-args "{}.0.{}" ($chat $padded))))))))

; Telegram-sized pieces, preferring line boundaries.
(= (tg:chunks $text)
   (if (<= (str:length $text) 4096) (if (== $text "") () ($text))
     (let $window (str:slice $text 0 4097)
       (let $cut (tg:last-newline $window 4096)
         (let $at (if (<= $cut 0) 4096 $cut)
           (let $piece (str:slice $text 0 $at)
             (let $rest (str:slice $text $at (str:length $text))
               (let $rest2 (if (str:starts-with $rest "\n") (str:slice $rest 1 (str:length $rest)) $rest)
                 (let $more (tg:chunks $rest2) (cons-atom $piece $more))))))))))
(= (tg:last-newline $text $from)
   (if (< $from 0) -1
     (if (== (str:slice $text $from (+ $from 1)) "\n") $from (tg:last-newline $text (- $from 1)))))

(= (tg:submit $key $body $deadline)
   (case (tg:call 4 $key $body)
     (((cwp:reply 66 $n $b) stored)
      ((cwp:reply 71 $n $b) (tg:submit-later $key $body $deadline))
      ((cwp:reply 72 $n $b) (tg:submit-later $key $body $deadline))
      ((cwp:unavailable $why) (tg:submit-later $key $body $deadline))
      ((cwp:reply $code $n $b) (refused $code)))))
(= (tg:submit-later $key $body $deadline)
   (if (>= (tg:now) $deadline) queued
     (let $slept (tg:sleep 0.2) (tg:submit $key $body $deadline))))

(= (tg:receipts $key $count)
   (let $rejected (collapse (match &self (tg:receipt $key -1 $r) $r))
     (if (not (== $rejected ())) (car-atom $rejected)
       (tg:receipt-list $key 0 $count))))
(= (tg:receipt-list $key $pos $count)
   (if (>= $pos $count) ()
     (let $found (collapse (match &self (tg:receipt $key $pos $r) $r))
       (let $rest (tg:receipt-list $key (+ $pos 1) $count)
         (cons-atom (if (== $found ()) none (car-atom $found)) $rest)))))
(= (tg:all-received $results)
   (if (== $results ()) True
     (let ($head $tail) (tg:uncons $results)
       (if (== $head none) False (tg:all-received $tail)))))

(= (tg:await $key $count $deadline)
   (let $polled (tg:poll)
     (let $results (tg:receipts $key $count)
       (case $results
         (((rejected $reason) (rejected $reason))
          ($list
           (if (tg:all-received $list) $list
             (if (>= (tg:now) $deadline) $list
               (let $slept (tg:sleep 0.1) (tg:await $key $count $deadline))))))))))

(= (tg:batch-body $commands) (json-stringify (JsonArray (tg:list $commands))))
(= (tg:send-commands $pieces)
   (if (== $pieces ()) ()
     (let ($head $tail) (tg:uncons $pieces)
       (let $rest (tg:send-commands $tail)
         (cons-atom (JsonArray ((JsonString "send") (JsonString $head) (JsonString "plain"))) $rest)))))

(= (tg:send $text $chat)
   (let $target (tg:reply-target $chat)
     (if (== $target "") "send failed: missing token or chat id"
       (if (not (tg:chat-allowed? $target)) "send failed: target chat is not allowed"
         (let $body (tg:unescape-newlines $text)
           (let $pieces (tg:chunks $body)
             (if (== $pieces ()) "send failed: empty message"
               (let $key (tg:next-key $target)
                 (let $deadline (+ (tg:now) (/ (tg:timeout-ms) 1000))
                   (let $mine (add-atom &self (tg:own-key $key))
                   (let $stored (tg:submit $key (tg:batch-body (tg:send-commands $pieces)) $deadline)
                     (case $stored
                       ((queued (format-args "send queued: the Telegram service is not answering; retry later ({})" ($key)))
                        ((refused $code) (format-args "send failed: the Telegram service refused it ({})" ($code)))
                        (stored
                         (let $results (tg:await $key (size-atom $pieces) $deadline)
                           (tg:send-outcome $key $target $pieces $results 0 ()))))))))))))))))

(= (tg:unescape-newlines $text) (str:join "\n" (str:split "\\n" $text)))

(= (tg:send-outcome $key $target $pieces $results $pos $ids)
   (case $results
     (((rejected $reason) (format-args "send failed: the Telegram service rejected it ({})" ($reason)))
      (()
       (let $first (car-atom $ids)
         (if (== (size-atom $ids) 1)
           (format-args "sent message {} to chat {}" ($first $target))
           (let $joined (str:join ", " (tg:list $ids))
             (let $n (size-atom $ids)
               (format-args "sent message {} to chat {} (in {} parts: {})" ($first $target $n $joined)))))))
      ($list
       (let ($head $tail) (tg:uncons $list)
         (let $piece (tg:nth $pieces $pos)
           (case $head
             ((none (format-args "send accepted by the Telegram service; delivery is still pending ({})" ($key)))
              ((delivered $id)
               (let $logged (tg:log-outbound $target $piece $id)
                 (let $more (tg:append-item $ids $id)
                   (tg:send-outcome $key $target $pieces $tail (+ $pos 1) $more))))
              ((failed $code) (format-args "send failed: Telegram rejected {}" ($code)))
              ((not-sent) "send failed: the message was not sent")
              ((uncertain $why)
               (format-args "send uncertain ({}): Telegram may or may not have it; this chat holds later messages until an operator resolves it ({})" ($why $key)))
              ((released) (format-args "send uncertain (released): an operator released this chat; the message may or may not have arrived ({})" ($key)))))))))))

(= (tg:nth $items $n)
   (let ($head $tail) (tg:uncons $items)
     (if (== $n 0) $head (tg:nth $tail (- $n 1)))))
(= (tg:append-item $items $x) (tg:append $items ($x)))

; A model-authored send goes out at most once per cognitive turn.
(= (tg:send-effect $text $chat)
   (let $target (tg:reply-target $chat)
     (let $body (tg:unescape-newlines $text)
       (let $turn (py-call (telegram.metta_effect_turn))
         (if (== (collapse (match &self (tg:effect-sent $turn $target $body) True)) (True))
           "duplicate send suppressed"
           (let $marked (add-atom &self (tg:effect-sent $turn $target $body))
             (tg:send $body $target)))))))

;; --------------------------------------------------------------- delete

(= (tg:delete $chat $message-id)
   (let $target $chat
     (if (not (tg:chat-allowed? $target)) "delete refused: target chat is not allowed"
       (let $key (tg:next-key $target)
         (let $deadline (+ (tg:now) (/ (tg:timeout-ms) 1000))
           (let $mine (add-atom &self (tg:own-key $key))
           (let $id (tg:jnum $message-id)
             (case (tg:submit $key (tg:batch-body ((JsonArray ((JsonString "delete") $id)))) $deadline)
               ((queued "delete queued: the Telegram service is not answering")
                ((refused $code) (format-args "delete failed: the Telegram service refused it ({})" ($code)))
                (stored
                 (case (tg:await $key 1 $deadline)
                   (((rejected $reason) (format-args "delete failed: the Telegram service rejected it ({})" ($reason)))
                    ((none) "delete accepted by the Telegram service; still pending")
                    (((delivered $x))
                     (let $l (tg:log-own-delete $target $message-id "own_delete")
                       (format-args "deleted message {} from chat {}" ($message-id $target))))
                    (((failed "400"))
                     (let $l (tg:log-own-delete $target $message-id "own_delete_terminal")
                       (format-args "cannot delete message {}: it is older than 48h, or a forward (whoever forwarded it must delete it), or not the bot's own message" ($message-id))))
                    (($other) (format-args "delete failed: {}" ($other)))))))))))))))

; Own sends to a chat, oldest first, less those already deleted.
(= (tg:own-sends $chat)
   (let $path (tg:ledger)
     (if (or (== $path "") (not (py-call (os.path.exists $path)))) ()
       (tg:live-sends (tg:own-records (fs:read-lines $path) $chat () ()) ))))
(= (tg:own-records $lines $chat $sent $deleted)
   (if (== $lines ()) ($sent $deleted)
     (let ($line $rest) (tg:uncons $lines)
       (if (== (str:find $line "\"own_") (TextNotFound "\"own_")) (tg:own-records $rest $chat $sent $deleted)
         (let $r (json-parse $line)
           (if (not (== (tg:str (tg:at $r "chat_id")) $chat)) (tg:own-records $rest $chat $sent $deleted)
             (let $note (tg:str (tg:at $r "note"))
               (let $id (tg:str (tg:at $r "message_id"))
                 (if (and (== $note "own_send") (not (== $id "")))
                   (tg:own-records $rest $chat (tg:append-item $sent $id) $deleted)
                   (if (or (== $note "own_delete") (== $note "own_delete_terminal"))
                     (tg:own-records $rest $chat $sent (cons-atom $id $deleted))
                     (tg:own-records $rest $chat $sent $deleted)))))))))))
(= (tg:live-sends $pair)
   (let ($sent $deleted) $pair (tg:without $sent $deleted)))
(= (tg:without $items $drop)
   (if (== $items ()) ()
     (let ($head $tail) (tg:uncons $items)
       (let $rest (tg:without $tail $drop)
         (if (tg:member $head $drop) $rest (cons-atom $head $rest))))))

(= (tg:delete-recorded $chat $message-id)
   (let $target (tg:reply-target $chat)
     (let $wanted (format-args "{}" ($message-id))
       (if (tg:member $wanted (tg:own-sends $target))
         (tg:delete $target $message-id)
         (format-args "delete refused: no current own-send receipt for message {} in chat {}; an authenticated operator may use /delete for an explicit legacy id" ($message-id $target))))))

(= (tg:delete-my-recent $chat $count)
   (let $target (tg:reply-target $chat)
     (let $ids (tg:own-sends $target)
       (if (== $ids ())
         (format-args "no recorded own-sends to chat {} — nothing to delete (only messages sent AFTER id-capture was added can be cleaned this way)" ($target))
         (let $n (if (< $count 1) 1 (if (> $count 20) 20 $count))
           (str:join " | " (tg:list (tg:delete-each $target (tg:newest $ids $n)))))))))
(= (tg:newest $ids $n)
   (let $reversed (tg:reverse $ids ()) (tg:take $reversed $n)))
(= (tg:reverse $items $acc)
   (if (== $items ()) $acc
     (let ($head $tail) (tg:uncons $items) (tg:reverse $tail (cons-atom $head $acc)))))
(= (tg:take $items $n)
   (if (or (== $items ()) (<= $n 0)) ()
     (let ($head $tail) (tg:uncons $items)
       (let $rest (tg:take $tail (- $n 1)) (cons-atom $head $rest)))))
(= (tg:delete-each $chat $ids)
   (if (== $ids ()) ()
     (let ($head $tail) (tg:uncons $ids)
       (let $one (tg:delete $chat (parse $head))
         (let $rest (tg:delete-each $chat $tail) (cons-atom $one $rest))))))

;; ------------------------------------------------------ operator commands
;; The service asks about delegated commands; the answer is its reply.

(= (tg:command $task $name $args $lane)
   (let $chat (car-atom (str:split "." $lane))
     (let $text (tg:command-text $name $args $chat)
       (let $answered (tg:answer-task $task $text)
         (if $answered (tg:unsee $task) ())))))

(= (tg:command-text $name $args $chat)
   (case $name
     (("/wake" (let $w (tg:wake-request "/wake") "Waking."))
      ("/delete"
       (let $fields (str:split-whitespace $args)
         (if (not (== (size-atom $fields) 2)) "usage: /delete <known-chat-id-or-title> <message-id>"
           (let ($who $mid) $fields
             (let $target (py-call (telegram.metta_resolve_chat $who))
               (if (== $target "") "delete refused: chat is not in the local ledger"
                 (tg:delete $target (parse $mid))))))))
      ($other (py-call (telegram.metta_command_answer $name $args $chat))))))

;; -------------------------------------------------------------- startup

(= (tg:start)
   (if (== (tg:socket) "") "telegram disabled: the durable service socket is not configured"
     (let $a (py-call (telegram.metta_publish "client" "metta"))
       (let $b (tg:poll) "telegram client started"))))
