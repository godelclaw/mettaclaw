;; runtime/loop_driver.metta — bounded / streamed / forever live loops, each
;; optionally run-lock guarded. The stream variant discards the per-turn
;; transcript so a long daemon run does not grow the parent's memory. The
;; preview-store path journals an un-approved send for later approval.
!(import! &self ./turn_driver.metta)
!(import! &self ./run_lock.metta)
!(import! &self ./pending_send.metta)

(= (claw:live-loop-step $timeout-s $commit)
   (let $turn (claw:live-one-turn $timeout-s $commit)
   (let $slept (claw:live-sleep-current)
        (LiveLoopStep $turn $slept))))

(= (claw:live-loop-n $n $timeout-s $commit)
   (if (<= $n 0)
       ()
       (let $step (claw:live-loop-step $timeout-s $commit)
       (let $rest (claw:live-loop-n (- $n 1) $timeout-s $commit)
            (cons-atom $step $rest)))))

;; Daemon-friendly bounded loop: execute and commit each turn, but do not
;; retain the full LiveTurn/LiveLoopStep transcript list in the parent.
(= (claw:live-loop-step-discard $timeout-s $commit)
   (let $_turn (claw:live-one-turn $timeout-s $commit)
   (let $_sleep (claw:live-sleep-current)
        LiveLoopStepDone)))

(= (claw:live-loop-n-stream-count $n $timeout-s $commit $done)
   (if (<= $n 0)
       (LiveLoopStreamDone $done)
       (let $_ (claw:live-loop-step-discard $timeout-s $commit)
            (claw:live-loop-n-stream-count
              (- $n 1) $timeout-s $commit (+ $done 1)))))

(= (claw:live-loop-n-stream $n $timeout-s $commit)
   (claw:live-loop-n-stream-count $n $timeout-s $commit 0))

(= (claw:live-loop-forever $timeout-s $commit)
   (let $_ (claw:live-loop-step $timeout-s $commit)
        (claw:live-loop-forever $timeout-s $commit)))

(= (claw:live-loop-n-locked-to-path $path $n $timeout-s $commit)
   (case (claw:live-acquire-run-lock-to-path $path)
     (((RunLockAcquired $p)
       (let $steps (claw:live-loop-n $n $timeout-s $commit)
       (let $released (claw:live-release-run-lock-to-path $p)
            (LockedLoopDone $p $steps $released))))
      ($busy $busy))))

(= (claw:live-loop-n-stream-locked-to-path $path $n $timeout-s $commit)
   (case (claw:live-acquire-run-lock-to-path $path)
     (((RunLockAcquired $p)
       (let $summary (claw:live-loop-n-stream $n $timeout-s $commit)
       (let $released (claw:live-release-run-lock-to-path $p)
            (LockedLoopStreamDone $p $summary $released))))
      ($busy $busy))))

(= (claw:live-loop-forever-locked-to-path $path $timeout-s $commit)
   (case (claw:live-acquire-run-lock-to-path $path)
     (((RunLockAcquired $p)
       (claw:live-loop-forever $timeout-s $commit))
      ($busy $busy))))

(= (claw:live-one-turn-preview-store-to-path $timeout-s $path)
   (let $turn (claw:live-one-turn-preview $timeout-s)
   (let $pending (claw:live-store-pending-from-turn-to-path $path $turn)
        (LivePreviewStored $turn $pending))))

(= (claw:live-one-turn-preview-store $timeout-s)
   (claw:live-one-turn-preview-store-to-path
     $timeout-s (claw:live-pending-send-path)))
