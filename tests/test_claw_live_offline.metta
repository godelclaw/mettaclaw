;; Offline Phase-1 live-turn wiring: Telegram payload -> reply chat/pending
;; offset -> keyed loop message -> commands. No network, no real send.

!(import! &self ../runtime/loop_driver.metta)
!(import! &self ./fixtures/llm.metta)
!(import! &self fs)
!(import! &self str)

(= (claw:test-update-body)
   "{\"ok\":true,\"result\":[{\"update_id\":10,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1001001,\"type\":\"private\"},\"text\":\"Hi Agent\"}}]}")

(= (claw:test-contains $haystack $needle)
   (if (== (collapse (str:find $haystack $needle)) ()) False True))

(= (claw:test-acquire-lock-busy? $path)
   (case (claw:live-acquire-run-lock-to-path $path)
     (((RunLockBusy $path $err) True)
      ($other False))))

(= (claw:test-remove-if-exists $path)
   (case (fs:exists $path)
     ((True (fs:remove $path))
      ($other ()))))

(= (claw:test-loop-envelope $msg)
   (case $msg
     (((Msg $sender $key $text) (LoopEnvelope $sender $key))
      ($other $other))))

(= (claw:test-loop-text $msg)
   (case $msg
     (((Msg $sender $key $text) $text)
      ($other ""))))

(= (claw:test-offset-commit-failed? $x)
   (case $x
     (((OffsetCommitFailed $offset $err) True)
      ($other False))))

(= (claw:test-live-history-failed? $x)
   (case $x
     (((LiveNotCommitted (HistoryAppendFailed $err)) True)
      ($other False))))

(= (claw:test-live-offset-failed? $x)
   (case $x
     (((LiveNotCommitted (OffsetCommitFailed $offset $err)) True)
      ($other False))))

(= (claw:test-long-feedback)
   (str:join ""
     ("DROP_FEEDBACK_SENTINEL"
      (str:join "" (repeat-atom 50010 "x"))
      "TAIL_FEEDBACK_SENTINEL")))

(= (claw:test-long-pin)
   (str:join "" (repeat-atom 200 "p")))

!(claw:live-init)

;; The contained command child must receive the explicit env allowlist. A wiped
;; env regressed live sends into preview-only responses.
!(assertEqual
  (claw:live-run-response-child
    "((shell \"if [ \\\"${CETTACLAW_LIVE_SEND_APPROVED+x}\\\" = x ]; then printf present; else printf missing; fi\"))")
  ((ShellOk 0 "present")))

!(assertEqual (claw:live-tick) ClawFirst)
!(assertEqual (get-state &loops) (claw:max-loops))
!(claw:live-tick)
!(assertEqual (get-state &loops) (- (claw:max-loops) 1))
!(change-state! &loops (claw:max-loops))
!(change-state! &live-k 1)

!(assertEqual
  (claw:test-contains
    (claw:full-context "catalog probe" 50 1 True True "")
    "(send-telegram-chat chat_id string)")
  True)

!(assertEqual
  (claw:test-contains
    (claw:full-context "catalog probe" 50 1 True True "")
    "(mcp-call server-name tool-name json-object-string)")
  True)

!(assertEqual
  (claw:test-contains
    (claw:full-context "catalog probe" 50 1 True True "")
    "(skillName5 args5)) S-expression of up to 5")
  True)

!(assertEqual
  (claw:test-contains
    (claw:full-context
      "feedback cap probe" 50 1 True True (claw:test-long-feedback))
    "DROP_FEEDBACK_SENTINEL")
  False)

!(assertEqual
  (claw:test-contains
    (claw:full-context
      "feedback cap probe" 50 1 True True (claw:test-long-feedback))
    "TAIL_FEEDBACK_SENTINEL")
  True)

;; Repr-escaped quotes in history/feedback are a presentation detail, not syntax
;; the model should imitate.
!(assertEqual
  (claw:context-tail "((send \\\"hello\\\"))" 1000)
  "((send \"hello\"))")

!(assertEqual
  (let $_ (change-state! &last (claw:test-long-feedback)) ())
  ())

!(assertEqual
  (claw:test-contains
    (claw:live-child-program "()" "runtime/test_claw_child_state.metta")
    "DROP_FEEDBACK_SENTINEL")
  False)

!(assertEqual
  (claw:test-contains
    (claw:live-child-program "()" "runtime/test_claw_child_state.metta")
    "TAIL_FEEDBACK_SENTINEL")
  True)

