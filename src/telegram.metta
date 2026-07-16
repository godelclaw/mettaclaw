;; src/telegram.metta — CeTTaClaw's Telegram Bot API adapter.
;; The bot token is part of every URL, so raw transport results/errors are
;; never returned as-is: everything reduces to (HttpResult s b) or
;; TransportError. JSON parsing below is pure/offline-testable and keeps ids as
;; JSON-number strings so the receive path does not need numeric coercions.

!(import! &self http)
!(import! &self json)
!(import! &self process)
!(import! &self str)
!(import! &self fs)
!(import! &self time)
!(import! &self ./config.metta)
!(import! &self ./text.metta)

(= (claw:tg-api $method)
   (str:concat "https://api.telegram.org/bot"
     (str:concat (claw:secret "METTACLAW_TELEGRAM_BOT_TOKEN")
       (str:concat "/" $method))))

(= (claw:tg-http $method $url $body $timeout-ms)
   (case (http:request $method $url ((Header "Content-Type" "application/json"))
                       $body $timeout-ms 8388608)
     (((HttpResult $s $b) (HttpResult $s $b))
      ($other TransportError))))

;; Identity probe: (HttpResult 200 {"ok":true,"result":{...bot info...}})
(= (claw:tg-get-me)
   (claw:tg-http "GET" (claw:tg-api "getMe") "" 15000))

;; JSON-number literal for either a numeric atom or a string containing digits.
(= (claw:tg-number-literal $x)
   (claw:unquote (repr $x)))

;; Long-poll fetch; offset "" or "-1" means "no offset yet".
(= (claw:tg-get-updates $offset $timeout-s)
   (let $offset-text (str:trim (claw:tg-number-literal $offset))
   (let $base (str:concat (claw:tg-api "getUpdates")
                          (str:concat "?timeout=" (repr $timeout-s)))
   (let $url (if (or (== $offset-text "") (== $offset-text "-1"))
                 $base
                 (str:concat $base (str:concat "&offset=" $offset-text)))
        (claw:tg-http "GET" $url "" (* 1000 (+ $timeout-s 10)))))))

(= (claw:tg-send-body $chat-id $text)
   (json-stringify
     (JsonObject
       ((JsonPair "chat_id" (JsonNumber (claw:tg-number-literal $chat-id)))
        (JsonPair "text" (JsonString $text))))))

(= (claw:tg-send $chat-id $text)
   (claw:tg-http "POST" (claw:tg-api "sendMessage")
                 (claw:tg-send-body $chat-id $text)
                 30000))

;; ---- pure update parsing --------------------------------------------------
;; Parsed shape:
;;   (TgMessage $update-id $chat-id $sender $text $kind)
;; where $sender is human or bot, $kind is message/edited_message/channel_post.

(= (claw:json-get $object $key)
   (case $object
     (((JsonObject $pairs) (json-object-get (JsonObject $pairs) $key))
      ($other JsonNull))))

(= (claw:json-string-or-empty $value)
   (case $value
     (((JsonString $text) $text)
      ($other ""))))

(= (claw:json-number-or-empty $value)
   (case $value
     (((JsonNumber $text) $text)
      ((JsonString $text) $text)
      ($other ""))))

(= (claw:json-bool-or-false $value)
   (case $value
     (((JsonBool True) True)
      ($other False))))

(= (claw:json-string-or-null $text)
   (if (== $text "") JsonNull (JsonString $text)))

(= (claw:json-number-or-null $text)
   (if (== $text "") JsonNull (JsonNumber $text)))

(= (claw:tg-list-last $items)
   (if (== $items ())
       JsonNull
       (let ($head $tail) (decons-atom $items)
            (if (== $tail ()) $head (claw:tg-list-last $tail)))))

;; ---- pettaclaw-compatible message display ---------------------------------
;; The Python bridge queues a rich text block, not just message text:
;;   [telegram update_id="..." chat_id="..." from_id="..." ...]
;;   body
;; That header is what gives the model source/provenance context.

(= (claw:tg-compact $text)
   (str:trim
     (claw:str-replace-all
       (claw:str-replace-all $text "\r" " ")
       "\n" " ")))

(= (claw:tg-json-field $key $value)
   (let $v (claw:tg-compact $value)
        (if (== $v "")
            ""
            (str:concat $key
              (str:concat "=" (json-stringify (JsonString $v)))))))

(= (claw:tg-bool-field $key $value)
   (str:concat $key (if $value "=true" "=false")))

