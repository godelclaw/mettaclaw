!(import! &self ./src/three_policy_fusion)

(= (initial-state)
  (rooted protected-root
    (three-policy-periphery development-0 life-0 coding-0 agent)))

(= (mixed-trace)
  ((select iter)
   (development (success development-1))
   (life (success life-1))
   (development failure)
   (select coding)
   (coding (success coding-1))
   (life failure)
   (development (success development-2))))

(= (final-state)
  (rooted protected-root
    (three-policy-periphery development-2 life-1 coding-1 coding)))

!(test
   (three-policy-run (initial-state) (mixed-trace))
   (final-state))

;; A mixed trace preserves the protected root.
!(test
   (process-root
     (three-policy-run (initial-state) (mixed-trace)))
   protected-root)

;; Each projection is exactly its source-coordinate fold after erasure.
!(test
   (three-policy-development
     (three-policy-run (initial-state) (mixed-trace)))
   (coordinate-run
     (three-policy-development (initial-state))
     (development-actions (mixed-trace))))

!(test
   (three-policy-life
     (three-policy-run (initial-state) (mixed-trace)))
   (coordinate-run
     (three-policy-life (initial-state))
     (life-actions (mixed-trace))))

!(test
   (three-policy-coding
     (three-policy-run (initial-state) (mixed-trace)))
   (coordinate-run
     (three-policy-coding (initial-state))
     (coding-actions (mixed-trace))))

;; Selection changes no operational coordinate.
!(test
   (three-policy-step (initial-state) (select coding))
   (rooted protected-root
     (three-policy-periphery development-0 life-0 coding-0 coding)))

;; Independent candidate installations commute.
!(test
   (three-policy-run
     (initial-state)
     ((development (success development-x))
      (coding (success coding-x))))
   (three-policy-run
     (initial-state)
     ((coding (success coding-x))
      (development (success development-x)))))

!(println! THREE_POLICY_CORE_OK)
