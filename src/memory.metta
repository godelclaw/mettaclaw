;; src/memory.metta — long-term memory service adapter.
;;
;; CeTTaClaw stays BUILD=core: remember/query use native HTTP+JSON against the
;; local memory service. The service owns embeddings, Chroma, and its canonical
;; append-only records; this module owns only the agent-facing client contract.

!(import! &self http)
!(import! &self json)
!(import! &self str)
!(import! &self ./config.metta)
!(import! &self ./value.metta)
!(import! &self ./text.metta)

(= (claw:max-recall-items) 20)

(= (claw:memory-base-url)
   (let $p (claw:setting "METTACLAW_MEMORY_ENDPOINT")
        (if (== $p NotFound) "http://127.0.0.1:8877" $p)))

(= (claw:memory-collection)
   (let $p (claw:setting "METTACLAW_CHROMA_COLLECTION")
        (if (== $p NotFound) "memories" $p)))

(= (claw:json-get-or-null $value $key)
   (case $value
     (((JsonObject $pairs) (json-object-get (JsonObject $pairs) $key))
      ($other JsonNull))))

(= (claw:json-string-or $value $fallback)
   (case $value
     (((JsonString $text) $text)
      ((JsonNumber $text) $text)
      ((JsonBool True) "true")
      ((JsonBool False) "false")
      (JsonNull $fallback)
      ($other $fallback))))

(= (claw:memory-body $text $k)
   (json-stringify
     (JsonObject
       ((JsonPair "text" (JsonString $text))
        (JsonPair "k" (JsonNumber (repr $k)))
        (JsonPair "collection" (JsonString (claw:memory-collection)))))))

(= (claw:memory-remember-body $text)
   (json-stringify
     (JsonObject
       ((JsonPair "text" (JsonString $text))
        (JsonPair "collection" (JsonString (claw:memory-collection)))))))

(= (claw:memory-post $path $body)
   (http:request
     "POST"
     (str:concat (claw:memory-base-url) $path)
     ((Header "Content-Type" "application/json"))
     $body
     180000
     16777216))

(= (claw:memory-hit-from-object $object)
   (let $id (claw:json-string-or (claw:json-get-or-null $object "id") "")
   (let $time (claw:json-string-or (claw:json-get-or-null $object "time") "")
   (let $content (claw:json-string-or (claw:json-get-or-null $object "content") "")
   (let $score (claw:json-string-or (claw:json-get-or-null $object "score") "")
        ($time $content))))))

(= (claw:memory-hit-from-json $value)
   (case $value
     (((JsonObject $pairs)
       (claw:memory-hit-from-object (JsonObject $pairs)))
      ($other MemoryHitMalformed))))

(= (claw:memory-hits-from-value $value)
   (case $value
     (((JsonArray $items)
       (map-atom $items $item (claw:memory-hit-from-json $item)))
      ($other ()))))

(= (claw:memory-query-extract $body)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (claw:memory-hits-from-value
         (json-object-get (JsonObject $pairs) "hits")))
      ($bad (MemoryQueryBadJson)))))

(= (claw:memory-remember-extract $body)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (let $status (claw:json-string-or
                      (json-object-get (JsonObject $pairs) "status") "")
       (let $id (claw:json-string-or
                  (json-object-get (JsonObject $pairs) "id") "")
            (if (== $status "remembered")
                (Remembered $id)
                (RememberFailed $body)))))
      ($bad (RememberFailed BadJson)))))

(= (claw:memory-query-text $query $k)
   (let $decoded (claw:decode-safe $query)
   (let $body (claw:memory-body $decoded $k)
   (case (claw:memory-post "/query" $body)
     (((HttpResult 200 $response) (claw:memory-query-extract $response))
      ((HttpResult $status $response)
       (MemoryQueryUnavailable (HttpStatus $status) $response))
      ($other (MemoryQueryUnavailable TransportError)))))))

(= (claw:remember $content)
   (let $decoded (claw:decode-safe $content)
   (let $body (claw:memory-remember-body $decoded)
   (case (claw:memory-post "/remember" $body)
     (((HttpResult 200 $response) (claw:memory-remember-extract $response))
      ((HttpResult $status $response)
       (RememberFailed (HttpStatus $status) $response))
      ($other (RememberFailed TransportError)))))))

(= (claw:query $k $query)
   (claw:memory-query-text $query $k))
