;; Offline golden for Telegram JSON handling. No network and no token: this
;; guards the pure layer that turns Bot API payloads into safe agent messages.

!(import! &self ../src/telegram.metta)

(= (claw:test-contains $haystack $needle)
   (if (== (collapse (str:find $haystack $needle)) ()) False True))

(= (claw:test-msg-envelope $msg)
   (case $msg
     (((TgMessage $update-id $chat-id $sender $text $kind)
       (TgEnvelope $update-id $chat-id $sender $kind))
      ($other $other))))

(= (claw:test-msg-text $msg)
   (case $msg
     (((TgMessage $update-id $chat-id $sender $text $kind) $text)
      ($other ""))))

(= (claw:test-receive-envelope $receive)
   (case $receive
     (((TgReceive
         (TgMessage $update-id $chat-id $sender $text $kind)
         $offset)
       (TgReceiveEnvelope $update-id $chat-id $sender $kind $offset))
      ((TgReceive TgNoMessage $offset) (TgReceiveNoMessage $offset))
      ($other $other))))

(= (claw:test-receive-text $receive)
   (case $receive
     (((TgReceive
         (TgMessage $update-id $chat-id $sender $text $kind)
         $offset)
       $text)
      ($other ""))))

(= (claw:test-audit-summary $audit)
   (case $audit
     (((TgAudit $update $kind $message $allowed $queued $note)
       (TgAuditSummary $kind $allowed $queued $note))
      ($other $other))))

!(assertEqual
  (claw:test-msg-envelope
    (claw:tg-latest-message-from-body
      "{\"ok\":true,\"result\":[{\"update_id\":10,\"message\":{\"message_id\":1,\"from\":{\"id\":111,\"is_bot\":false,\"username\":\"tester\"},\"chat\":{\"id\":1001001,\"type\":\"private\"},\"text\":\"Hi Agent\"}}]}"))
  (TgEnvelope "10" "1001001" (human "111") message))

!(assertEqual
  (claw:test-contains
    (claw:test-msg-text
      (claw:tg-latest-message-from-body
        "{\"ok\":true,\"result\":[{\"update_id\":10,\"message\":{\"message_id\":1,\"from\":{\"id\":111,\"is_bot\":false,\"username\":\"tester\"},\"chat\":{\"id\":1001001,\"type\":\"private\"},\"text\":\"Hi Agent\"}}]}"))
    "from=\"@tester\"")
  True)

!(assertEqual
  (claw:test-contains
    (claw:test-msg-text
      (claw:tg-latest-message-from-body
        "{\"ok\":true,\"result\":[{\"update_id\":10,\"message\":{\"message_id\":1,\"from\":{\"id\":111,\"is_bot\":false,\"username\":\"tester\"},\"chat\":{\"id\":1001001,\"type\":\"private\"},\"text\":\"Hi Agent\"}}]}"))
    "]\nHi Agent")
  True)

;; The latest update wins, and bot messages are classified but still parsed.
!(assertEqual
  (claw:test-msg-envelope
    (claw:tg-latest-message-from-body
      "{\"ok\":true,\"result\":[{\"update_id\":10,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1},\"text\":\"old\"}},{\"update_id\":11,\"message\":{\"from\":{\"is_bot\":true},\"chat\":{\"id\":2},\"text\":\"new\"}}]}"))
  (TgEnvelope "11" "2" bot message))

;; Caption-only edited messages are accepted.
!(assertEqual
  (claw:test-msg-envelope
    (claw:tg-latest-message-from-body
      "{\"ok\":true,\"result\":[{\"update_id\":12,\"edited_message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":3},\"caption\":\"cap\"}}]}"))
  (TgEnvelope "12" "3" human edited_message))

!(assertEqual
  (claw:test-contains
    (claw:test-msg-text
      (claw:tg-latest-message-from-body
        "{\"ok\":true,\"result\":[{\"update_id\":12,\"edited_message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":3},\"caption\":\"cap\"}}]}"))
    "kind=\"edited_message\"")
  True)

;; Forward/reply metadata is preserved in the message text the model sees.
!(assertEqual
  (claw:test-contains
    (claw:test-msg-text
      (claw:tg-latest-message-from-body
        "{\"ok\":true,\"result\":[{\"update_id\":13,\"message\":{\"message_id\":9,\"from\":{\"id\":111,\"is_bot\":false,\"first_name\":\"Human\"},\"chat\":{\"id\":123,\"type\":\"private\"},\"reply_to_message\":{\"message_id\":8,\"from\":{\"id\":222,\"is_bot\":false,\"username\":\"alice\"},\"chat\":{\"id\":123,\"type\":\"private\"},\"text\":\"old line\"},\"forward_origin\":{\"type\":\"user\",\"sender_user\":{\"id\":333,\"is_bot\":false,\"username\":\"forwarder\"},\"message_id\":7},\"text\":\"new line\"}}]}"))
    "forward_from=\"@forwarder\"")
  True)

