;; Synthetic live transcript parity contract.
;;
;; This is not a constant spreadsheet. It exercises the PeTTa-shaped operational
;; behavior on fake Telegram updates: allowed-chat filtering, FIFO delivery,
;; send-gate failure, history append, and offset commit. All paths are scratch;
;; no network, no real Telegram send, no live offset.

!(import! &self ../runtime/loop_driver.metta)
!(import! &self fs)
!(import! &self str)

(= (claw:test-contains $haystack $needle)
   (if (== (collapse (str:find $haystack $needle)) ()) False True))

(= (claw:test-remove-if-exists $path)
   (case (fs:exists $path)
     ((True (fs:remove $path))
      ($other ()))))

(= (claw:test-turn-results $acted)
   (case $acted
     (((LiveActed $cmds $results) $results)
      ($other ()))))

(= (claw:test-msg-key $msg)
   (case $msg
     (((Msg $sender $key $text) $key)
      ($other ""))))

(= (claw:test-msg-text $msg)
   (case $msg
     (((Msg $sender $key $text) $text)
      ($other ""))))

(= (claw:test-turn-to-paths $msg $raw $history-path $offset-path)
   (let $_tick (claw:live-tick)
   (let $msgnew (claw:note-prevmsg (claw:msg-key $msg))
   (let $humanmsg (claw:is-human $msg)
   (let $_arm (if (and $msgnew $humanmsg) (claw:arm) ClawNoop)
   (let $acted
        (if (and (claw:live-real-message? $msg) (> (get-state &loops) 0))
            (claw:live-run-response $msg $raw)
            LiveIdle)
   (let $results (claw:test-turn-results $acted)
   (let $finish
        (claw:live-finalize-to-paths
          $history-path $offset-path $msg $raw $results True)
        (TranscriptTurn $msg $msgnew $humanmsg $acted $finish)))))))))

(= (claw:test-finish $turn)
   (case $turn
     (((TranscriptTurn $msg $new $human $acted $finish) $finish)
      ($other $other))))

(= (claw:test-acted $turn)
   (case $turn
     (((TranscriptTurn $msg $new $human $acted $finish) $acted)
      ($other $other))))

(= (claw:test-body)
   "{\"ok\":true,\"result\":[{\"update_id\":100,\"message\":{\"from\":{\"is_bot\":false,\"id\":1,\"username\":\"other\"},\"chat\":{\"id\":999,\"type\":\"private\"},\"text\":\"disallowed\"}},{\"update_id\":101,\"message\":{\"from\":{\"is_bot\":false,\"id\":1002003,\"username\":\"zariuq\"},\"chat\":{\"id\":1002003,\"type\":\"private\",\"username\":\"zariuq\"},\"text\":\"First allowed\"}},{\"update_id\":102,\"message\":{\"from\":{\"is_bot\":false,\"id\":1002003,\"username\":\"zariuq\"},\"chat\":{\"id\":1002003,\"type\":\"private\",\"username\":\"zariuq\"},\"text\":\"Second allowed\"}}]}")

(= (claw:test-empty-body)
   "{\"ok\":true,\"result\":[]}")

(= (claw:test-history) "runtime/test_claw_transcript_history.metta")
(= (claw:test-offset) "runtime/test_claw_transcript_offset.txt")
(= (claw:test-audit) "runtime/test_claw_transcript_audit.jsonl")

!(claw:live-init)
!(change-state! &sleep-ms 0)
!(change-state! &reply-chat "")
!(change-state! &pending-offset "")
!(change-state! &prevmsg "")
!(change-state! &tg-queue (TgQueue ()))
!(change-state! &live-last-msg NoLiveMessage)
!(claw:test-remove-if-exists (claw:test-history))
!(claw:test-remove-if-exists (claw:test-offset))
!(fs:write-text (claw:test-audit) "")

;; First allowed update is selected; the disallowed update is audited and skipped.
!(assertEqual
  (let $msg
       (claw:live-receive-from-body-log-explicit
         (claw:test-body)
         (claw:test-audit)
         "2026-07-05T20:00:00+0200"
         False
         "1002003")
       (and
         (== (claw:test-msg-key $msg) "101")
         (and
           (claw:test-contains (claw:test-msg-text $msg) "chat_id=\"1002003\"")
           (claw:test-contains (claw:test-msg-text $msg) "]\nFirst allowed"))))
  True)

!(assertEqual (get-state &reply-chat) "1002003")
!(assertEqual (get-state &pending-offset) "102")
!(assertEqual
  (claw:test-contains (fs:read-text (claw:test-audit)) "\"note\":\"disallowed_chat\"")
  True)

;; A generated send in unapproved/offline mode must not consume the update.
!(assertEqual
  (claw:test-finish
    (claw:test-turn-to-paths
      (Msg human "101" "First allowed")
      "((send \"Preview only\") (pin \"first seen\"))"
      (claw:test-history)
      (claw:test-offset)))
  (LiveNotCommitted SendNotDelivered))

!(assertEqual (fs:exists (claw:test-offset)) False)
!(assertEqual (fs:exists (claw:test-history)) False)
!(assertEqual (get-state &pending-offset) "102")

;; The queued second update is processed FIFO and commits when the command
;; result is deliverable.
!(assertEqual
  (let $msg (claw:live-receive-from-queued-state)
       (and
         (== (claw:test-msg-key $msg) "102")
         (claw:test-contains (claw:test-msg-text $msg) "]\nSecond allowed")))
  True)

!(assertEqual (get-state &pending-offset) "103")

!(assertEqual
  (claw:test-finish
    (claw:test-turn-to-paths
      (Msg human "102" "Second allowed")
      "((pin \"second committed\"))"
      (claw:test-history)
      (claw:test-offset)))
  (LiveCommitted HistoryAppended (OffsetCommitted "103")))

!(assertEqual (fs:read-text (claw:test-offset)) "103\n")
!(assertEqual
  (claw:test-contains (fs:read-text (claw:test-history)) "HUMAN_MESSAGE: ")
  True)
!(assertEqual
  (claw:test-contains (fs:read-text (claw:test-history)) "Second allowed")
  True)
!(assertEqual
  (claw:test-contains (fs:read-text (claw:test-history)) "second committed")
  True)

;; PeTTa consumes a queued message once. An empty batch retains the reply route
;; and continuation key, but must not present the old human text again.
!(assertEqual
  (let $msg (claw:live-receive-from-body-explicit
              (claw:test-empty-body) False "1002003")
       (and
         (== (claw:test-msg-key $msg) "102")
         (and
           (== (claw:test-msg-text $msg) "")
           (not (claw:is-human $msg)))))
  True)

!(assertEqual (get-state &pending-offset) "")

!(assertEqual
  (claw:test-finish
    (claw:test-turn-to-paths
      (Msg bot "102" "")
      "((pin \"followup no offset\"))"
      (claw:test-history)
      (claw:test-offset)))
  (LiveCommitted HistoryAppended NoPendingOffset))
