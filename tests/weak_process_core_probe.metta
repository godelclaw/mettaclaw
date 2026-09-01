!(import! &self ./src/weak_process_core)
!(import! &self ./src/open_assemblage)

(= (assertEqual $A $B) (assert (== $A $B)))

!(let* (($initial
          (rooted weak-process-core-v1
            (coordinate life awake
              (coordinate development iter-v1
                (coordinate coding episodic coordinates-empty)))))
         ($replaced
          (process-step $initial
            (success
              (coordinate life resting
                (coordinate new-policy learned coordinates-empty)))))
         ($_ (assertEqual (process-root $replaced) weak-process-core-v1))
         ($_ (assertEqual
               (coordinate-get life (process-periphery $replaced)) resting))
         ($_ (assertEqual
               (coordinate-get new-policy (process-periphery $replaced))
               learned))
         ($_ (assertEqual (process-step $initial failure) $initial))
         ($extended
          (coordinate-set reflection available (process-periphery $initial)))
         ($_ (assertEqual (coordinate-get reflection $extended) available))
         ($_ (assertEqual (coordinate-get life $extended) awake))
         ($_ (assertEqual (coordinate-get absent $extended)
                          (missing-coordinate absent)))
         ($_ (assertEqual
               (coordinate-set life resting
                 (coordinate-set coding continuous
                   (process-periphery $initial)))
               (coordinate-set coding continuous
                 (coordinate-set life resting
                   (process-periphery $initial))))))
     (println! WEAK_PROCESS_CORE_OK))
