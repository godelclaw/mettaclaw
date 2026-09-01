!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

(= (assertEqual $A $B) (assert (== $A $B)))

;; A prose answer never becomes an executable pseudo-command. The parser
;; projects it to the empty command sequence, and pacing—not energy loss—is
;; the recovery transition.
!(let* (($commands
          (model-response-commands
            (model-response-read
              (model-response-envelope "Understood, but not a command"))))
         ($_ (assertEqual $commands ()))
         ($before
           (coordinate loops 12
             (coordinate sleep-interval 1 coordinates-empty)))
         ($failed (applyProtocolPacing 1 60 $before no-commands))
         ($_ (assertEqual (loop-budget $failed) 12))
         ($_ (assertEqual (loop-sleep $failed) 60))
         ($answered (applyProtocolPacing 1 60 $failed commands-parsed))
         ($_ (assertEqual (loop-budget $answered) 12))
         ($_ (assertEqual (loop-sleep $answered) 1)))
     (println! PROTOCOL_RECOVERY_OK))