!(assertEqual
  (claw:test-contains
    (claw:test-msg-text
      (claw:tg-latest-message-from-body
        "{\"ok\":true,\"result\":[{\"update_id\":13,\"message\":{\"message_id\":9,\"from\":{\"id\":111,\"is_bot\":false,\"first_name\":\"Human\"},\"chat\":{\"id\":123,\"type\":\"private\"},\"reply_to_message\":{\"message_id\":8,\"from\":{\"id\":222,\"is_bot\":false,\"username\":\"alice\"},\"chat\":{\"id\":123,\"type\":\"private\"},\"text\":\"old line\"},\"forward_origin\":{\"type\":\"user\",\"sender_user\":{\"id\":333,\"is_bot\":false,\"username\":\"forwarder\"},\"message_id\":7},\"text\":\"new line\"}}]}"))
    "reply_to_from=\"@alice\"")
  True)

;; The Python bridge also accepts edited_channel_post updates.
!(assertEqual
  (claw:test-msg-envelope
    (claw:tg-latest-message-from-body
      "{\"ok\":true,\"result\":[{\"update_id\":14,\"edited_channel_post\":{\"message_id\":10,\"chat\":{\"id\":-100,\"type\":\"channel\",\"title\":\"News\"},\"caption\":\"edited channel caption\"}}]}"))
  (TgEnvelope "14" "-100" bot edited_channel_post))

;; Legacy Telegram forwarding fields still appear in older payloads.
!(assertEqual
  (claw:test-contains
    (claw:test-msg-text
      (claw:tg-latest-message-from-body
        "{\"ok\":true,\"result\":[{\"update_id\":15,\"message\":{\"message_id\":11,\"from\":{\"id\":111,\"is_bot\":false,\"first_name\":\"Human\"},\"chat\":{\"id\":123,\"type\":\"private\"},\"forward_from\":{\"id\":444,\"is_bot\":false,\"username\":\"legacy\"},\"author_signature\":\"sig\",\"text\":\"legacy forward\"}}]}"))
    "forward_from=\"@legacy\"")
  True)

!(assertEqual
  (claw:test-contains
    (claw:test-msg-text
      (claw:tg-latest-message-from-body
        "{\"ok\":true,\"result\":[{\"update_id\":16,\"message\":{\"message_id\":12,\"from\":{\"id\":111,\"is_bot\":false,\"first_name\":\"Human\"},\"chat\":{\"id\":123,\"type\":\"private\"},\"forward_sender_name\":\"Hidden Sender\",\"text\":\"hidden forward\"}}]}"))
    "forward_from=\"Hidden Sender\"")
  True)

;; external_reply and quote metadata are source/provenance, not body text.
!(assertEqual
  (claw:test-contains
    (claw:test-msg-text
      (claw:tg-latest-message-from-body
        "{\"ok\":true,\"result\":[{\"update_id\":17,\"message\":{\"message_id\":13,\"from\":{\"id\":111,\"is_bot\":false,\"first_name\":\"Human\"},\"chat\":{\"id\":123,\"type\":\"private\"},\"external_reply\":{\"origin\":\"external\",\"text\":\"outside line\"},\"quote\":{\"text\":\"quoted words\"},\"text\":\"reply with quote\"}}]}"))
    "external_reply_excerpt=\"outside line\"")
  True)

!(assertEqual
  (claw:test-contains
    (claw:test-msg-text
      (claw:tg-latest-message-from-body
        "{\"ok\":true,\"result\":[{\"update_id\":17,\"message\":{\"message_id\":13,\"from\":{\"id\":111,\"is_bot\":false,\"first_name\":\"Human\"},\"chat\":{\"id\":123,\"type\":\"private\"},\"external_reply\":{\"origin\":\"external\",\"text\":\"outside line\"},\"quote\":{\"text\":\"quoted words\"},\"text\":\"reply with quote\"}}]}"))
    "quote=\"quoted words\"")
  True)

;; Empty update batches and malformed payloads do not crash the loop.
!(assertEqual
  (claw:tg-latest-message-from-body "{\"ok\":true,\"result\":[]}")
  TgNoMessage)

!(assertEqual
  (claw:tg-latest-message-from-body "not json")
  TgNoMessage)

;; Telegram offset is update_id + 1, implemented as decimal-string arithmetic.
!(assertEqual (claw:tg-next-offset (TgMessage "10" "1001001" human "x" message)) "11")
!(assertEqual (claw:tg-decimal-inc "199") "200")
!(assertEqual (claw:tg-decimal-inc "") "1")
!(assertEqual
  (claw:tg-msg->loop-msg (TgMessage "10" "1001001" human "same text" message))
  (Msg human "10" "same text"))

;; sendMessage body accepts both numeric atoms and JSON-number strings.
!(assertEqual
  (claw:tg-send-body "1001001" "hello")
  "{\"chat_id\":1001001,\"text\":\"hello\"}")

!(assertEqual
  (claw:tg-send-body 1001001 "hello")
  "{\"chat_id\":1001001,\"text\":\"hello\"}")

