;; src/llm.metta — CeTTaClaw's LLM client over native http+json interfaces,
;; mirroring the original agent's synthetic_llm.py contract:
;;   POST {base}/chat/completions  {model, messages, max_tokens, reasoning}
;;   -> choices[0].message.content ; any failure -> the empty action "()".
;; Errors are sanitized: transport Error atoms echo the request (including
;; the Authorization header), so they are classified and dropped, never
;; returned or printed.

!(import! &self http)
!(import! &self json)
!(import! &self str)
!(import! &self time)
!(import! &self ./config.metta)

;; Endpoint bases. The pettaclaw-generated .env does not set these (they are
;; code defaults in synthetic_llm.py), so mirror that: use the setting when
;; present, else the same defaults the original agent uses.
(= (claw:synthetic-base-url)
   (let $s (claw:setting "SYNTHETIC_BASE_URL")
        (if (== $s NotFound) "https://api.synthetic.new/openai/v1" $s)))

(= (claw:synthetic-api-root)
   (let $s (claw:setting "SYNTHETIC_API_ROOT")
        (if (== $s NotFound) "https://api.synthetic.new" $s)))

(= (claw:llm-configured-model)
   (let $s (claw:setting "SYNTHETIC_MODEL")
        (if (== $s NotFound) "syn:large:text" $s)))

;; Resolve the model for a call, given the agent's session override ($session,
;; "" when unset). The agent owns that state cell (&llm-model), not this client,
;; so it is passed in: a non-empty session model wins, else the configured one.
(= (claw:llm-current-model $session)
   (if (== $session "") (claw:llm-configured-model) $session))

(= (claw:llm-auth-headers)
   ((Header "Authorization" (str:concat "Bearer " (claw:secret "SYNTHETIC_API_KEY")))
    (Header "Content-Type" "application/json")))

;; Run an http request but never let the raw result/error (which echoes the
;; auth header) escape: reduce to (HttpResult s b) or the tag Transport.
(= (claw:llm-http $method $url $body $timeout-ms)
   (case (http:request $method $url (claw:llm-auth-headers) $body $timeout-ms 8388608)
     (((HttpResult $s $b) (HttpResult $s $b))
      ($other TransportError))))

(= (claw:llm-chat-body $model $prompt $max-tokens $effort)
   (json-stringify
     (JsonObject
       ((JsonPair "model" (JsonString $model))
        (JsonPair "messages"
          (JsonArray
            ((JsonObject ((JsonPair "role" (JsonString "user"))
                          (JsonPair "content" (JsonString $prompt)))))))
        (JsonPair "max_tokens" (JsonNumber (repr $max-tokens)))
        (JsonPair "reasoning"
          (JsonObject ((JsonPair "effort" (JsonString $effort)))))))))

;; A whitespace-only (or empty) model reply is the empty action, matching
;; synthetic_llm.chat: `if content.strip(): return content; else "()"`.
(= (claw:llm-content-or-empty $text)
   (if (== (str:trim $text) "") "()" $text))

;; choices[0].message.content, or the empty action on any shape mismatch.
(= (claw:llm-extract $body)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (case (json-object-get (JsonObject $pairs) "choices")
         (((JsonArray ($first))
           (case (json-object-get $first "message")
             (((JsonObject $mp)
               (case (json-object-get (JsonObject $mp) "content")
                 (((JsonString $text) (claw:llm-content-or-empty $text))
                  ($o1 "()"))))
              ($o2 "()"))))
          ($o3 "()"))))
      ($o4 "()"))))

;; The real chat call. Faithful failure discipline: non-200, transport
;; errors, and unexpected payload shapes all yield "()" (the empty action).
;; Exponential backoff on retriable failures (2,4,8,16,32,64s): quick retries
;; absorb transient rate limits; the capped tail idles politely through credit
;; outages instead of spinning the loop against a refusing API.
(= (claw:llm-retriable-status? $s)
   (or (== $s 408) (or (== $s 409) (or (== $s 425) (or (== $s 429)
   (or (== $s 500) (or (== $s 502) (or (== $s 503) (== $s 504)))))))))

(= (claw:llm-backoff-ms $attempt)
   (case $attempt
     ((0 2000) (1 4000) (2 8000) (3 16000) (4 32000) ($o 64000))))