(= (claw:tg-header-join-loop $items $acc)
   (if (== $items ())
       $acc
       (let ($head $tail) (decons-atom $items)
            (if (== $head "")
                (claw:tg-header-join-loop $tail $acc)
                (if (== $acc "")
                    (claw:tg-header-join-loop $tail $head)
                    (claw:tg-header-join-loop
                      $tail (str:concat $acc (str:concat " " $head))))))))

(= (claw:tg-header-join $items)
   (claw:tg-header-join-loop $items ""))

(= (claw:tg-display-user $user)
   (let $username (claw:json-string-or-empty (claw:json-get $user "username"))
        (if (not (== $username ""))
            (str:concat "@" $username)
            (let $first (claw:json-string-or-empty (claw:json-get $user "first_name"))
                 (if (not (== $first ""))
                     $first
                     (claw:json-number-or-empty (claw:json-get $user "id")))))))

(= (claw:tg-display-chat $chat)
   (let $title (claw:json-string-or-empty (claw:json-get $chat "title"))
        (if (not (== $title ""))
            $title
            (let $username (claw:json-string-or-empty (claw:json-get $chat "username"))
                 (if (not (== $username ""))
                     (str:concat "@" $username)
                     (let $first (claw:json-string-or-empty (claw:json-get $chat "first_name"))
                          (if (not (== $first ""))
                              $first
                              (claw:json-number-or-empty (claw:json-get $chat "id")))))))))

(= (claw:tg-message-excerpt $message)
   (claw:tg-compact (claw:tg-text $message)))

(= (claw:tg-origin-user-fields $origin $origin-type)
   (let $user (claw:json-get $origin "sender_user")
        (claw:tg-header-join
          ((claw:tg-bool-field "forwarded" True)
           (claw:tg-json-field "forward_type" $origin-type)
           (claw:tg-json-field "forward_from" (claw:tg-display-user $user))
           (claw:tg-json-field "forward_from_id"
             (claw:json-number-or-empty (claw:json-get $user "id")))
           (claw:tg-json-field "forward_message_id"
             (claw:json-number-or-empty (claw:json-get $origin "message_id")))
           (claw:tg-json-field "forward_signature"
             (claw:json-string-or-empty
               (claw:json-get $origin "author_signature")))))))

(= (claw:tg-origin-hidden-user-fields $origin $origin-type)
   (claw:tg-header-join
     ((claw:tg-bool-field "forwarded" True)
      (claw:tg-json-field "forward_type" $origin-type)
      (claw:tg-json-field "forward_from"
        (claw:json-string-or-empty (claw:json-get $origin "sender_user_name")))
      (claw:tg-json-field "forward_message_id"
        (claw:json-number-or-empty (claw:json-get $origin "message_id")))
      (claw:tg-json-field "forward_signature"
        (claw:json-string-or-empty
          (claw:json-get $origin "author_signature"))))))

(= (claw:tg-origin-chat-fields $origin $origin-type)
   (let $chat (claw:json-get $origin "sender_chat")
        (claw:tg-header-join
          ((claw:tg-bool-field "forwarded" True)
           (claw:tg-json-field "forward_type" $origin-type)
           (claw:tg-json-field "forward_from_chat" (claw:tg-display-chat $chat))
           (claw:tg-json-field "forward_from_chat_id"
             (claw:json-number-or-empty (claw:json-get $chat "id")))
           (claw:tg-json-field "forward_message_id"
             (claw:json-number-or-empty (claw:json-get $origin "message_id")))
           (claw:tg-json-field "forward_signature"
             (claw:json-string-or-empty
               (claw:json-get $origin "author_signature")))))))

(= (claw:tg-forward-origin-fields $origin)
   (let $origin-type (claw:json-string-or-empty (claw:json-get $origin "type"))
        (case $origin-type
          (("user" (claw:tg-origin-user-fields $origin $origin-type))
           ("hidden_user" (claw:tg-origin-hidden-user-fields $origin $origin-type))
           ($other (claw:tg-origin-chat-fields $origin $origin-type))))))

(= (claw:tg-json-object? $value)
   (case $value
     (((JsonObject $pairs) True)
      ($other False))))

