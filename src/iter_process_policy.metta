;; Replaceable bridge from MeTTa policy code to a captured Iter process fold.
;; JSON is the boundary representation.  The adapter reproduces the ordinary
;; two-rule kernel's replacement/stutter fold without changing that kernel.
(= (iter-process-run-json $directory $messages-json $tools-json)
   (py-call
     (iter_process_adapter.run_json $directory $messages-json $tools-json)))
