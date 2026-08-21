;; Replaceable bridge from MeTTa policy code to a captured Iter process fold.
;; JSON is the boundary representation.  The adapter reproduces the ordinary
;; two-rule kernel's replacement/stutter fold without changing that kernel.
(= (iter-process-run-json $directory $messages-json $tools-json)
   (py-call
     (iter_process_adapter.run_json $directory $messages-json $tools-json)))

;; Request-local structured bridge used by the real turn path.  Python owns
;; only JSON/process isolation; selection and sequencing remain MeTTa policy.
(= (iter-process-prepare-request
      $system-message $activity-message $advertised $run-iter)
   (py-call
     (iter_process_adapter.prepare_request_json
       $system-message $activity-message $advertised $run-iter)))

(= (iter-process-render-request $prepared-json)
   (py-call (iter_process_adapter.render_request_json $prepared-json)))

(= (iter-process-request-observations $prepared-json)
   (py-call (iter_process_adapter.render_observations_json $prepared-json)))