(= (claw:tg-legacy-forward-fields $message)
   (let $legacy-user (claw:json-get $message "forward_from")
   (let $legacy-chat (claw:json-get $message "forward_from_chat")
   (let $legacy-name
        (claw:json-string-or-empty
          (claw:json-get $message "forward_sender_name"))
        (if (or (claw:tg-json-object? $legacy-user)
                (or (claw:tg-json-object? $legacy-chat)
                    (not (== $legacy-name ""))))
            (claw:tg-header-join
              ((claw:tg-bool-field "forwarded" True)
               (claw:tg-json-field "forward_from"
                 (if (claw:tg-json-object? $legacy-user)
                     (claw:tg-display-user $legacy-user)
                     $legacy-name))
               (claw:tg-json-field "forward_from_id"
                 (claw:json-number-or-empty
                   (claw:json-get $legacy-user "id")))
               (claw:tg-json-field "forward_from_chat"
                 (claw:tg-display-chat $legacy-chat))
               (claw:tg-json-field "forward_from_chat_id"
                 (claw:json-number-or-empty
                   (claw:json-get $legacy-chat "id")))
               (claw:tg-json-field "forward_signature"
                 (claw:json-string-or-empty
                   (claw:json-get $message "author_signature")))))
            (claw:tg-bool-field "forwarded" False))))))

(= (claw:tg-forward-fields $message)
   (let $origin (claw:json-get $message "forward_origin")
        (case $origin
          (((JsonObject $pairs)
            (claw:tg-forward-origin-fields (JsonObject $pairs)))
           ($other (claw:tg-legacy-forward-fields $message))))))

(= (claw:tg-external-reply-fields $message)
   (let $external (claw:json-get $message "external_reply")
        (case $external
          (((JsonObject $e)
            (claw:tg-header-join
              ((claw:tg-json-field "external_reply_origin"
                 (claw:json-string-or-empty
                   (claw:json-get (JsonObject $e) "origin")))
               (claw:tg-json-field "external_reply_excerpt"
                 (claw:tg-message-excerpt (JsonObject $e))))))
           ($other "")))))

(= (claw:tg-quote-fields $message)
   (let $quote (claw:json-get $message "quote")
        (case $quote
          (((JsonObject $q)
            (claw:tg-json-field "quote"
              (claw:json-string-or-empty
                (claw:json-get (JsonObject $q) "text"))))
           ($other "")))))

(= (claw:tg-reply-fields $message)
   (let $reply (claw:json-get $message "reply_to_message")
   (let $base
        (case $reply
          (((JsonObject $r)
            (let $sender (claw:json-get (JsonObject $r) "from")
            (let $chat (claw:json-get (JsonObject $r) "chat")
                 (claw:tg-header-join
                   ((claw:tg-bool-field "is_reply" True)
                    (claw:tg-json-field "reply_to_message_id"
                      (claw:json-number-or-empty
                        (claw:json-get (JsonObject $r) "message_id")))
                    (claw:tg-json-field "reply_to_from"
                      (claw:tg-display-user $sender))
                    (claw:tg-json-field "reply_to_from_id"
                      (claw:json-number-or-empty
                        (claw:json-get $sender "id")))
                    (claw:tg-json-field "reply_to_chat"
                      (claw:tg-display-chat $chat))
                    (claw:tg-json-field "reply_to_excerpt"
                      (claw:tg-message-excerpt (JsonObject $r))))))))
           ($other (claw:tg-bool-field "is_reply" False))))
   (let $external (claw:tg-external-reply-fields $message)
   (let $quote (claw:tg-quote-fields $message)
        (claw:tg-header-join ($base $external $quote)))))))

(= (claw:tg-format-message $update $kind $message $text)
   (let $chat (claw:json-get $message "chat")
   (let $sender (claw:json-get $message "from")
   (let $sender-chat (claw:json-get $message "sender_chat")
   (let $via-bot (claw:json-get $message "via_bot")
   (let $header
        (claw:tg-header-join
          ("telegram"
           (claw:tg-json-field "update_id"
             (claw:json-number-or-empty (claw:json-get $update "update_id")))
           (claw:tg-json-field "kind" (repr $kind))
           (claw:tg-json-field "chat_id" (claw:tg-chat-id $message))
           (claw:tg-json-field "chat_type" (claw:tg-chat-type $message))
           (claw:tg-json-field "chat_title" (claw:tg-display-chat $chat))
           (claw:tg-json-field "message_id" (claw:tg-message-id $message))
           (claw:tg-json-field "thread_id"
             (claw:json-number-or-empty
               (claw:json-get $message "message_thread_id")))
           (claw:tg-bool-field "is_topic"
             (claw:json-bool-or-false
               (claw:json-get $message "is_topic_message")))
           (claw:tg-json-field "from" (claw:tg-display-user $sender))
           (claw:tg-json-field "from_id" (claw:tg-from-id $message))
           (claw:tg-bool-field "from_is_bot" (claw:tg-from-is-bot? $message))
           (claw:tg-json-field "sender_chat" (claw:tg-display-chat $sender-chat))
           (claw:tg-json-field "sender_chat_id"
             (claw:json-number-or-empty (claw:json-get $sender-chat "id")))
           (claw:tg-json-field "via_bot" (claw:tg-display-user $via-bot))
           (claw:tg-bool-field "automatic_forward"
             (claw:json-bool-or-false
               (claw:json-get $message "is_automatic_forward")))
           (claw:tg-forward-fields $message)
           (claw:tg-reply-fields $message)))
        (str:concat "[" (str:concat $header (str:concat "]\n" $text)))))))))

