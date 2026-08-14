!(import! &self (library lib_he))
!(import! &self ./src/attention_graph)

!(attention-begin turn-7 operator-event True)
!(assertEqual
   (collapse
     (match &attention
            (edge (event turn-7) foreground-of (task turn-7))
            True))
   (True))
!(assertEqual
   (collapse
     (match &attention
            (edge prior-receipt evidence-for (task turn-7))
            True))
   (True))

!(attention-complete turn-7 commands-parsed)
!(assertEqual
   (collapse
     (match &attention
            (edge (task turn-7) proposes (proposal turn-7))
            True))
   (True))
!(assertEqual
   (collapse
     (match &attention
            (edge (proposal turn-7) observed-as (receipt turn-7))
            True))
   (True))

;; Starting a new turn bounds the space and does not invent prior evidence.
!(attention-begin turn-8 loop-tick False)
!(assertEqual
   (collapse
     (match &attention (node (event turn-7) $kind $source) True))
   ())
!(assertEqual
   (collapse
     (match &attention (node prior-receipt receipt) True))
   ())
!(println! ATTENTION_GRAPH_OK)
