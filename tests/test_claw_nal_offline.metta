;; PeTTaClaw reasoning-library parity: NAL and NAL7 are loaded with the agent,
;; and the model-facing metta skill evaluates against that same library set.

!(import! &self ../lib_cettaclaw.metta)
!(import! &self str)

(= (claw:test-contains $haystack $needle)
   (if (== (collapse (str:find $haystack $needle)) ()) False True))

!(assertEqual
  (Truth_Negation (stv 0.75 0.8))
  (stv 0.25 0.8))

!(assertEqual
  (Truth_Deduction (stv 1.0 0.9) (stv 0.8 0.7))
  (stv 0.8 0.504))

!(assertEqual
  (collapse (|-nal7 (rain (stv 1.0 0.0)) (wet (stv 0.8 0.0))))
  (((=/> rain wet) (stv 1.0 0.0))
   ((&/ rain wet) (stv 0.8 0.0))))

!(assertEqual
  (case (claw:metta "(Truth_Negation (stv 0.75 0.8))")
    (((MettaOk $output)
      (claw:test-contains $output "(stv 0.25 0.8)"))
     ($other False)))
  True)