!(assertEqual (let $_ (change-state! &last "") ()) ())
!(assertEqual
  (let $_ (change-state! &pins (repeat-atom 1000 (claw:test-long-pin))) ())
  ())

!(assertEqual
  (< (str:length
       (claw:live-child-program "()" "runtime/test_claw_child_state.metta"))
     100000)
  True)

!(assertEqual (let $_ (change-state! &pins ()) ()) ())

!(claw:test-remove-if-exists "runtime/test_claw_run.lock")

!(assertEqual
  (claw:live-acquire-run-lock-to-path "runtime/test_claw_run.lock")
  (RunLockAcquired "runtime/test_claw_run.lock"))

!(assertEqual
  (fs:exists "runtime/test_claw_run.lock")
  True)

!(assertEqual
  (claw:test-acquire-lock-busy? "runtime/test_claw_run.lock")
  True)

!(assertEqual
  (claw:live-release-run-lock-to-path "runtime/test_claw_run.lock")
  (RunLockReleased "runtime/test_claw_run.lock"))

!(assertEqual
  (fs:exists "runtime/test_claw_run.lock")
  False)

!(fs:write-text "runtime/test_claw_forever_busy.lock" "held")

!(assertEqual
  (claw:live-loop-forever-locked-to-path
    "runtime/test_claw_forever_busy.lock" 0 False)
  (RunLockBusy "runtime/test_claw_forever_busy.lock" AlreadyExists))

!(claw:test-remove-if-exists "runtime/test_claw_forever_busy.lock")

!(assertEqual
  (claw:live-loop-n-locked-to-path "runtime/test_claw_run.lock" 0 0 False)
  (LockedLoopDone
    "runtime/test_claw_run.lock"
    ()
    (RunLockReleased "runtime/test_claw_run.lock")))

!(assertEqual
  (fs:exists "runtime/test_claw_run.lock")
  False)

!(assertEqual
  (claw:live-loop-n-stream-locked-to-path "runtime/test_claw_run.lock" 0 0 False)
  (LockedLoopStreamDone
    "runtime/test_claw_run.lock"
    (LiveLoopStreamDone 0)
    (RunLockReleased "runtime/test_claw_run.lock")))

!(assertEqual
  (fs:exists "runtime/test_claw_run.lock")
  False)

!(assertEqual
  (claw:test-loop-envelope
    (claw:live-receive-from-body-explicit
      (claw:test-update-body) True ""))
  (LoopEnvelope human "10"))

!(assertEqual
  (claw:test-contains
    (claw:test-loop-text
      (claw:live-receive-from-body-explicit
        (claw:test-update-body) True ""))
    "[telegram update_id=\"10\"")
  True)

!(assertEqual
  (claw:test-contains
    (claw:test-loop-text
      (claw:live-receive-from-body-explicit
        (claw:test-update-body) True ""))
    "]\nHi Agent")
  True)

!(assertEqual (get-state &reply-chat) "1001001")
!(assertEqual (get-state &pending-offset) "11")

!(fs:write-text "runtime/test_claw_live_audit.jsonl" "")
!(change-state! &reply-chat "")
!(change-state! &pending-offset "")

!(assertEqual
  (claw:test-loop-envelope
    (claw:live-receive-from-body-log-explicit
      "{\"ok\":true,\"result\":[{\"update_id\":20,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":999,\"type\":\"private\"},\"text\":\"skip\"}},{\"update_id\":21,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"allowed\"}}]}"
      "runtime/test_claw_live_audit.jsonl"
      "2026-07-04T15:45:00+0200"
      False
      "1002003"))
  (LoopEnvelope human "21"))

!(assertEqual
  (claw:test-contains
    (claw:test-loop-text
      (claw:live-receive-from-body-log-explicit
        "{\"ok\":true,\"result\":[{\"update_id\":20,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":999,\"type\":\"private\"},\"text\":\"skip\"}},{\"update_id\":21,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"allowed\"}}]}"
        "runtime/test_claw_live_audit.jsonl"
        "2026-07-04T15:45:00+0200"
        False
        "1002003"))
    "]\nallowed")
  True)

!(assertEqual (get-state &reply-chat) "1002003")
!(assertEqual (get-state &pending-offset) "22")
!(change-state! &tg-queue (TgQueue ()))

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_live_audit.jsonl")
    "\"update_id\":20")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_live_audit.jsonl")
    "\"note\":\"disallowed_chat\"")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_live_audit.jsonl")
    "\"text\":\"allowed\"")
  True)