;; Live receive filtering mirrors pettaclaw: disallowed or non-text updates are
;; skipped as messages but still advance the Telegram offset.
!(assertEqual
  (claw:test-receive-envelope
    (claw:tg-receive-from-body-explicit
      "{\"ok\":true,\"result\":[{\"update_id\":20,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":999,\"type\":\"private\"},\"text\":\"skip\"}},{\"update_id\":21,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"allowed\"}}]}"
      False
      "1002003,-1003004"))
  (TgReceiveEnvelope "21" "1002003" human message "22"))

!(assertEqual
  (claw:test-contains
    (claw:test-receive-text
      (claw:tg-receive-from-body-explicit
        "{\"ok\":true,\"result\":[{\"update_id\":20,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":999,\"type\":\"private\"},\"text\":\"skip\"}},{\"update_id\":21,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"allowed\"}}]}"
        False
        "1002003,-1003004"))
    "]\nallowed")
  True)

;; Batches expose all queued allowed messages in Telegram order, so the live
;; driver can process them as a FIFO instead of collapsing a burst to "latest".
!(assertEqual
  (case (claw:tg-receive-batch-from-body-explicit
          "{\"ok\":true,\"result\":[{\"update_id\":70,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"first\"}},{\"update_id\":71,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"second\"}}]}"
          False
          "1002003")
    (((TgReceiveBatch $queued $offset)
      (let ($first $rest) (decons-atom $queued)
      (let ($second $tail) (decons-atom $rest)
           (TgBatchEnvelope
             (claw:test-msg-envelope $first)
             (claw:test-msg-envelope $second)
             $offset))))))
  (TgBatchEnvelope
    (TgEnvelope "70" "1002003" human message)
    (TgEnvelope "71" "1002003" human message)
    "72"))

!(assertEqual
  (claw:tg-receive-from-body-explicit
    "{\"ok\":true,\"result\":[{\"update_id\":30,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":999,\"type\":\"private\"},\"text\":\"skip\"}}]}"
    False
    "1002003")
  (TgReceive TgNoMessage "31"))

!(assertEqual
  (claw:test-receive-envelope
    (claw:tg-receive-from-body-explicit
      "{\"ok\":true,\"result\":[{\"update_id\":40,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":999,\"type\":\"private\"},\"text\":\"private ok\"}}]}"
      True
      ""))
  (TgReceiveEnvelope "40" "999" human message "41"))

!(assertEqual
  (claw:tg-receive-from-body-explicit
    "{\"ok\":true,\"result\":[{\"update_id\":50,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"}}}]}"
    False
    "1002003")
  (TgReceive TgNoMessage "51"))

;; Attachment discovery and audit classification stay pure: the audit path
;; recognizes queueable files without invoking getFile or downloading bytes.
!(assertEqual
  (claw:tg-attachment
    (json-parse
      "{\"message_id\":9,\"document\":{\"file_id\":\"doc-1\",\"file_name\":\"paper.pdf\",\"mime_type\":\"application/pdf\",\"file_size\":123}}"))
  (TgAttachment "document" "doc-1" "paper.pdf" "application/pdf" "123"))

!(assertEqual
  (claw:test-audit-summary
    (claw:tg-audit-classify-explicit
      False "1002003"
      (json-parse
        "{\"update_id\":52,\"message\":{\"message_id\":9,\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"document\":{\"file_id\":\"doc-1\"}}}")))
  (TgAuditSummary message True True ""))

!(assertEqual
  (claw:tg-curl-config "https://example.invalid/file")
  "url = \"https://example.invalid/file\"\n")

;; Audit logging mirrors pettaclaw's essential contract: one JSONL row per
;; update; disallowed updates redact text/raw, allowed updates keep them.
!(fs:write-text "runtime/test_claw_telegram_audit.jsonl" "")
!(claw:tg-log-updates-from-body-explicit
  "runtime/test_claw_telegram_audit.jsonl"
  "2026-07-04T15:40:00+0200"
  False
  "1002003"
  "{\"ok\":true,\"result\":[{\"update_id\":60,\"message\":{\"message_id\":6,\"from\":{\"id\":111,\"is_bot\":false},\"chat\":{\"id\":999,\"type\":\"private\"},\"text\":\"skip\"}},{\"update_id\":61,\"message\":{\"message_id\":7,\"from\":{\"id\":222,\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"allowed\"}},{\"update_id\":62,\"message\":{\"message_id\":8,\"from\":{\"id\":222,\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"}}}]}")

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_telegram_audit.jsonl")
    "\"update_id\":60")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_telegram_audit.jsonl")
    "\"allowed\":false")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_telegram_audit.jsonl")
    "\"note\":\"disallowed_chat\"")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_telegram_audit.jsonl")
    "\"text\":null")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_telegram_audit.jsonl")
    "\"raw\":null")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_telegram_audit.jsonl")
    "\"update_id\":61")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_telegram_audit.jsonl")
    "\"queued\":true")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_telegram_audit.jsonl")
    "\"text\":\"allowed\"")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_telegram_audit.jsonl")
    "\"note\":\"no_text_or_caption\"")
  True)
