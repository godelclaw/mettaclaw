;; Exercise repeated provider failures through the real SWI-PeTTa/Janus
;; evaluation boundary.  The explicit sequence avoids conflating transport
;; lifetime with recursive arithmetic or multi-match evaluation semantics.
!(let* (($_00 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_01 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_02 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_03 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_04 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_05 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_06 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_07 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_08 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_09 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_10 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($_11 (py-call (synthetic_llm.chat "local-test-model" 1 "low" "local timeout probe")))
         ($fdCount (py-call (builtins.len (py-call (os.listdir "/proc/self/fd")))))
         ($_12 (println! (PROVIDER_TIMEOUTS_COMPLETE $fdCount))))
     (empty))
