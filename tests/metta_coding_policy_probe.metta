!(import! &self (library lib_import))
!(import! &self ./src/metta_coding_policy)

(= (assertEqual $A $B) (assert (== $A $B)))
!(bind! &coding-execution-count (new-state 0))

;; Transformations are ordinary open MeTTa equations, not kernel cases.
(= (coding-transform append-new
      (coding-view $messages $advertised))
   (success
     (coding-view
       (coding-message-append-one $messages (coding-message user new))
       $advertised)))
(= (coding-transform clear-messages
      (coding-view $messages $advertised))
   (success (coding-view coding-messages-empty $advertised)))
(= (coding-transform broken $visible) failure)

;; The executor is an open adapter below the authority gates.  The second
;; equation is a tripwire: an unknown command must not evaluate it.
(= (coding-execute workspace-0
      (coding-command metta-eval (read-file "x")))
   (progn
     (change-state! &coding-execution-count
                    (+ 1 (get-state &coding-execution-count)))
     (execution-success workspace-1 file-content)))
(= (coding-execute workspace-0 (coding-command invented payload))
   (progn
     (change-state! &coding-execution-count 999)
     (execution-success forged-workspace forged-result)))
(= (coding-execute workspace-0 (coding-command denied-tool payload))
   (progn
     (change-state! &coding-execution-count 999)
     (execution-success forged-workspace forged-result)))
(= (coding-execute workspace-0 (coding-command fail-tool payload))
   (progn
     (change-state! &coding-execution-count
                    (+ 1 (get-state &coding-execution-count)))
     (execution-failure expected-error)))

!(let* (($initial
          (coding-boundary
            (coding-message-list
              (coding-message user original) coding-messages-empty)
            (coding-capability-list described coding-capabilities-empty)
            (coding-capability-list metta-eval
              (coding-capability-list fail-tool
                (coding-capability-list denied-tool
                  coding-capabilities-empty)))
            (coding-capability-list metta-eval
              (coding-capability-list fail-tool
                coding-capabilities-empty))))
         ($prepared
          (coding-run-transforms
            $initial
            (coding-transform-list append-new
              (coding-transform-list broken coding-transforms-empty))))
         ($_ (assertEqual
               (coding-boundary-messages $prepared)
               (coding-message-list
                 (coding-message user original)
                 (coding-message-list
                   (coding-message user new) coding-messages-empty))))
         ($_ (assertEqual
               (coding-boundary-executable $prepared)
               (coding-boundary-executable $initial)))
         ($_ (assertEqual
               (coding-boundary-permitted $prepared)
               (coding-boundary-permitted $initial)))
         ($succeeded
          (coding-step
            (coding-state $prepared workspace-0)
            (coding-command metta-eval (quote (read-file "x")))))
         ($_ (assertEqual (get-state &coding-execution-count) 1))
         ($_ (assertEqual (coding-state-workspace $succeeded) workspace-1))
         ($_ (assertEqual
               (coding-boundary-messages
                 (coding-state-boundary $succeeded))
               (coding-message-list
                 (coding-message user original)
                 (coding-message-list
                   (coding-message user new)
                   (coding-message-list
                     (coding-message tool
                       (command-succeeded metta-eval file-content))
                     coding-messages-empty)))))
         ($failed
          (coding-step
            (coding-state $initial workspace-0)
            (coding-command fail-tool payload)))
         ($_ (assertEqual (get-state &coding-execution-count) 2))
         ($_ (assertEqual (coding-state-workspace $failed) workspace-0))
         ($_ (assertEqual
               (coding-boundary-messages (coding-state-boundary $failed))
               (coding-message-list
                 (coding-message user original)
                 (coding-message-list
                   (coding-message tool
                     (command-failed fail-tool expected-error))
                   coding-messages-empty))))
         ($denied
          (coding-step
            (coding-state $initial workspace-0)
            (coding-command denied-tool payload)))
         ($_ (assertEqual (get-state &coding-execution-count) 2))
         ($_ (assertEqual (coding-state-workspace $denied) workspace-0))
         ($unknown
          (coding-step
            (coding-state $initial workspace-0)
            (coding-command invented payload)))
         ($_ (assertEqual (get-state &coding-execution-count) 2))
         ($_ (assertEqual (coding-state-workspace $unknown) workspace-0)))
     (println! METTA_CODING_POLICY_OK))