!(change-state! &tg-queue (TgQueue ()))
!(change-state! &reply-chat "")
!(change-state! &pending-offset "")

!(assertEqual
  (claw:test-loop-envelope
    (claw:live-receive-from-body-explicit
      "{\"ok\":true,\"result\":[{\"update_id\":30,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"first\"}},{\"update_id\":31,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"second\"}}]}"
      False
      "1002003"))
  (LoopEnvelope human "30"))

!(assertEqual (get-state &pending-offset) "31")

!(assertEqual
  (claw:test-contains
    (claw:test-loop-text
      (claw:live-receive-from-queued-state))
    "]\nsecond")
  True)

!(assertEqual (get-state &pending-offset) "32")

!(change-state! &tg-queue (TgQueue ()))
!(change-state! &reply-chat "")
!(change-state! &pending-offset "")

!(assertEqual
  (claw:test-loop-envelope
    (claw:live-receive-from-body-explicit
      "{\"ok\":true,\"result\":[{\"update_id\":40,\"message\":{\"from\":{\"is_bot\":false},\"chat\":{\"id\":1002003,\"type\":\"private\"},\"text\":\"persist\"}}]}"
      False
      "1002003"))
  (LoopEnvelope human "40"))

!(assertEqual (get-state &pending-offset) "41")

;; PeTTa consumes the latest queued message once. CeTTa retains its key and
;; reply route for autonomous follow-up work, but the old human payload is gone.
!(assertEqual
  (claw:test-loop-envelope
    (claw:live-receive-from-body-explicit
      "{\"ok\":true,\"result\":[]}"
      False
      "1002003"))
  (LoopEnvelope bot "40"))

!(assertEqual
  (claw:test-loop-text
    (claw:live-receive-from-body-explicit
      "{\"ok\":true,\"result\":[]}"
      False
      "1002003"))
  "")

!(assertEqual (get-state &pending-offset) "")

!(change-state! &reply-chat "1001001")
!(change-state! &pending-offset "11")

!(assertEqual
  (let $turn
       (claw:live-one-turn-from-msg-with-response
         (Msg human "11" "Hi Agent")
         "((send \"Hello Human\") (pin \"saw live test\"))"
         False)
       (and
         (claw:test-contains (repr $turn) "SendPreview")
         (and
           (claw:test-contains (repr $turn) "Hello Human")
           (and
             (claw:test-contains (repr $turn) "Pinned")
             (claw:test-contains (repr $turn) "LivePreviewOnly")))))
  True)

;; Preview mode does not consume the update.
!(assertEqual (get-state &pending-offset) "11")

!(change-state! &reply-chat "")
!(change-state! &pending-offset "")
!(change-state! &sleep-ms 0)

!(assertEqual
  (let $step
       (claw:live-loop-step-from-msg-with-response
         (Msg human "18" "Loop once")
         "((pin \"loop ok\"))"
         False)
       (and
         (claw:test-contains (repr $step) "Pinned")
         (claw:test-contains (repr $step) "LivePreviewOnly")))
  True)

;; Malformed model output is feedback, not a loop-breaking top-level Error.
!(assertEqual
  (claw:live-one-turn-from-msg-with-response
    (Msg human "19" "Bad raw")
    "\"unterminated"
    False)
  (LiveTurn
    (Msg human "19" "Bad raw")
    True
    True
    (LiveActed
      (ParseFailed "((\"unterminated))")
      ((CommandParseFailed
        "[(Error (parse \"((\\\"unterminated))\") ParseFailed)]\n")))
    (LivePreviewOnly "" "")))

;; Built-in-looking non-skill commands are data, not executable surprises.
!(assertEqual
  (let $turn
       (claw:live-one-turn-from-msg-with-response
         (Msg human "20" "Bad command")
         "((+ 1 \"x\"))"
         False)
       (and
         (claw:test-contains (repr $turn) "UnknownCommand")
         (claw:test-contains (repr $turn) "LivePreviewOnly")))
  True)

;; A model that emits repr-escaped command quotes still means a quoted command.
!(assertEqual
  (let $turn
       (claw:live-one-turn-from-msg-with-response
         (Msg human "21" "Escaped send")
         "((send-telegram-chat \\\"42\\\" \\\"Escaped ok\\\"))"
         False)
       (and
         (claw:test-contains (repr $turn) "SendPreview")
         (claw:test-contains (repr $turn) "Escaped ok")))
  True)

