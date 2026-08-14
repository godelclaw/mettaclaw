;; Attention is a view over the causal ledger, not a second mutable store.
;; These equations preserve the small MeTTa interface while the Python kernel
;; records turn facts and deterministically projects the familiar graph.

(= (attention-begin $turn $source $hasPriorReceipt $frontiers)
   (py-call (agent_kernel.begin_turn
              $turn $source $hasPriorReceipt $frontiers)))

(= (attention-complete $turn $outcome $receipt)
   (py-call (agent_kernel.complete_turn $turn $outcome $receipt)))

(= (attention-view)
   (sread (py-call (agent_kernel.attention_view_text))))