(= (claw:llm-max-retries) 6)

(= (claw:llm-chat-once $model $prompt $max-tokens $effort)
   (let $base (claw:synthetic-base-url)
        (claw:llm-http "POST" (str:concat $base "/chat/completions")
                       (claw:llm-chat-body $model $prompt $max-tokens $effort)
                       120000)))

(= (claw:llm-chat-with-retry $model $prompt $max-tokens $effort $attempt)
   (case (claw:llm-chat-once $model $prompt $max-tokens $effort)
     (((HttpResult 200 $body) (claw:llm-extract $body))
      ((HttpResult $s $body)
       (if (and (claw:llm-retriable-status? $s) (< $attempt (claw:llm-max-retries)))
           (let $_ (time:sleep-ms (claw:llm-backoff-ms $attempt))
                (claw:llm-chat-with-retry $model $prompt $max-tokens $effort (+ $attempt 1)))
           "()"))
      ($other
       (if (< $attempt (claw:llm-max-retries))
           (let $_ (time:sleep-ms (claw:llm-backoff-ms $attempt))
                (claw:llm-chat-with-retry $model $prompt $max-tokens $effort (+ $attempt 1)))
           "()")))))

(= (claw:llm-chat-real $model $prompt $max-tokens $effort)
   (claw:llm-chat-with-retry $model $prompt $max-tokens $effort 0))

;; Loop seam: (claw:llm-chat $model $max-tokens $effort $prompt) -> command-text.
;; The agent core supplies its resolved model + policy (output tokens, effort),
;; keeping this client free of agent state and policy — faithful to the original
;; synthetic_llm.chat(model, max_tokens, effort, prompt). Drop-in swappable with
;; Cettaclaw's offline test fixture implements the identical 4-arg seam.
(= (claw:llm-chat $model $max-tokens $effort $prompt)
   (claw:llm-chat-real $model $prompt $max-tokens $effort))

(= (claw:llm-json-get-or-null $value $key)
   (case $value
     (((JsonObject $pairs) (json-object-get (JsonObject $pairs) $key))
      ($other JsonNull))))

(= (claw:json-scalar-or $value $fallback)
   (case $value
     (((JsonString $text) $text)
      ((JsonNumber $text) $text)
      ((JsonBool True) "True")
      ((JsonBool False) "False")
      (JsonNull $fallback)
      ($other $fallback))))

(= (claw:llm-quota-week $root)
   (let $week (claw:llm-json-get-or-null $root "weeklyTokenLimit")
        (str:join "" ("weekly_credits="
                      (claw:json-scalar-or
                        (claw:llm-json-get-or-null $week "remainingCredits") "?")
                      " of "
                      (claw:json-scalar-or
                        (claw:llm-json-get-or-null $week "maxCredits") "?")
                      " ("
                      (claw:json-scalar-or
                        (claw:llm-json-get-or-null $week "percentRemaining") "?")
                      "% left)"))))

(= (claw:llm-quota-five $root)
   (let $five (claw:llm-json-get-or-null $root "rollingFiveHourLimit")
        (str:join "" ("5h_window="
                      (claw:json-scalar-or
                        (claw:llm-json-get-or-null $five "remaining") "?")
                      "/"
                      (claw:json-scalar-or
                        (claw:llm-json-get-or-null $five "max") "?")
                      (case (claw:llm-json-get-or-null $five "limited")
                        (((JsonBool True) " LIMITED")
                         ($other "")))))))

(= (claw:llm-quota-subscription $root)
   (let $sub (claw:llm-json-get-or-null $root "subscription")
        (str:join "" ("subscription="
                      (claw:json-scalar-or
                        (claw:llm-json-get-or-null $sub "requests") "?")
                      "/"
                      (claw:json-scalar-or
                        (claw:llm-json-get-or-null $sub "limit") "?")))))

(= (claw:llm-quota-summary-body $model $body)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (let $root (JsonObject $pairs)
            (str:join " | "
              ((str:join "" ("model=" $model))
               (claw:llm-quota-week $root)
               (claw:llm-quota-five $root)
               (claw:llm-quota-subscription $root)))))
      ($other "quota unavailable: bad response"))))

