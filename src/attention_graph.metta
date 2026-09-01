;; A bounded, typed graph for the present cognitive turn.  Durable semantic
;; memory remains responsible for long-range recall; this space only makes the
;; active event, task, proposal, and receipt relations explicit.
!(bind! &attention (new-space))

(= (attention-clear)
   (collapse
     (match &attention $atom
            (remove-atom &attention $atom))))

(= (attention-begin $turn $source $hasPriorReceipt)
   (progn
     (attention-clear)
     (add-atom &attention (node (event $turn) event $source))
     (add-atom &attention (node (task $turn) task respond-to-foreground))
     (add-atom &attention
               (edge (event $turn) foreground-of (task $turn)))
     (if $hasPriorReceipt
         (progn
           (add-atom &attention (node prior-receipt receipt))
           (add-atom &attention
                     (edge prior-receipt evidence-for (task $turn))))
         _)
     True))

(= (attention-complete $turn $outcome)
   (progn
     (add-atom &attention (node (proposal $turn) proposal))
     (add-atom &attention
               (edge (task $turn) proposes (proposal $turn)))
     (add-atom &attention (node (receipt $turn) receipt $outcome))
     (add-atom &attention
               (edge (proposal $turn) observed-as (receipt $turn)))
     True))

(= (attention-view)
   (collapse (get-atoms &attention)))
