!(import! &self ./src/three_policy_process_host)

(= (host-state)
   (rooted protected-root
     (three-policy-periphery development-0 life-0 coding-0 agent)))

!(test
   (invoke-isolated-process
     (host-state) "tests/fixtures/process_replace.py")
   (rooted protected-root
     (three-policy-periphery
       development-new life-new coding-new iter)))

;; Import or runtime failure is data: the last state remains live.
!(test
   (invoke-isolated-process
     (host-state) "tests/fixtures/process_fail.py")
   (host-state))

!(println! THREE_POLICY_PROCESS_HOST_OK)
