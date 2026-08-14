!(import! &self (library lib_he))
!(import! &self ./src/attention_graph)

!(attention-begin turn-7 operator-event True "{}")
!(assertEqual
   (attention-view)
   ((node (event "turn-7") event "operator-event")
     (node (task "turn-7") task respond-to-foreground)
     (edge (event "turn-7") foreground-of (task "turn-7"))
     (frontier-fresh True)
     (pending-input False)
     (node prior-receipt receipt)
     (edge prior-receipt evidence-for (task "turn-7"))))

!(println! ATTENTION_GRAPH_OK)
