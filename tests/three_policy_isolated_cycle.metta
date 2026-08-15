!(import! &self ./src/three_policy_process_host)

(= (cycle-initial)
   (rooted protected-root
     (three-policy-periphery
       (boundary () ())
       (living asleep)
       (coding-state workspace-0 () ready)
       agent)))

(= (cycle-final)
   (invoke-isolated-process
     (invoke-isolated-process
       (invoke-isolated-process
         (cycle-initial) "tests/fixtures/process_agent.py")
       "tests/fixtures/process_iter.py")
     "tests/fixtures/process_coding.py"))

!(test
   (cycle-final)
   (rooted protected-root
     (three-policy-periphery
       (boundary (context-transformed) (tool-advertised))
       (living human-wake)
       (coding-state
         workspace-1 (tool-result-observed) ready)
       coding)))

!(test (process-root (cycle-final)) protected-root)

!(println! THREE_POLICY_ISOLATED_CYCLE_OK)
