;; A failure-transactional process around one protected root.
;; Successful processes may replace the entire periphery.  Failure stutters.

(= (process-step (rooted $root $periphery) (success $next))
   (rooted $root $next))
(= (process-step $state failure) $state)

(= (process-run $state ()) $state)
(= (process-run $state (cons $outcome $rest))
   (process-run (process-step $state $outcome) $rest))

(= (process-root (rooted $root $periphery)) $root)
(= (process-periphery (rooted $root $periphery)) $periphery)
