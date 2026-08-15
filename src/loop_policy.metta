;; Replaceable life-policy data and per-turn directives.  This file is not
;; part of the two-equation process kernel.

!(bind! &loop-directives (new-state coordinates-empty))

(= (loop-directives-clear)
   (change-state! &loop-directives coordinates-empty))
(= (loop-directive-set $name $value)
   (change-state! &loop-directives
     (coordinate-set $name $value (get-state &loop-directives))))
(= (loop-directives-apply $periphery)
   (coordinate-overlay (get-state &loop-directives) $periphery))

(= (loop-iteration $periphery)
   (coordinate-get-or iteration 1 $periphery))
(= (loop-budget $periphery)
   (coordinate-get-or loops 0 $periphery))
(= (loop-sleep $periphery)
   (coordinate-get-or sleep-interval 1 $periphery))
(= (loop-last-results $periphery)
   (coordinate-get-or last-results "" $periphery))
(= (loop-last-heartbeat $periphery)
   (coordinate-get-or last-heartbeat 0 $periphery))
(= (loop-active-policy $periphery)
   (coordinate-get-or active-policy agent $periphery))
(= (loop-autonomous-ready $periphery)
   (coordinate-get-or autonomous-ready 0 $periphery))
(= (loop-pending-continuation $periphery)
   (coordinate-get-or pending-continuation no-continuation $periphery))

;; Four-coordinate source records.  Adding a mode adds one equation here;
;; neither the generic policy functions nor the process core changes.
;; reasoning=inherit means use the configured model default.
(= (policy-record agent)  (policy 50 1 False inherit))
(= (policy-record iter)   (policy 50 60 True inherit))
(= (policy-record coding) (policy 50 1 False high))

(= (policy-burst-budget $selected)
   (let (policy $budget $idle $renew $reasoning) (policy-record $selected)
        $budget))
(= (policy-idle-wait $selected)
   (let (policy $budget $idle $renew $reasoning) (policy-record $selected)
        $idle))
(= (policy-autonomous-renewal $selected)
   (let (policy $budget $idle $renew $reasoning) (policy-record $selected)
        $renew))
(= (policy-reasoning $selected $default)
   (let (policy $budget $idle $renew $reasoning) (policy-record $selected)
        (if (== $reasoning inherit) $default $reasoning)))

(= (policy-wait-seconds $selected $loops $requested $paused)
   (if (and (and (policy-autonomous-renewal $selected) (<= $loops 0))
            (== $paused 0))
       (policy-idle-wait $selected)
       $requested))

(= (policy-autonomous-turn $selected $ready $has-activity $paused)
   (and (and (policy-autonomous-renewal $selected) (== $ready 1))
        (and (not $has-activity) (== $paused 0))))

(= (policy-next-autonomous-ready $selected $loops $wait-timed-out $paused)
   (if (and (and (policy-autonomous-renewal $selected) (<= $loops 0))
            (and (== $wait-timed-out 1) (== $paused 0)))
       1
       0))
