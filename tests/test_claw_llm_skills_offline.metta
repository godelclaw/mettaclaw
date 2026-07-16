;; Offline command-dispatch coverage for the LLM utility skills. The live driver
;; imports src/llm (the network client) alongside the core; here we stub that
;; adapter seam (pure model validation + resolution) so the core's own wrappers —
;; the model-parameterized llm-quota / llm-models dispatch and the llm-set-model
;; state write + message — are exercised with no network or secrets.

!(import! &self ../src/skills.metta)
!(import! &self str)

;; &llm-model is normally created by the loop; create it for this standalone test.
!(bind! &llm-model (new-state ""))

;; Stub the LLM seam the core calls (skills does not import src/llm,
;; so these are the sole definitions — no conflict).
(= (claw:llm-current-model $session) "stub-model")
(= (claw:llm-validate-model $name) (LlmModelValid $name))
(= (claw:llm-quota $model) (str:join "" ("quota model=" $model)))
(= (claw:llm-models) "(model fixture)")

;; (llm-quota) dispatch resolves + passes the current session model.
!(assertEqual
  (claw:run (llm-quota))
  "quota model=stub-model")

!(assertEqual
  (claw:run (llm-models))
  "(model fixture)")

;; (llm-set-model ...) is the CORE wrapper: validate (stubbed valid) -> write
;; &llm-model -> the session message.
!(assertEqual
  (claw:run (llm-set-model "fixture-model"))
  "model set to 'fixture-model' for this session (reverts to default on restart)")

!(assertEqual (get-state &llm-model) "fixture-model")
