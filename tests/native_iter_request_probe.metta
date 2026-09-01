!(import! &self (library lib_import))
!(import! &self ./src/utils)
!(import! &self ./src/iter_process_policy)
!(import! &self ./src/metta_coding_policy)

!(let* (($prepared
          (iter-process-prepare-request system activity advertised 1))
         ($prompt (iter-process-render-request $prepared))
         ($observations (iter-process-request-observations $prepared)))
     (println!
       (NATIVE_ITER_REQUEST_OK $prompt $observations)))
