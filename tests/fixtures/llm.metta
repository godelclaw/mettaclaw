;; Deterministic offline LLM provider owned by Cettaclaw's tests.
;; It implements the real provider's four-argument seam without network I/O.

!(import! &self str)

;; str:find yields Empty (no results) on a miss, so probe via collapse.
(= (claw:contains $haystack $needle)
   (if (== (collapse (str:find $haystack $needle)) ()) False True))

(= (claw:llm-configured-model) "syn:large:text")
(= (claw:llm-current-model $session)
   (if (== $session "") (claw:llm-configured-model) $session))

(= (claw:llm-chat $model $max-tokens $effort $context)
   (if (claw:contains $context "PING")
       "((pin \"saw ping\") (rest))"
       (if (claw:contains $context "WORK")
           "((shell \"printf worked\") (pin \"did work\"))"
           "((pin \"idle\") (rest))")))
