;; runtime/pending_send.metta — the approval-gated send queue.
;; A previewed (un-approved) send is journaled to CETTACLAW_PENDING_SEND_PATH so
;; an operator (or an approved restart) can deliver it later: on approval it
;; sends via src/telegram, then appends history + commits the offset (commit)
;; and clears the journal. This is what lets live sends stay externally gated
;; without losing the turn.
!(import! &self fs)
!(import! &self str)
!(import! &self ../src/config.metta)
!(import! &self ../src/telegram.metta)
!(import! &self ../src/utils.metta)
!(import! &self ../src/channels.metta)
!(import! &self ./commit.metta)

(= (claw:live-pending-send-path)
   (let $p (claw:setting "CETTACLAW_PENDING_SEND_PATH")
        (if (== $p NotFound)
            (str:concat (claw:home) "/.config/cettaclaw/pending_send.metta")
            $p)))

(= (claw:live-first-send-preview $results)
   (if (== $results ())
       NoPendingSend
       (let ($head $tail) (decons-atom $results)
            (case $head
              (((SendPreview $chat $text) (PendingSendCandidate $chat $text))
               ($other (claw:live-first-send-preview $tail)))))))

(= (claw:live-pending-send-record $chat $offset $text $msg-text $raw)
   (PendingSend $chat $offset $text $msg-text $raw))

(= (claw:live-write-pending-send-offset-to-path $path $offset $msg $raw $results)
   (case (claw:live-first-send-preview $results)
     (((PendingSendCandidate $chat $text)
       (if (or (== $offset "") (== $chat ""))
           NoPendingSend
           (let $record
                (claw:live-pending-send-record
                  $chat $offset $text (claw:msg-text $msg) $raw)
           (let $write (catch (fs:write-text $path (str:concat (repr $record) "\n")))
                (case $write
                  (((catch ()) (PendingSendWritten $chat $offset))
                   (() (PendingSendWritten $chat $offset))
                   ($err (PendingSendWriteFailed $err))))))))
      ($other NoPendingSend))))

(= (claw:live-write-pending-send-to-path $path $msg $raw $results)
   (claw:live-write-pending-send-offset-to-path
     $path (get-state &pending-offset) $msg $raw $results))

(= (claw:live-write-pending-send $msg $raw $results)
   (claw:live-write-pending-send-to-path
     (claw:live-pending-send-path) $msg $raw $results))

(= (claw:live-pending-send-from-parsed $parsed)
   (case $parsed
     (((PendingSend $chat $offset $text $msg-text $raw)
       (PendingSend $chat $offset $text $msg-text $raw))
      ($other NoPendingSend))))

(= (claw:live-pending-send-from-text $value)
   (case $value
     (((FsError $msg) (PendingSendReadFailed (FsError $msg)))
      ($text (claw:live-pending-send-from-parsed (parse $text))))))

(= (claw:live-read-pending-send-from-path $path)
   (if (fs:exists $path)
       (claw:live-pending-send-from-text (fs:read-text $path))
       NoPendingSend))

(= (claw:live-read-pending-send)
   (claw:live-read-pending-send-from-path (claw:live-pending-send-path)))

(= (claw:live-clear-pending-send-to-path $path)
   (case (catch (fs:write-text $path "(NoPendingSend)\n"))
     (((catch ()) PendingSendCleared)
      (() PendingSendCleared)
      ($err (PendingSendClearFailed $err)))))

(= (claw:live-send-pending-clear-after-commit $path $chat $offset $status)
   (case (claw:live-clear-pending-send-to-path $path)
     ((PendingSendCleared
       (PendingSendCommitted
         $chat $offset $status HistoryAppended
         (OffsetCommitted $offset) PendingSendCleared))
      ($err
       (PendingSendPostCommitClearFailed
         $chat $offset $status HistoryAppended
         (OffsetCommitted $offset) $err)))))

(= (claw:live-send-pending-commit-after-history $path $chat $offset $status)
   (case (claw:live-commit-offset $offset)
     (((OffsetCommitted $committed)
       (claw:live-send-pending-clear-after-commit
         $path $chat $committed $status))
      ($err (PendingSendPostSendFailed $chat $offset $status $err)))))

(= (claw:live-send-pending-record-after-send
      $path $chat $offset $status $msg-text $raw)
   (case (claw:live-append-history-text $msg-text $raw)
     ((HistoryAppended
       (claw:live-send-pending-commit-after-history
         $path $chat $offset $status))
      ($err (PendingSendPostSendFailed $chat $offset $status $err)))))

(= (claw:live-send-pending-approved
      $path $chat $offset $text $msg-text $raw)
   (case (claw:tg-send $chat $text)
     (((HttpResult 200 $body)
       (claw:live-send-pending-record-after-send
         $path $chat $offset 200 $msg-text $raw))
      ((HttpResult $status $body)
       (PendingSendFailed $chat $offset (HttpStatus $status)))
      ($other (PendingSendFailed $chat $offset $other)))))

(= (claw:live-send-pending-from-path $path)
   (case (claw:live-read-pending-send-from-path $path)
     (((PendingSend $chat $offset $text $msg-text $raw)
       (case (claw:send-approved?)
         ((True
           (claw:live-send-pending-approved
             $path $chat $offset $text $msg-text $raw))
          ($other (PendingSendNeedsApproval $chat $offset $text)))))
      ((PendingSendReadFailed $err) (PendingSendReadFailed $err))
      ($other NoPendingSend))))

(= (claw:live-send-pending)
   (claw:live-send-pending-from-path (claw:live-pending-send-path)))

(= (claw:live-store-pending-from-turn-to-path $path $turn)
   (case $turn
     (((LiveTurn $msg $msgnew $humanmsg $raw (LiveActed $cmds $results) $finish)
       (case $finish
         (((LivePreviewOnly $chat $offset)
           (claw:live-write-pending-send-offset-to-path
             $path $offset $msg $raw $results))
          ((LiveNotCommitted SendNotDelivered)
           (claw:live-write-pending-send-to-path $path $msg $raw $results))
          ($other NoPendingSend))))
      ($other NoPendingSend))))

(= (claw:live-store-pending-from-turn $turn)
   (claw:live-store-pending-from-turn-to-path
     (claw:live-pending-send-path) $turn))