!(assertEqual
  (claw:live-results-committable?
    ((SendPreview "1001001" "not sent") (Pinned "x")))
  False)

!(assertEqual
  (claw:live-results-committable?
    ((UnknownCommand (query "later")) (Pinned "x")))
  True)

!(assertEqual
  (claw:live-results-committable?
    ((Pinned "x") (Sent "1001001" "sent" 200)))
  True)

!(assertEqual
  (claw:live-results-committable?
    ((SendFailed "1001001" "sent" TransportError)))
  False)

!(assertEqual
  (claw:live-first-send-preview
    ((Pinned "x") (SendPreview "1001001" "Hello Human") (Pinned "y")))
  (PendingSendCandidate "1001001" "Hello Human"))

!(assertEqual
  (claw:live-first-send-preview ((Pinned "x") (UnknownCommand (query "later"))))
  NoPendingSend)

!(assertEqual
  (claw:live-pending-send-record
    "1001001" "12" "Hello Human" "Hi Agent" "((send \"Hello Human\"))")
  (PendingSend
    "1001001" "12" "Hello Human" "Hi Agent" "((send \"Hello Human\"))"))

!(assertEqual
  (let $record
       (claw:live-pending-send-record
         "1001001" "12" "Hello Human" "Hi Agent" "((send \"Hello Human\"))")
       (parse (repr $record)))
  (PendingSend
    "1001001" "12" "Hello Human" "Hi Agent" "((send \"Hello Human\"))"))

!(assertEqual
  (claw:live-write-pending-send-offset-to-path
    "runtime/test_claw_pending_send.metta"
    "11"
    (Msg human "12" "Hi Agent")
    "((send \"Hello Human\"))"
    ((SendPreview "1001001" "Hello Human") (Pinned "x")))
  (PendingSendWritten "1001001" "11"))

!(assertEqual
  (claw:live-read-pending-send-from-path
    "runtime/test_claw_pending_send.metta")
  (PendingSend
    "1001001" "11" "Hello Human" "Hi Agent" "((send \"Hello Human\"))"))

!(assertEqual
  (claw:live-send-pending-from-path "runtime/test_claw_pending_send.metta")
  (PendingSendNeedsApproval "1001001" "11" "Hello Human"))

!(assertEqual
  (claw:live-store-pending-from-turn-to-path
    "runtime/test_claw_pending_from_turn.metta"
    (LiveTurn
      (Msg human "13" "Again")
      True
      True
      "((send \"Stored exactly\"))"
      (LiveActed
        ((send "Stored exactly"))
        ((SendPreview "1001001" "Stored exactly")))
      (LivePreviewOnly "1001001" "14")))
  (PendingSendWritten "1001001" "14"))

!(assertEqual
  (claw:live-read-pending-send-from-path
    "runtime/test_claw_pending_from_turn.metta")
  (PendingSend
    "1001001" "14" "Stored exactly" "Again" "((send \"Stored exactly\"))"))

!(fs:write-text "runtime/test_claw_history.metta" "")

!(assertEqual
  (claw:live-append-history-to-path
    "runtime/test_claw_history.metta"
    (Msg human "15" "Remember this")
    "((pin \"history ok\"))")
  HistoryAppended)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_history.metta")
    "HUMAN_MESSAGE: ")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_history.metta")
    "Remember this")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_history.metta")
    "history ok")
  True)

!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_history.metta")
    "time:time-string")
  False)

;; Preview/pending storage must not mutate the durable history file.
!(fs:write-text "runtime/test_claw_history_preview.metta" "")

!(assertEqual
  (claw:live-store-pending-from-turn-to-path
    "runtime/test_claw_pending_history_preview.metta"
    (LiveTurn
      (Msg human "16" "Preview only")
      True
      True
      "((send \"Do not append yet\"))"
      (LiveActed
        ((send "Do not append yet"))
        ((SendPreview "1001001" "Do not append yet")))
      (LivePreviewOnly "1001001" "17")))
  (PendingSendWritten "1001001" "17"))

!(assertEqual
  (fs:read-text "runtime/test_claw_history_preview.metta")
  "")

!(claw:test-remove-if-exists "runtime/test_claw_offset.txt")

!(change-state! &pending-offset "42")

!(assertEqual
  (claw:live-commit-pending-offset-to-path "runtime/test_claw_offset.txt")
  (OffsetCommitted "42"))

