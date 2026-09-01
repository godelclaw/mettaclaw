;; The complete ordinary process kernel.  Policy adapters may compute any
;; replacement periphery; the kernel observes only success or failure.
(= (process-step (rooted $root $periphery) (success $next))
   (rooted $root $next))
(= (process-step $state failure) $state)
