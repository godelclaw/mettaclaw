;; Iter-style failure isolation is an adapter around the two-equation core.

!(import! &self ./src/three_policy_core)

(= (wire-outcome (1 $next)) (success $next))
(= (wire-outcome (0 $error)) failure)

(= (invoke-isolated-process $state $path)
   (let $wire
        (py-call
          (process_host.invoke $path (process-periphery $state)))
        (process-step $state (wire-outcome $wire))))
