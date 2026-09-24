!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

(= (assertEqual $A $B) (assert (== $A $B)))

;; A well-formed command that runs and returns nothing is reported as such,
;; not as a format error in which nothing ran.
!(initMemory)
!(configure commchannel telegram)
!(let* (($_ (addition-effect-turn-begin 5))
        ($_ (addition-effect-broker 5 5
              (quote ((metta "(match &self (= (no-such-head) $y) $y)")))))
        ($errors (command-batch-errors 5))
        ($_ (assertEqual (car-atom (car-atom $errors))
                         command_returned_no_result)))
   (println! COMMAND_ERROR_LABELS_OK))
