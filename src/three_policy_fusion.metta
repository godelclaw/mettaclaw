;; Agent, Iter, and Coding are policy adapters over the weak process core.
;; This file names their product representation; three_policy_core.metta does
;; not.

!(import! &self ./src/three_policy_core)

(= (three-policy-propose
      (rooted $root
        (three-policy-periphery $development $life $coding $active))
      (select $policy))
   (success
     (three-policy-periphery $development $life $coding $policy)))

(= (three-policy-propose
      (rooted $root
        (three-policy-periphery $development $life $coding $active))
      (development (success $next)))
   (success
     (three-policy-periphery $next $life $coding $active)))
(= (three-policy-propose $state (development failure)) failure)

(= (three-policy-propose
      (rooted $root
        (three-policy-periphery $development $life $coding $active))
      (life (success $next)))
   (success
     (three-policy-periphery $development $next $coding $active)))
(= (three-policy-propose $state (life failure)) failure)

(= (three-policy-propose
      (rooted $root
        (three-policy-periphery $development $life $coding $active))
      (coding (success $next)))
   (success
     (three-policy-periphery $development $life $next $active)))
(= (three-policy-propose $state (coding failure)) failure)

(= (three-policy-step $state $action)
   (process-step $state (three-policy-propose $state $action)))

(= (three-policy-run $state ()) $state)
(= (three-policy-run $state (cons $action $rest))
   (three-policy-run (three-policy-step $state $action) $rest))

(= (three-policy-development
      (rooted $root
        (three-policy-periphery $development $life $coding $active)))
   $development)
(= (three-policy-life
      (rooted $root
        (three-policy-periphery $development $life $coding $active)))
   $life)
(= (three-policy-coding
      (rooted $root
        (three-policy-periphery $development $life $coding $active)))
   $coding)
(= (three-policy-active
      (rooted $root
        (three-policy-periphery $development $life $coding $active)))
   $active)

;; Source-coordinate quotients and trace erasures.

(= (coordinate-step $current (success $next)) $next)
(= (coordinate-step $current failure) $current)
(= (coordinate-run $current ()) $current)
(= (coordinate-run $current (cons $outcome $rest))
   (coordinate-run (coordinate-step $current $outcome) $rest))

(= (development-actions ()) ())
(= (development-actions (cons (select $policy) $rest))
   (development-actions $rest))
(= (development-actions (cons (development $outcome) $rest))
   (cons $outcome (development-actions $rest)))
(= (development-actions (cons (life $outcome) $rest))
   (development-actions $rest))
(= (development-actions (cons (coding $outcome) $rest))
   (development-actions $rest))

(= (life-actions ()) ())
(= (life-actions (cons (select $policy) $rest))
   (life-actions $rest))
(= (life-actions (cons (development $outcome) $rest))
   (life-actions $rest))
(= (life-actions (cons (life $outcome) $rest))
   (cons $outcome (life-actions $rest)))
(= (life-actions (cons (coding $outcome) $rest))
   (life-actions $rest))

(= (coding-actions ()) ())
(= (coding-actions (cons (select $policy) $rest))
   (coding-actions $rest))
(= (coding-actions (cons (development $outcome) $rest))
   (coding-actions $rest))
(= (coding-actions (cons (life $outcome) $rest))
   (coding-actions $rest))
(= (coding-actions (cons (coding $outcome) $rest))
   (cons $outcome (coding-actions $rest)))
