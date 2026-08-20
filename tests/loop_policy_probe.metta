!(import! &self ./src/weak_process_core)
!(import! &self ./src/open_assemblage)
!(import! &self ./src/loop_policy)

(= (assertEqual $A $B) (assert (== $A $B)))

!(let* (($periphery
          (coordinate iteration 7
            (coordinate loops 12
              (coordinate sleep-interval 3
                (coordinate last-results ok
                  (coordinate last-heartbeat 9
                    (coordinate active-policy agent
                      (coordinate autonomous-ready 0 coordinates-empty))))))))
         ($_ (assertEqual (loop-iteration $periphery) 7))
         ($_ (assertEqual (loop-budget $periphery) 12))
         ($_ (assertEqual (policy-burst-budget agent) 50))
         ($_ (assertEqual (policy-idle-wait iter) 60))
         ($_ (assertEqual (policy-autonomous-renewal agent) False))
         ($_ (assertEqual (policy-autonomous-renewal iter) True))
         ($_ (assertEqual (policy-reasoning coding medium) high))
         ($_ (assertEqual (policy-burst-budget iter-coding) 50))
         ($_ (assertEqual (policy-idle-wait iter-coding) 60))
         ($_ (assertEqual (policy-autonomous-renewal iter-coding) True))
         ($_ (assertEqual (policy-reasoning iter-coding medium) high))
         ($_ (assertEqual
               (policy-compile (stage-list missing-stage stages-empty))
               (policy-error unknown-stage missing-stage)))
         ($_ (assertEqual (policy-reasoning agent medium) medium))
         ($_ (assertEqual (policy-wait-seconds agent 0 3 0) 3))
         ($_ (assertEqual (policy-wait-seconds iter 0 3 0) 60))
         ($_ (assertEqual (policy-wait-seconds iter 0 600 1) 600))
         ($_ (assertEqual (policy-autonomous-turn iter 1 False 0) True))
         ($_ (assertEqual (policy-autonomous-turn agent 1 False 0) False))
         ($_ (loop-directives-clear))
         ($_ (loop-directive-set loops 0))
         ($_ (loop-directive-set sleep-interval 900))
         ($rested (loop-directives-apply $periphery))
         ($_ (assertEqual (loop-budget $rested) 0))
         ($_ (assertEqual (loop-sleep $rested) 900))
         ($_ (assertEqual (loop-last-results $rested) ok))
         ($_ (loop-directives-clear)))
     (println! LOOP_POLICY_OK))