!(assertEqual (get-state &pending-offset) "")
!(assertEqual (fs:read-text "runtime/test_claw_offset.txt") "42\n")

!(change-state! &pending-offset "43")

!(assertEqual
  (claw:test-offset-commit-failed?
    (claw:live-commit-pending-offset-to-path
      "runtime/missing-offset-dir/test_claw_offset.txt"))
  True)

;; A failed offset write must leave the in-memory pending offset intact.
!(assertEqual (get-state &pending-offset) "43")

!(claw:test-remove-if-exists "runtime/test_claw_finalize_history.metta")
!(claw:test-remove-if-exists "runtime/test_claw_finalize_offset.txt")

!(change-state! &pending-offset "44")

!(assertEqual
  (claw:live-finalize-to-paths
    "runtime/test_claw_finalize_history.metta"
    "runtime/test_claw_finalize_offset.txt"
    (Msg human "44" "Commit this")
    "((pin \"commit ok\"))"
    ((Pinned "commit ok"))
    True)
  (LiveCommitted HistoryAppended (OffsetCommitted "44")))

!(assertEqual (get-state &pending-offset) "")
!(assertEqual (fs:read-text "runtime/test_claw_finalize_offset.txt") "44\n")
!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_finalize_history.metta")
    "Commit this")
  True)

!(change-state! &pending-offset "45")

!(assertEqual
  (claw:test-live-history-failed?
    (claw:live-finalize-to-paths
      "runtime/missing-history-dir/test_claw_finalize_history.metta"
      "runtime/test_claw_finalize_offset_after_history_fail.txt"
      (Msg human "45" "Do not skip")
      "((pin \"history fail\"))"
      ((Pinned "history fail"))
      True))
  True)

;; If history cannot be written, the Telegram offset must not advance.
!(assertEqual (get-state &pending-offset) "45")
!(assertEqual
  (fs:exists "runtime/test_claw_finalize_offset_after_history_fail.txt")
  False)

!(claw:test-remove-if-exists "runtime/test_claw_finalize_offset_fail_history.metta")

!(change-state! &pending-offset "46")

!(assertEqual
  (claw:test-live-offset-failed?
    (claw:live-finalize-to-paths
      "runtime/test_claw_finalize_offset_fail_history.metta"
      "runtime/missing-offset-dir/test_claw_finalize_offset.txt"
      (Msg human "46" "Do not mark consumed")
      "((pin \"offset fail\"))"
      ((Pinned "offset fail"))
      True))
  True)

;; If offset write fails after history append, leave the pending offset for
;; operator repair rather than silently skipping the update.
!(assertEqual (get-state &pending-offset) "46")
!(assertEqual
  (claw:test-contains
    (fs:read-text "runtime/test_claw_finalize_offset_fail_history.metta")
    "Do not mark consumed")
  True)

;; Empty update batches with no previous visible message do not spend a model
;; call or commit anything. Once a message has been consumed, follow-up turns
;; carry only its continuation key and reply route, never its human payload.
!(change-state! &live-last-msg NoLiveMessage)
!(change-state! &prevmsg "")
!(change-state! &reply-chat "")
!(change-state! &pending-offset "")

!(assertEqual
  (claw:live-one-turn-from-body-with-response
    "{\"ok\":true,\"result\":[]}"
    "((send \"should not happen\"))"
    False)
  (LiveTurn (Msg bot "" "") False False LiveIdle LiveNoCommit))

;; The full live-control path can use the normal LLM seam; fixture import keeps
;; this offline and verifies context assembly reaches the provider.
!(assertEqual
  (let $turn (claw:live-one-turn-from-msg (Msg human "12" "PING please") False)
       (and
         (claw:test-contains (repr $turn) "saw ping")
         (and
           (claw:test-contains (repr $turn) "Resting loops-left 0")
           (claw:test-contains (repr $turn) "LivePreviewOnly"))))
  True)

;; PeTTa's append-file skill appends one complete line, including its newline.
!(assertEqual
  (let $path "runtime/test_claw_append_line.txt"
  (let $_write (fs:write-text $path "first\n")
  (let $result (claw:append-file $path "second")
  (let $content (fs:read-text $path)
  (let $_remove (fs:remove $path)
       (and (== (claw:live-command-batch-timeout-ms) 900000)
            (and (== $result (Appended $path))
                 (== $content "first\nsecond\n"))))))))
  True)
