!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

(= (assertEqual $A $B) (assert (== $A $B)))

!(let* (($periphery
          (coordinate iteration 7
            (coordinate loops 0
              (coordinate sleep-interval 1
                (coordinate last-results before
                  (coordinate last-heartbeat 9
                    (coordinate active-policy agent
                      (coordinate autonomous-ready 0
                        (coordinate pending-continuation
                          (continuation-value (metta "(+ 1 2)"))
                          coordinates-empty)))))))))
         ($early (applyTimedContinuation $periphery 0))
         ($_ (assertEqual (loop-pending-continuation $early)
                          (continuation-value (metta "(+ 1 2)"))))
         ($resumed (applyTimedContinuation $periphery 1))
         ($_ (assertEqual (loop-budget $resumed) 2))
         ($_ (assertEqual (loop-pending-continuation $resumed)
                          (quote no-continuation))))
     (println! REST_CONTINUATION_OK))
