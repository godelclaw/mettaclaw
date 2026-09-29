!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

(= (assertEqual $A $B) (assert (== $A $B)))

;; No mode renders the legacy request any more; a policy of the base fragment
;; alone still must, byte for byte.
(= (policy-preset unstructured) (stage-list base stages-empty))

!(let* (($_ (assertEqual (policy-structured-request godelclaw) 1))
         ($_ (assertEqual (policy-structured-request coding) 1))
         ($_ (assertEqual (policy-iter-transformations godelclaw) 1))
         ($_ (assertEqual (policy-iter-transformations coding) 1))
         ($legacy
          (coding-prepare-request unstructured legacy system activity advertised))
         ($_ (assertEqual (coding-request-prompt $legacy) legacy))
         ($_ (assertEqual (coding-request-observations $legacy) ""))
         ($structured
          (coding-prepare-request godelclaw legacy system activity advertised))
         ($_ (coding-request-prompt $structured))
         ($observations (coding-request-observations $structured))
         ($_ (assertEqual (== $observations "") False)))
     (println! STRUCTURED_REQUEST_OK))
