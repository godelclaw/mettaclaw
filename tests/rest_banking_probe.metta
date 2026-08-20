;; Rest is a pause, not a spend: the budget crosses the sleep intact.
!(import! &self (library lib_import))
!(import! &self ./src/utils)
!(import! &self ./src/weak_process_core)
!(import! &self ./src/open_assemblage)
!(import! &self ./src/loop_policy)
!(import! &self ./src/loop)

(= (assertEqual $A $B) (assert (== $A $B)))

!(configure sleepInterval 1)

!(let* (($periphery
          (coordinate iteration 7
            (coordinate loops 43
              (coordinate sleep-interval 1
                (coordinate last-results ok
                  (coordinate last-heartbeat 9
                    (coordinate active-policy agent
                      (coordinate autonomous-ready 0
                        (coordinate banked-loops 0
                          (coordinate pending-continuation no-continuation
                            coordinates-empty))))))))))
         ;; An ordinary turn banks nothing.
         ($idle (applyRestBanking $periphery))
         ($_ (assertEqual (loop-budget $idle) 43))
         ($_ (assertEqual (coordinate-get-or banked-loops 0 $idle) 0))
         ;; Resting stops the burst and sets the remaining budget aside.
         ($_ (loop-directives-clear))
         ($_ (loop-directive-set rest-request 1))
         ($_ (loop-directive-set sleep-interval 600))
         ($resting (applyRestBanking (loop-directives-apply $periphery)))
         ($_ (assertEqual (loop-budget $resting) 0))
         ($_ (assertEqual (coordinate-get-or banked-loops 0 $resting) 43))
         ($_ (assertEqual (loop-sleep $resting) 600))
         ;; A rest in flight is visible in the periphery itself — no flag.
         ($_ (assertEqual (loop-resting $periphery) 0))
         ($_ (assertEqual (loop-resting $resting) 1))
         ;; Renewal is suspended for exactly as long as the rest lasts.
         ($_ (assertEqual (policy-next-autonomous-ready iter 0 1 (loop-resting $resting)) 0))
         ($_ (assertEqual (policy-next-autonomous-ready iter 0 1 (loop-resting $periphery)) 1))
         ;; Waking hands it back and returns idle pacing to normal.
         ($woken (applyRestRestore $resting))
         ($_ (assertEqual (loop-budget $woken) 43))
         ($_ (assertEqual (coordinate-get-or banked-loops 0 $woken) 0))
         ($_ (assertEqual (loop-sleep $woken) 1))
         ($_ (assertEqual (loop-resting $woken) 0))
         ;; Waking again mints nothing: the bank is empty and stays empty.
         ($again (applyRestRestore $woken))
         ($_ (assertEqual (loop-budget $again) 43))
         ($_ (assertEqual (coordinate-get-or banked-loops 0 $again) 0))
         ;; A timer continuation's own allowance survives the restore.
         ($_ (loop-directives-clear))
         ($continued
           (applyRestRestore
             (coordinate-set loops 2
               (coordinate-set banked-loops 1 $periphery))))
         ($_ (assertEqual (loop-budget $continued) 2))
         ($_ (loop-directives-clear)))
     (println! REST_BANKING_OK))