(= (claw:tg-event $update)
   (let $message (claw:json-get $update "message")
        (case $message
          (((JsonObject $m) (TgEvent message (JsonObject $m)))
           ($o1
            (let $edited (claw:json-get $update "edited_message")
                 (case $edited
                   (((JsonObject $e) (TgEvent edited_message (JsonObject $e)))
                    ($o2
                     (let $channel (claw:json-get $update "channel_post")
                          (case $channel
                            (((JsonObject $c) (TgEvent channel_post (JsonObject $c)))
                             ($o3
                              (let $edited-channel
                                   (claw:json-get $update "edited_channel_post")
                                   (case $edited-channel
                                     (((JsonObject $ec)
                                       (TgEvent edited_channel_post
                                                (JsonObject $ec)))
                                      ($o4 TgNoEvent)))))))))))))))))

(= (claw:tg-text $message)
   (let $text (claw:json-string-or-empty (claw:json-get $message "text"))
        (if (== $text "")
            (claw:json-string-or-empty (claw:json-get $message "caption"))
            $text)))

(= (claw:tg-chat-id $message)
   (let $chat (claw:json-get $message "chat")
        (claw:json-number-or-empty (claw:json-get $chat "id"))))

(= (claw:tg-chat-type $message)
   (let $chat (claw:json-get $message "chat")
        (claw:json-string-or-empty (claw:json-get $chat "type"))))

(= (claw:tg-sender $message)
   (let $from (claw:json-get $message "from")
        (case (claw:json-get $from "is_bot")
          (((JsonBool True) bot)
           ((JsonBool False) human)
           ($other bot)))))

(= (claw:tg-message-id $message)
   (claw:json-number-or-empty (claw:json-get $message "message_id")))

(= (claw:tg-from-id $message)
   (let $from (claw:json-get $message "from")
        (claw:json-number-or-empty (claw:json-get $from "id"))))

(= (claw:tg-from-is-bot? $message)
   (let $from (claw:json-get $message "from")
        (claw:json-bool-or-false (claw:json-get $from "is_bot"))))

;; Rich sender for live messages: human carries the sender's user id so the
;; loop can apply per-human arm grants. Offline fixtures may keep plain human.
(= (claw:tg-sender-rich $message)
   (case (claw:tg-sender $message)
     ((human (let $id (claw:tg-from-id $message)
                  (if (== $id "") human (human $id))))
      ($other bot))))

(= (claw:tg-caption $message)
   (claw:json-string-or-empty (claw:json-get $message "caption")))

;; ---- attachments ------------------------------------------------------------
;; Files from ALLOWED chats are downloaded via getFile into a local inbox and
;; the saved path is announced in the message text the agent sees. The download
;; runs once, in the queued-message seam only — the audit pass stays pure.
;; Size is enforced twice without local numeric parsing: getFile itself refuses
;; files over the 20MB bot limit, and curl carries --max-filesize as a belt.
;; The destination filename comes from Telegram's own server path (safe
;; charset, keeps the extension), prefixed with the message id; the original
;; file_name appears only in the announcement text, never in the path.

(= (claw:tg-attachment-kinds)
   ("document" "video" "audio" "voice" "animation" "video_note" "sticker"))

(= (claw:tg-attachment-from-object $kind $item)
   (TgAttachment $kind
     (claw:json-string-or-empty (claw:json-get $item "file_id"))
     (claw:json-string-or-empty (claw:json-get $item "file_name"))
     (claw:json-string-or-empty (claw:json-get $item "mime_type"))
     (claw:json-number-or-empty (claw:json-get $item "file_size"))))

(= (claw:tg-attachment-from-kinds $message $kinds)
   (if (== $kinds ())
       (claw:tg-photo-attachment $message)
       (let ($head $tail) (decons-atom $kinds)
            (case (claw:json-get $message $head)
              (((JsonObject $fields)
                (claw:tg-attachment-from-object $head (JsonObject $fields)))
               ($other (claw:tg-attachment-from-kinds $message $tail)))))))

