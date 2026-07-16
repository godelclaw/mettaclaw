;; Offline golden for claw/llm.metta's pure response handling (no network,
;; no secrets). Exercises the OpenAI-shape extractor and the faithful
;; empty-action ("()") discipline on malformed payloads.
!(import! &self ../src/llm.metta)

;; Well-formed choices[0].message.content -> the content string.
!(assertEqual
  (claw:llm-extract "{\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":\"((rest))\"}}]}")
  "((rest))")

;; Empty choices array -> empty action.
!(assertEqual
  (claw:llm-extract "{\"choices\":[]}")
  "()")

;; Missing message/content -> empty action.
!(assertEqual
  (claw:llm-extract "{\"choices\":[{\"delta\":{}}]}")
  "()")

;; Error-shaped payload (no choices) -> empty action, never a raw error.
!(assertEqual
  (claw:llm-extract "{\"error\":{\"message\":\"bad request\"}}")
  "()")

;; Non-JSON garbage -> empty action.
!(assertEqual
  (claw:llm-extract "not json at all")
  "()")

;; Empty / whitespace-only content -> empty action (reasoning ate the budget),
;; matching synthetic_llm.chat's content.strip() gate.
!(assertEqual
  (claw:llm-extract "{\"choices\":[{\"message\":{\"content\":\"\"}}]}")
  "()")

!(assertEqual
  (claw:llm-extract "{\"choices\":[{\"message\":{\"content\":\"   \"}}]}")
  "()")

;; LLM introspection mirrors synthetic_llm.py's compact string interface rather
;; than exposing raw HTTP JSON to the agent. The current model is passed in (the
;; agent owns &llm-model); here it is pinned explicitly.
!(assertEqual
  (claw:llm-quota-summary-body "syn:large:text"
    "{\"weeklyTokenLimit\":{\"remainingCredits\":12,\"maxCredits\":34,\"percentRemaining\":56.7},\"rollingFiveHourLimit\":{\"remaining\":1,\"max\":2,\"limited\":true},\"subscription\":{\"requests\":3,\"limit\":4}}")
  (str:join " | "
    ("model=syn:large:text"
     "weekly_credits=12 of 34 (56.7% left)"
     "5h_window=1/2 LIMITED"
     "subscription=3/4")))

!(assertEqual
  (claw:llm-quota-summary-body "m" "not json")
  "quota unavailable: bad response")

!(assertEqual
  (claw:llm-models-summary-body
    "{\"data\":[{\"id\":\"syn:large:text\",\"context_length\":200000},{\"id\":\"other\",\"context_window\":4096}]}")
  "(syn:large:text ctx 200000) (other ctx 4096)")

!(assertEqual
  (claw:llm-models-summary-body "{\"data\":[]}")
  "(no models returned)")

!(assertEqual
  (claw:llm-models-summary-body "not json")
  "models unavailable: bad response")

;; Model-name validation is PURE: it returns a verdict against the live /models
;; body. The agent core turns a valid verdict into the &llm-model state write +
;; user message (see the agent's llm-set-model), so this client stays state-free.
!(assertEqual
  (claw:llm-validate-from-body
    "other"
    "{\"data\":[{\"id\":\"syn:large:text\",\"context_length\":200000},{\"id\":\"other\",\"context_window\":4096}]}")
  (LlmModelValid "other"))

!(assertEqual
  (claw:llm-validate-from-body
    "missing"
    "{\"data\":[{\"id\":\"syn:large:text\",\"context_length\":200000},{\"id\":\"other\",\"context_window\":4096}]}")
  (LlmModelUnknown "missing" ("syn:large:text" "other")))

!(assertEqual
  (claw:llm-validate-from-body "other" "{\"data\":[]}")
  (LlmModelListEmpty))

!(assertEqual
  (claw:llm-validate-from-body "other" "not json")
  (LlmModelListUnavailable BadResponse))

;; Model resolution: a non-empty session override wins, else the configured one.
!(assertEqual (claw:llm-current-model "other") "other")
!(assertEqual (claw:llm-current-model "") (claw:llm-configured-model))
