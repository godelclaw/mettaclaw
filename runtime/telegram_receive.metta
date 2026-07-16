;; runtime/telegram_receive.metta — live Telegram inbox-session adapter.
;;
;; This is runtime/daemon machinery, not part of the thin agent core.  It turns
;; getUpdates batches into keyed Msg values, tracks reply chat and pending offset,
;; drains queued updates FIFO, and keeps the last reply route for follow-up
;; turns. PeTTaClaw consumes each queued message once: after that, the model may
;; keep working, but HUMAN-LAST-MSG is empty until another update arrives.

!(import! &self ../src/telegram.metta)
!(import! &self ../src/channels.metta)

(= (claw:live-real-message? $msg)
   (not (== (claw:msg-key $msg) "")))

(= (claw:live-store-last-message $chat $msg)
   (let $_ (change-state! &live-last-msg (LiveLastMessage $chat $msg))
        $msg))

(= (claw:live-continue-after-last-message)
   (case (get-state &live-last-msg)
     (((LiveLastMessage $chat $msg)
       (let $_ (change-state! &reply-chat $chat)
       (let $__ (change-state! &pending-offset "")
            (Msg bot (claw:msg-key $msg) ""))))
      ($other
       (let $_ (change-state! &reply-chat "")
       (let $__ (change-state! &pending-offset "")
            (Msg bot "" "")))))))

(= (claw:live-receive-from-tg-with-offset $tg $offset)
   (case $tg
     (((TgMessage $update-id $chat-id $sender $text $kind)
       (let $_ (change-state! &reply-chat $chat-id)
       (let $__ (change-state! &pending-offset $offset)
       (let $msg (Msg $sender $update-id $text)
            (claw:live-store-last-message $chat-id $msg)))))
      ($other
       (if (== $offset "")
           (claw:live-continue-after-last-message)
           (let $_ (change-state! &reply-chat "")
           (let $__ (change-state! &pending-offset $offset)
                (Msg bot "" ""))))))))

(= (claw:live-receive-from-tg $tg)
   (case $tg
     (((TgMessage $update-id $chat-id $sender $text $kind)
       (claw:live-receive-from-tg-with-offset
         $tg (claw:tg-decimal-inc $update-id)))
      ($other (claw:live-receive-from-tg-with-offset TgNoMessage "")))))

(= (claw:live-receive-from-tg-receive $receive)
   (case $receive
     (((TgReceive $tg $offset)
       (case $tg
         (((TgMessage $update-id $chat-id $sender $text $kind)
           (let $_ (change-state! &reply-chat $chat-id)
           (let $__ (change-state! &pending-offset (claw:tg-next-offset $tg))
                (Msg $sender $update-id $text))))
          ($other
           (let $_ (change-state! &reply-chat "")
           (let $__ (change-state! &pending-offset $offset)
                (Msg bot "" "")))))))
      ($other (claw:live-receive-from-tg TgNoMessage)))))

(= (claw:live-receive-from-batch $batch)
   (case $batch
     (((TgReceiveBatch $queued $offset)
       (if (== $queued ())
           (let $_ (change-state! &tg-queue (TgQueue ()))
                (claw:live-receive-from-tg-with-offset TgNoMessage $offset))
           (let ($head $tail) (decons-atom $queued)
           (let $_ (change-state! &tg-queue (TgQueue $tail))
                (claw:live-receive-from-tg-with-offset
                  $head (claw:tg-next-offset $head))))))
      ($other (claw:live-receive-from-tg TgNoMessage)))))

(= (claw:live-receive-from-queued-state)
   (let $queue (get-state &tg-queue)
        (case $queue
          (((TgQueue ()) NoQueuedTelegramMessage)
           ((TgQueue $items)
            (let ($head $tail) (decons-atom $items)
            (let $_ (change-state! &tg-queue (TgQueue $tail))
                 (claw:live-receive-from-tg-with-offset
                   $head (claw:tg-next-offset $head)))))
           ($other NoQueuedTelegramMessage)))))

(= (claw:live-receive-from-body $body)
   (let $_ (once (claw:tg-log-updates-from-body $body))
        (claw:live-receive-from-batch
          (claw:tg-receive-batch-from-body-explicit
            $body
            (claw:tg-allow-private?)
            (claw:tg-allowed-chat-ids)))))

(= (claw:live-receive-from-body-explicit $body $allow-private $allowed-chat-ids)
   (claw:live-receive-from-batch
     (claw:tg-receive-batch-from-body-explicit
       $body $allow-private $allowed-chat-ids)))

(= (claw:live-receive-from-body-log-explicit
      $body $log-path $received-at $allow-private $allowed-chat-ids)
   (let $_ (once (claw:tg-log-updates-from-body-explicit
                   $log-path $received-at $allow-private $allowed-chat-ids $body))
        (claw:live-receive-from-body-explicit
          $body $allow-private $allowed-chat-ids)))

(= (claw:live-receive $timeout-s)
   (case (claw:live-receive-from-queued-state)
     ((NoQueuedTelegramMessage
       (case (claw:tg-get-updates (claw:tg-read-offset) $timeout-s)
         (((HttpResult 200 $body) (claw:live-receive-from-body $body))
          ($other (claw:live-receive-from-tg TgNoMessage)))))
      ($queued $queued))))
