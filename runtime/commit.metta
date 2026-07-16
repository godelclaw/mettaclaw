;; runtime/commit.metta — the CORE commit semantics of a live turn.
;; A turn is committed only when its results are deliverable: the history row is
;; appended (to METTACLAW_HISTORY_PATH) and the Telegram offset is advanced (via
;; src/telegram). committable? refuses to commit a turn whose send only
;; previewed or failed, so a message is never dropped from the offset without a
;; real reply.
!(import! &self fs)
!(import! &self str)
!(import! &self time)
!(import! &self ../src/config.metta)
!(import! &self ../src/telegram.metta)
!(import! &self ../src/utils.metta)
!(import! &self ./bounded_eval.metta)

(= (claw:live-history-record $msg $raw)
   (claw:live-history-record-text (claw:msg-text $msg) $raw))

(= (claw:live-history-record-text $msg-text $raw)
   (claw:live-history-record-text-new $msg-text $raw True))

(= (claw:live-history-record-text-new $msg-text $raw $msgnew)
   (let $ts (time:time-string)
        (str:concat
          (if $msgnew
              (repr ($ts "\n" "HUMAN_MESSAGE: " $msg-text "\n" $raw "\n"))
              (repr ($ts "\n" $raw "\n")))
          "\n")))

(= (claw:live-append-history $msg $raw)
   (claw:live-append-history-text (claw:msg-text $msg) $raw))

(= (claw:live-append-history-new $msg $raw $msgnew)
   (claw:live-append-history-text-new (claw:msg-text $msg) $raw $msgnew))

(= (claw:live-append-history-to-path $path $msg $raw)
   (claw:live-append-history-text-to-path $path (claw:msg-text $msg) $raw))

(= (claw:live-append-history-text $msg-text $raw)
   (claw:live-append-history-text-new $msg-text $raw True))

(= (claw:live-append-history-text-new $msg-text $raw $msgnew)
   (let $p (claw:setting "METTACLAW_HISTORY_PATH")
        (if (== $p NotFound)
            HistoryNotConfigured
            (claw:live-append-history-text-to-path-new
              $p $msg-text $raw $msgnew))))

(= (claw:live-append-history-text-to-path $path $msg-text $raw)
   (claw:live-append-history-text-to-path-new $path $msg-text $raw True))

(= (claw:live-append-history-text-to-path-new $path $msg-text $raw $msgnew)
   (case (once (eval (claw:live-history-record-text-new $msg-text $raw $msgnew)))
     (($record
       (case (once (catch (fs:append-text $path $record)))
         (((catch ()) HistoryAppended)
          (() HistoryAppended)
          ($err (HistoryAppendFailed $err))))))))

(= (claw:live-commit-offset-to-path $path $offset)
   (if (== $offset "")
       NoPendingOffset
       (case (once (catch (claw:tg-write-offset-to-path $path $offset)))
         (((catch ()) (OffsetCommitted $offset))
          (() (OffsetCommitted $offset))
          ($err (OffsetCommitFailed $offset $err))))))

(= (claw:live-commit-offset $offset)
   (claw:live-commit-offset-to-path (claw:tg-offset-path) $offset))

(= (claw:live-commit-pending-offset-to-path $path)
   (let $offset (get-state &pending-offset)
        (if (== $offset "")
            NoPendingOffset
            (case (claw:live-commit-offset-to-path $path $offset)
              (((OffsetCommitted $committed)
                (let $_ (change-state! &pending-offset "")
                     (OffsetCommitted $committed)))
               ($err $err))))))

(= (claw:live-commit-pending-offset)
   (claw:live-commit-pending-offset-to-path (claw:tg-offset-path)))

(= (claw:live-results-committable? $results)
   ;; Unwrap pettaclaw-parity feedback shapes before scanning: the batch is
   ;; (RESULTS: (...)) and each item (COMMAND_RETURN: (cmd result)).
   (case $results
     (((RESULTS: $inner) (claw:live-results-committable-list? $inner))
      ($other (claw:live-results-committable-list? $other)))))

(= (claw:live-results-committable-list? $results)
   (if (== $results ())
       True
       (let ($head0 $tail) (decons-atom $results)
       (let $head (case $head0
                    (((COMMAND_RETURN: ($cmd $result)) $result)
                     ($o $o)))
            (case $head
              (((SendPreview $chat $text) False)
               ((SendFailed $chat $text $err) False)
               ((SendNoChat $text) False)
               ((ChildCommandsFailed $code $text) False)
               ((ChildCommandsTimeout $text) False)
               ((ChildCommandsOk $text)
                (if (or (claw:live-text-contains? $text "SendPreview")
                        (claw:live-text-contains? $text "SendFailed"))
                    False
                    (claw:live-results-committable-list? $tail)))
               ($other (claw:live-results-committable-list? $tail))))))))

(= (claw:live-finalize-after-offset (OffsetCommitted $offset))
   (LiveCommitted HistoryAppended (OffsetCommitted $offset)))

(= (claw:live-finalize-after-offset NoPendingOffset)
   (LiveCommitted HistoryAppended NoPendingOffset))

(= (claw:live-finalize-after-offset (OffsetCommitFailed $offset $err))
   (LiveNotCommitted (OffsetCommitFailed $offset $err)))

(= (claw:live-finalize-after-history HistoryAppended)
   (claw:live-finalize-after-offset (claw:live-commit-pending-offset)))

(= (claw:live-finalize-after-history HistoryNotConfigured)
   (LiveNotCommitted HistoryNotConfigured))

(= (claw:live-finalize-after-history (HistoryAppendFailed $err))
   (LiveNotCommitted (HistoryAppendFailed $err)))

(= (claw:live-finalize-to-paths-after-history HistoryAppended $offset-path)
   (claw:live-finalize-after-offset
     (claw:live-commit-pending-offset-to-path $offset-path)))

(= (claw:live-finalize-to-paths-after-history HistoryNotConfigured $offset-path)
   (LiveNotCommitted HistoryNotConfigured))

(= (claw:live-finalize-to-paths-after-history
      (HistoryAppendFailed $err) $offset-path)
   (LiveNotCommitted (HistoryAppendFailed $err)))

(= (claw:live-finalize-to-paths $history-path $offset-path $msg $raw $results $commit)
   (if $commit
       (if (claw:live-results-committable? $results)
           (claw:live-finalize-to-paths-after-history
             (claw:live-append-history-to-path $history-path $msg $raw)
             $offset-path)
           (LiveNotCommitted SendNotDelivered))
       (LivePreviewOnly (get-state &reply-chat) (get-state &pending-offset))))

(= (claw:live-finalize $msg $raw $results $commit)
   (claw:live-finalize-new $msg $raw $results True $commit))

(= (claw:live-history-worthy? $results $msgnew)
   ;; pettaclaw parity: append unless the message is stale AND no commands ran.
   (or $msgnew (not (or (== $results ()) (== $results (RESULTS: ()))))))

(= (claw:live-finalize-new $msg $raw $results $msgnew $commit)
   (if $commit
       (if (claw:live-results-committable? $results)
           (claw:live-finalize-after-history
             (if (claw:live-history-worthy? $results $msgnew)
                 (claw:live-append-history-new $msg $raw $msgnew)
                 HistorySkipped))
           (LiveNotCommitted SendNotDelivered))
       (LivePreviewOnly (get-state &reply-chat) (get-state &pending-offset))))