;; photo arrives as an array of sizes ordered smallest->largest; take the last.
(= (claw:tg-photo-attachment $message)
   (case (claw:json-get $message "photo")
     (((JsonArray $sizes)
       (if (== $sizes ())
           TgNoAttachment
           (case (claw:tg-list-last $sizes)
             (((JsonObject $fields)
               (TgAttachment "photo"
                 (claw:json-string-or-empty (claw:json-get (JsonObject $fields) "file_id"))
                 ""
                 "image/jpeg"
                 (claw:json-number-or-empty (claw:json-get (JsonObject $fields) "file_size"))))
              ($o TgNoAttachment)))))
      ($other TgNoAttachment))))

(= (claw:tg-attachment $message)
   (claw:tg-attachment-from-kinds $message (claw:tg-attachment-kinds)))

(= (claw:tg-attachments-dir)
   (let $v (claw:setting "METTACLAW_TELEGRAM_ATTACHMENTS_DIR")
        (if (== $v NotFound) "memory/attachments" $v)))

(= (claw:tg-attachment-label $kind $name $mime $size)
   (str:concat $kind
     (str:concat (if (== $name "") "" (str:concat " " $name))
       (str:concat (if (== $mime "") "" (str:concat ", " $mime))
         (if (== $size "") "" (str:concat ", " (str:concat $size "b")))))))

(= (claw:tg-get-file $file-id)
   (claw:tg-http "POST" (claw:tg-api "getFile")
     (json-stringify (JsonObject ((JsonPair "file_id" (JsonString $file-id)))))
     30000))

(= (claw:tg-file-path-from-body $body)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (case (claw:json-get (JsonObject $pairs) "result")
         (((JsonObject $r)
           (claw:json-string-or-empty (claw:json-get (JsonObject $r) "file_path")))
          ($o ""))))
      ($o2 ""))))

(= (claw:tg-file-url $remote-path)
   (str:concat "https://api.telegram.org/file/bot"
     (str:concat (claw:secret "METTACLAW_TELEGRAM_BOT_TOKEN")
       (str:concat "/" $remote-path))))

;; curl reads only the tokened URL from stdin. The non-secret destination stays
;; a distinct argv value, avoiding config-file quoting and injection concerns.
(= (claw:tg-curl-config $url)
   (str:concat "url = \"" (str:concat $url "\"\n")))

(= (claw:tg-download-file $remote-path $dest)
   (let $r (process-run-cmd-cwd-env-stdin-timeout-cap-bytes
             ("curl" "-sS" "--fail" "--remove-on-error"
              "--max-filesize" "20971520" "--output" $dest "--config" "-")
             "" ()
             (claw:tg-curl-config (claw:tg-file-url $remote-path))
             120000 65536)
        (if (process-result-timed-out? $r)
            False
            (== (process-result-exit-code $r) 0))))

(= (claw:tg-path-basename $path)
   (let $parts (str:split "/" $path)
        (if (== $parts ()) $path (claw:tg-list-last $parts))))

(= (claw:tg-attachment-note $message)
   (case (claw:tg-attachment $message)
     ((TgNoAttachment "")
      ((TgAttachment $kind $file-id $name $mime $size)
       (let $label (claw:tg-attachment-label $kind $name $mime $size)
            (if (== $file-id "")
                (str:concat "[attachment " (str:concat $label " -- no file_id]"))
                (case (claw:tg-get-file $file-id)
                  (((HttpResult 200 $body)
                    (let $remote (claw:tg-file-path-from-body $body)
                         (if (== $remote "")
                             (str:concat "[attachment " (str:concat $label " -- getFile refused it (too big or expired)]"))
                             (let $dir (claw:tg-attachments-dir)
                             (let $_mk (fs:mkdirs $dir)
                             (let $dest (str:concat $dir (str:concat "/"
                                          (str:concat (claw:tg-message-id $message)
                                            (str:concat "-" (claw:tg-path-basename $remote)))))
                                  (if (claw:tg-download-file $remote $dest)
                                      (str:concat "[attachment saved: " (str:concat $dest
                                        (str:concat " (" (str:concat $label ")]"))))
                                      (str:concat "[attachment " (str:concat $label " -- download failed]")))))))))
                   ($other (str:concat "[attachment " (str:concat $label " -- getFile transport error]")))))))))))

(= (claw:tg-compose-with-note $text $note)
   (if (== $note "")
       $text
       (if (== $text "")
           $note
           (str:concat $text (str:concat "\n" $note)))))