(= (claw:llm-model-item $item)
   (case $item
     (((JsonObject $pairs)
       (let $obj (JsonObject $pairs)
       (let $id (claw:json-scalar-or (claw:llm-json-get-or-null $obj "id") "?")
       (let $ctx (case (claw:llm-json-get-or-null $obj "context_length")
                   ((JsonNull
                     (claw:json-scalar-or
                       (claw:llm-json-get-or-null $obj "context_window") "?"))
                    ($other (claw:json-scalar-or $other "?"))))
            (str:join "" ("(" $id " ctx " $ctx ")"))))))
      ($other ""))))

(= (claw:llm-model-items $items)
   (if (== $items ())
       ()
       (let ($head $tail) (decons-atom $items)
       (let $text (claw:llm-model-item $head)
       (let $rest (claw:llm-model-items $tail)
            (if (== $text "")
                $rest
                (cons-atom $text $rest)))))))

(= (claw:llm-model-id $item)
   (case $item
     (((JsonObject $pairs)
       (claw:json-scalar-or
         (claw:llm-json-get-or-null (JsonObject $pairs) "id")
         ""))
      ($other ""))))

(= (claw:llm-model-ids $items)
   (if (== $items ())
       ()
       (let ($head $tail) (decons-atom $items)
       (let $id (claw:llm-model-id $head)
       (let $rest (claw:llm-model-ids $tail)
            (if (== $id "")
                $rest
                (cons-atom $id $rest)))))))

(= (claw:llm-model-id-member? $ids $name)
   (if (== $ids ())
       False
       (let ($head $tail) (decons-atom $ids)
            (if (== $head $name)
                True
                (claw:llm-model-id-member? $tail $name)))))

(= (claw:llm-models-summary-body $body)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (case (json-object-get (JsonObject $pairs) "data")
         (((JsonArray $items)
           (let $summaries (claw:llm-model-items $items)
                (if (== $summaries ())
                    "(no models returned)"
                    (str:join " " $summaries))))
          ($other "(no models returned)"))))
      ($other "models unavailable: bad response"))))

;; Pure model validation against the live /models list. Returns a verdict; the
;; agent core turns it into the &llm-model state write + user-facing message, so
;; this client never touches agent state.
(= (claw:llm-validate-from-ids $model $ids)
   (case $ids
     ((() (LlmModelListEmpty))
      ($nonempty
       (if (claw:llm-model-id-member? $nonempty $model)
           (LlmModelValid $model)
           (LlmModelUnknown $model $nonempty))))))

(= (claw:llm-validate-from-body $name $body)
   (let $model (str:trim $name)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (case (json-object-get (JsonObject $pairs) "data")
         (((JsonArray $items)
           (claw:llm-validate-from-ids $model (claw:llm-model-ids $items)))
          ($other (LlmModelListEmpty)))))
      ($other (LlmModelListUnavailable BadResponse))))))

(= (claw:llm-models-raw)
   (claw:llm-http "GET" (str:concat (claw:synthetic-base-url) "/models")
                  "" 30000))

(= (claw:llm-quota-raw)
   (claw:llm-http "GET" (str:concat (claw:synthetic-api-root) "/v2/quotas")
                  "" 30000))

(= (claw:llm-models)
   (case (claw:llm-models-raw)
     (((HttpResult 200 $body) (claw:llm-models-summary-body $body))
      ((HttpResult $status $body)
       (str:join "" ("models unavailable: HTTP " (repr $status))))
      ($other "models unavailable: TransportError"))))

(= (claw:llm-quota $model)
   (case (claw:llm-quota-raw)
     (((HttpResult 200 $body) (claw:llm-quota-summary-body $model $body))
      ((HttpResult $status $body)
       (str:join "" ("quota unavailable: HTTP " (repr $status))))
      ($other "quota unavailable: TransportError"))))

;; Validate a requested model name against the live list (pure — no state
;; write). The agent core writes &llm-model + renders the message on a valid
;; verdict (see the agent's llm-set-model).
(= (claw:llm-validate-model $name)
   (case (claw:llm-models-raw)
     (((HttpResult 200 $body) (claw:llm-validate-from-body $name $body))
      ((HttpResult $status $body) (LlmModelListUnavailable (HttpStatus $status)))
      ($other (LlmModelListUnavailable TransportError)))))
