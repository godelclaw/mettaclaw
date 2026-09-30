; Omega's utils.metta/src_utils.metta boundary, reduced without imports.
; PeTTa v1.0.4 passes; the qualification CeTTa build returns no answer to test.
(: predicate-bool (-> Expression Bool))
(= (predicate-bool $predicate)
   (case (eval $predicate) ((Empty False) (True True))))
(= (fixture-true) True)
!(test (predicate-bool (fixture-true)) True)