(= (claw:tg-update->message-with-note $update $note)
   (let $update-id (claw:json-number-or-empty (claw:json-get $update "update_id"))
   (let $event (claw:tg-event $update)
        (case $event
          (((TgEvent $kind $message)
            (TgMessage $update-id
                       (claw:tg-chat-id $message)
                       (claw:tg-sender-rich $message)
                       (claw:tg-format-message
                         $update $kind $message
                         (claw:tg-compose-with-note (claw:tg-text $message) $note))
                       $kind))
           ($other TgNoMessage))))))

(= (claw:tg-update->message $update)
   (let $update-id (claw:json-number-or-empty (claw:json-get $update "update_id"))
   (let $event (claw:tg-event $update)
        (case $event
          (((TgEvent $kind $message)
            (TgMessage $update-id
                       (claw:tg-chat-id $message)
                       (claw:tg-sender-rich $message)
                       (claw:tg-format-message
                         $update $kind $message (claw:tg-text $message))
                       $kind))
           ($other TgNoMessage))))))

(= (claw:tg-latest-message-from-result $result)
   (case $result
     (((JsonArray $items)
       (claw:tg-update->message (claw:tg-list-last $items)))
      ($other TgNoMessage))))

(= (claw:tg-latest-message-from-body $body)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (claw:tg-latest-message-from-result
         (json-object-get (JsonObject $pairs) "result")))
      ($o2 TgNoMessage))))

;; ---- live filtering -------------------------------------------------------
;; pettaclaw's Telegram channel logs every update, skips disallowed/no-text
;; updates, and queues every allowed text/caption update in FIFO order. These
;; helpers keep the pure "latest message" parser above unchanged while giving
;; the live driver the same allowlist + batching behavior.

(= (claw:tg-false-setting? $value)
   (or (== $value "0")
       (or (== $value "false")
           (or (== $value "False")
               (or (== $value "no")
                   (== $value "No"))))))

(= (claw:tg-allow-private?)
   (let $v (claw:setting "METTACLAW_TELEGRAM_ALLOW_PRIVATE")
        (if (== $v NotFound)
            True
            (not (claw:tg-false-setting? $v)))))

(= (claw:tg-allowed-chat-ids)
   (let $v (claw:setting "METTACLAW_TELEGRAM_ALLOWED_CHAT_IDS")
        (if (== $v NotFound) "" $v)))

(= (claw:tg-list-contains-trimmed? $items $needle)
   (if (== $items ())
       False
       (let ($head $tail) (decons-atom $items)
            (if (== (str:trim $head) $needle)
                True
                (claw:tg-list-contains-trimmed? $tail $needle)))))

(= (claw:tg-chat-allowed-explicit? $allow-private $allowed-chat-ids $message)
   (let $chat-id (claw:tg-chat-id $message)
   (let $chat-type (claw:tg-chat-type $message)
        (if (and $allow-private (== $chat-type "private"))
            True
            (claw:tg-list-contains-trimmed?
              (str:split "," $allowed-chat-ids)
              $chat-id)))))

(= (claw:tg-update-next-offset $update)
   (let $update-id (claw:json-number-or-empty (claw:json-get $update "update_id"))
        (if (== $update-id "") "" (claw:tg-decimal-inc $update-id))))

(= (claw:tg-queued-message-from-update-explicit $allow-private $allowed-chat-ids $update)
   (case (claw:tg-event $update)
     (((TgEvent $kind $message)
       (if (claw:tg-chat-allowed-explicit?
             $allow-private $allowed-chat-ids $message)
           (let $note (claw:tg-attachment-note $message)
                (if (and (== (claw:tg-text $message) "") (== $note ""))
                    TgNoMessage
                    (claw:tg-update->message-with-note $update $note)))
           TgNoMessage))
      ($other TgNoMessage))))

(= (claw:tg-reverse-acc () $acc)
   $acc)

(= (claw:tg-reverse-acc $items $acc)
   (let ($head $tail) (decons-atom $items)
        (claw:tg-reverse-acc $tail (cons-atom $head $acc))))

(= (claw:tg-reverse $items)
   (claw:tg-reverse-acc $items ()))

(= (claw:tg-first-message $items)
   (if (== $items ())
       TgNoMessage
       (let ($head $tail) (decons-atom $items) $head)))

