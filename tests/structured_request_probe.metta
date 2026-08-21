!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

(= (assertEqual $A $B) (assert (== $A $B)))

!(let* (($_ (assertEqual (policy-structured-request agent) 0))
         ($_ (assertEqual (policy-structured-request iter) 1))
         ($_ (assertEqual (policy-structured-request coding) 1))
         ($_ (assertEqual (policy-structured-request iter-coding) 1))
         ($_ (assertEqual (policy-iter-transformations agent) 0))
         ($_ (assertEqual (policy-iter-transformations coding) 0))
         ($_ (assertEqual (policy-iter-transformations iter) 1))
         ($_ (assertEqual (policy-iter-transformations iter-coding) 1))
         ($legacy
          (coding-prepare-request agent legacy system activity advertised))
         ($_ (assertEqual (coding-request-prompt $legacy) legacy))
         ($_ (assertEqual (coding-request-observations $legacy) ""))
         ($structured
          (coding-prepare-request iter legacy system activity advertised))
         ($_ (coding-request-prompt $structured))
         ($observations (coding-request-observations $structured))
         ($_ (assertEqual (== $observations "") False)))
     (println! STRUCTURED_REQUEST_OK))
