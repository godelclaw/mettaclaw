!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

!(let $result
      (iter-process-run-json
        "./tests/fixtures/iter_processes" "[1]" "[]")
   (if (== (py-call (helper.text_nonempty $result)) 1)
       (println! ITER_PROCESS_ADAPTER_OK)
       (println! ITER_PROCESS_ADAPTER_EMPTY)))