(= (claw:tg-collect-queued-fold $items $allow-private $allowed-chat-ids $queued-rev $offset)
   (if (== $items ())
       (TgReceiveBatch (claw:tg-reverse $queued-rev) $offset)
       (let ($head $tail) (decons-atom $items)
       (let $next-offset (claw:tg-update-next-offset $head)
       (let $queued (claw:tg-queued-message-from-update-explicit
                      $allow-private $allowed-chat-ids $head)
       (let $queued-rev2 (case $queued
                           ((TgNoMessage $queued-rev)
                            ($msg (cons-atom $msg $queued-rev))))
       (let $offset2 (if (== $next-offset "") $offset $next-offset)
            (claw:tg-collect-queued-fold
              $tail $allow-private $allowed-chat-ids
              $queued-rev2 $offset2))))))))

(= (claw:tg-receive-batch-from-result-explicit $result $allow-private $allowed-chat-ids)
   (case $result
     (((JsonArray $items)
       (claw:tg-collect-queued-fold
         $items $allow-private $allowed-chat-ids () ""))
      ($other (TgReceiveBatch () "")))))

(= (claw:tg-audit-bool $value)
   (if $value (JsonBool True) (JsonBool False)))

(= (claw:tg-audit-kind-text $kind)
   (repr $kind))

(= (claw:tg-audit-classify-explicit $allow-private $allowed-chat-ids $update)
   (case (claw:tg-event $update)
     (((TgEvent $kind $message)
       (let $allowed (claw:tg-chat-allowed-explicit?
                       $allow-private $allowed-chat-ids $message)
       (let $text (claw:json-string-or-empty (claw:json-get $message "text"))
       (let $caption (claw:tg-caption $message)
       (let $queued (and $allowed
                         (not (and (== $text "")
                                   (and (== $caption "")
                                        (== (claw:tg-attachment $message) TgNoAttachment)))))
       (let $note
            (if (not $allowed)
                "disallowed_chat"
                (if $queued "" "no_text_or_caption"))
            (TgAudit $update $kind $message $allowed $queued $note)))))))
      ($other
       (TgAudit $update unsupported JsonNull False False "unsupported_update")))))

(= (claw:tg-audit-record $received-at $audit)
   (case $audit
     (((TgAudit $update $kind $message $allowed $queued $note)
       (JsonObject
         ((JsonPair "received_at" (JsonString $received-at))
          (JsonPair "update_id"
            (claw:json-number-or-null
              (claw:json-number-or-empty (claw:json-get $update "update_id"))))
          (JsonPair "kind" (JsonString (claw:tg-audit-kind-text $kind)))
          (JsonPair "allowed" (claw:tg-audit-bool $allowed))
          (JsonPair "queued" (claw:tg-audit-bool $queued))
          (JsonPair "note" (JsonString $note))
          (JsonPair "chat_id" (JsonString (claw:tg-chat-id $message)))
          (JsonPair "chat_type" (JsonString (claw:tg-chat-type $message)))
          (JsonPair "chat_title" (JsonString ""))
          (JsonPair "message_id"
            (claw:json-number-or-null (claw:tg-message-id $message)))
          (JsonPair "from" (JsonString ""))
          (JsonPair "from_id" (JsonString (claw:tg-from-id $message)))
          (JsonPair "from_is_bot" (claw:tg-audit-bool (claw:tg-from-is-bot? $message)))
          (JsonPair "text"
            (if $allowed
                (claw:json-string-or-null
                  (claw:json-string-or-empty (claw:json-get $message "text")))
                JsonNull))
          (JsonPair "caption"
            (if $allowed
                (claw:json-string-or-null (claw:tg-caption $message))
                JsonNull))
          (JsonPair "raw" (if $allowed $update JsonNull)))))
      ($other JsonNull))))

(= (claw:tg-audit-row $received-at $audit)
   (str:concat (json-stringify (claw:tg-audit-record $received-at $audit)) "\n"))

(= (claw:tg-log-update-to-path-explicit $path $received-at $allow-private $allowed-chat-ids $update)
   (case (once (eval (claw:tg-audit-row
                       $received-at
                       (claw:tg-audit-classify-explicit
                         $allow-private $allowed-chat-ids $update))))
     (($row
       (case (once (fs:append-text $path $row))
         ((() TgAuditLogged)
          ($err (TgAuditLogFailed $err))))))))

(= (claw:tg-log-updates-fold $path $received-at $allow-private $allowed-chat-ids $items)
   (if (== $path "")
       TgAuditDisabled
       (if (== $items ())
           TgAuditLogged
           (let ($head $tail) (decons-atom $items)
           (let $one (claw:tg-log-update-to-path-explicit
                       $path $received-at $allow-private $allowed-chat-ids $head)
           (case $one
             ((TgAuditLogged
               (claw:tg-log-updates-fold
                 $path $received-at $allow-private $allowed-chat-ids $tail))
              ($err $err))))))))

