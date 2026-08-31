;; One Iter transformation runs in one fresh SWI-PeTTa process.
;; The host passes a captured .metta source path and a visible-request file.

!(import! &self (library lib_import))
!(import_prolog_functions_from_file
    ./src/native_iter_worker.pl
    (native_iter_read_visible native_iter_write_result))
!(import! &self ./metta_coding_policy)

(= (native-iter-emit $path $result)
   (progn
     (translatePredicate (native_iter_write_result $path $result))
     True))

!(let* (($transformation (argv 1))
         ($visible-path (argv 2))
         ($result-path (argv 3))
         ($_ (import! &self $transformation))
         ;; Transport one exact SWI term without importing the value as
         ;; executable source.  The Iter transformation itself remains MeTTa.
         ($visible (native_iter_read_visible $visible-path))
         ;; Quote the request at the transformation boundary.  It is an Iter
         ;; value, not a program for the evaluator to traverse.
         ;; `iter-transform` was imported dynamically above, so dispatch it at
         ;; runtime; quoting keeps the visible request data opaque to eval.
         ($outcomes (collapse (eval (iter-transform (quote $visible)))))
         ($_ (native-iter-emit
               $result-path (native-iter-worker-results $outcomes))))
     (native-iter-worker-results $outcomes))