(= (claw:tg-log-updates-from-body-explicit $path $received-at $allow-private $allowed-chat-ids $body)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (case (json-object-get (JsonObject $pairs) "result")
         (((JsonArray $items)
           (claw:tg-log-updates-fold
             $path $received-at $allow-private $allowed-chat-ids $items))
          ($other TgAuditLogged))))
      ($bad TgAuditLogged))))

(= (claw:tg-log-path)
   (let $p (claw:setting "METTACLAW_TELEGRAM_LOG_PATH")
        (if (== $p NotFound) "" $p)))

(= (claw:tg-log-updates-from-body $body)
   (claw:tg-log-updates-from-body-explicit
     (claw:tg-log-path)
     (time:time-string "%Y-%m-%dT%H:%M:%S%z")
     (claw:tg-allow-private?)
     (claw:tg-allowed-chat-ids)
     $body))

(= (claw:tg-receive-from-result-explicit $result $allow-private $allowed-chat-ids)
   (case (claw:tg-receive-batch-from-result-explicit
           $result $allow-private $allowed-chat-ids)
     (((TgReceiveBatch $queued $offset)
       (TgReceive (claw:tg-first-message $queued) $offset)))))

(= (claw:tg-receive-batch-from-body-explicit $body $allow-private $allowed-chat-ids)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (claw:tg-receive-batch-from-result-explicit
         (json-object-get (JsonObject $pairs) "result")
         $allow-private
         $allowed-chat-ids))
      ($o2 (TgReceiveBatch () "")))))

(= (claw:tg-receive-from-body-explicit $body $allow-private $allowed-chat-ids)
   (case (claw:tg-receive-batch-from-body-explicit
           $body $allow-private $allowed-chat-ids)
     (((TgReceiveBatch $queued $offset)
       (TgReceive (claw:tg-first-message $queued) $offset)))))

(= (claw:tg-receive-from-body $body)
   (claw:tg-receive-from-body-explicit
     $body
     (claw:tg-allow-private?)
     (claw:tg-allowed-chat-ids)))

;; Decimal string increment for Telegram offsets (`next = update_id + 1`).
(= (claw:tg-inc-last-digit $prefix $digit)
   (case $digit
     (("0" (str:concat $prefix "1"))
      ("1" (str:concat $prefix "2"))
      ("2" (str:concat $prefix "3"))
      ("3" (str:concat $prefix "4"))
      ("4" (str:concat $prefix "5"))
      ("5" (str:concat $prefix "6"))
      ("6" (str:concat $prefix "7"))
      ("7" (str:concat $prefix "8"))
      ("8" (str:concat $prefix "9"))
      ("9" (str:concat (claw:tg-decimal-inc $prefix) "0"))
      ($other "1"))))

(= (claw:tg-decimal-inc $text)
   (let $clean (str:trim $text)
        (if (== $clean "")
            "1"
            (let $len (str:length $clean)
            (let $prefix (str:slice $clean 0 (- $len 1))
            (let $last (str:slice $clean (- $len 1) $len)
                 (claw:tg-inc-last-digit $prefix $last)))))))

(= (claw:tg-next-offset $msg)
   (case $msg
     (((TgMessage $update-id $chat-id $sender $text $kind)
       (claw:tg-decimal-inc $update-id))
      ($other ""))))

(= (claw:tg-msg->loop-msg $msg)
   (case $msg
     (((TgMessage $update-id $chat-id $sender $text $kind)
       (Msg $sender $update-id $text))
      ($other (Msg bot "" "")))))

(= (claw:tg-offset-path)
   (let $p (claw:setting "METTACLAW_TELEGRAM_OFFSET_PATH")
        (if (== $p NotFound)
            (str:concat (claw:home) "/.config/cettaclaw/telegram_offset.txt")
            $p)))

(= (claw:tg-read-offset)
   (let $p (claw:tg-offset-path)
        (if (fs:exists $p)
            (case (fs:read-text $p)
              (((FsError $msg) "-1")
               ($text (str:trim $text))))
            "-1")))

(= (claw:tg-write-offset-to-path $path $offset)
   (fs:write-text $path (str:concat $offset "\n")))

(= (claw:tg-write-offset $offset)
   (claw:tg-write-offset-to-path (claw:tg-offset-path) $offset))
