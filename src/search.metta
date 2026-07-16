;; src/search.metta - pettaclaw-compatible web search over native http/json.
;;
;; Interface:
;;   (search "query")        provider prefixes/env, Tavily then DDG fallback
;;   (search-tavily "query") Tavily API
;;   (search-ddg "query")    DuckDuckGo lite/html scrape

!(import! &self http)
!(import! &self json)
!(import! &self str)
!(import! &self web)
!(import! &self ./config.metta)
!(import! &self ./text.metta)

(= (claw:search-clean $text)
   (str:join " " (str:split-whitespace $text)))

(= (claw:search-config $key)
   (let $secret (claw:secret $key)
        (if (== $secret NotFound)
            (claw:setting $key)
            $secret)))

(= (claw:search-config-default $key $default)
   (let $v (claw:search-config $key)
        (if (or (== $v NotFound) (== $v ""))
            $default
            $v)))

(= (claw:search-provider)
   (claw:search-config-default "METTACLAW_SEARCH_PROVIDER" "auto"))

(= (claw:search-decode-query $query)
   (str:trim (claw:decode-safe $query)))

(= (claw:search-query-provider $query)
   (let $text (claw:search-decode-query $query)
        (if (str:starts-with $text "tavily:")
            (SearchQuery tavily (str:trim (str:slice $text 7 (str:length $text))))
            (if (str:starts-with $text "ddg:")
                (SearchQuery ddg (str:trim (str:slice $text 4 (str:length $text))))
                (if (str:starts-with $text "duckduckgo:")
                    (SearchQuery ddg (str:trim (str:slice $text 11 (str:length $text))))
                    (if (str:starts-with $text "auto:")
                        (SearchQuery auto (str:trim (str:slice $text 5 (str:length $text))))
                        (SearchQuery (claw:search-provider) $text)))))))

(= (claw:search-url-piece $url)
   (if (== $url "") "" (str:concat " URL: " $url)))

(= (claw:search-format-entry $title $url $snippet)
   (str:join ""
     ("(TITLE: " $title (claw:search-url-piece $url)
      " SNIPPET: " $snippet ")")))

(= (claw:search-format-entries $entries)
   (str:concat "(" (str:concat (str:join " " $entries) ")")))

(= (claw:json-string-field $object $key)
   (case (json-object-get $object $key)
     (((JsonString $text) (claw:search-clean $text))
      ($other ""))))

(= (claw:search-snippet-field $object)
   (let $content (claw:json-string-field $object "content")
        (if (== $content "")
            (claw:json-string-field $object "snippet")
            $content)))

(= (claw:search-format-json-result $object)
   (case $object
     (((JsonObject $pairs)
       (claw:search-format-entry
         (claw:json-string-field (JsonObject $pairs) "title")
         (claw:json-string-field (JsonObject $pairs) "url")
         (claw:search-snippet-field (JsonObject $pairs))))
      ($other ""))))

(= (claw:search-format-json-array $array)
   (case $array
     (((JsonArray $items)
       (claw:search-format-entries
         (map-atom $items $item (claw:search-format-json-result $item))))
      ($other ""))))

(= (claw:search-tavily-key)
   (claw:search-config-default "TAVILY_API_KEY" ""))

(= (claw:search-tavily-base-url)
   (claw:search-config-default "TAVILY_BASE_URL" "https://api.tavily.com"))

(= (claw:search-tavily-body $query $max-results)
   (json-stringify
     (JsonObject
       ((JsonPair "query" (JsonString $query))
        (JsonPair "max_results" (JsonNumber $max-results))))))

(= (claw:search-tavily-entries-from-object $object)
   (let $results (json-object-get $object "results")
   (let $entries
        (case $results
          (((JsonArray $items)
            (map-atom $items $item (claw:search-format-json-result $item)))
           ($other ())))
   (let $answer (claw:json-string-field $object "answer")
        (if (== $answer "")
            $entries
            (cons-atom
              (claw:search-format-entry "Tavily answer" "" $answer)
              $entries))))))

(= (claw:search-tavily-format-body $body)
   (case (json-parse $body)
     (((JsonObject $pairs)
       (claw:search-format-entries
         (claw:search-tavily-entries-from-object (JsonObject $pairs))))
      ($bad ""))))

(= (claw:search-tavily-with-max $query $max-results)
   (let $q (claw:search-decode-query $query)
   (let $key (claw:search-tavily-key)
        (if (== $key "")
            "()"
            (let $url (str:concat (claw:search-tavily-base-url) "/search")
            (let $body (claw:search-tavily-body $q $max-results)
            (let $result
                 (http:request "POST" $url
                   ((Header "Authorization" (str:concat "Bearer " $key))
                    (Header "Content-Type" "application/json")
                    (Header "User-Agent" "cettaclaw-websearch/1.0"))
                   $body 30000 1048576)
                 (case $result
                   (((HttpResult 200 $response)
                     (claw:search-tavily-format-body $response))
                    ((HttpResult $status $response) "")
                    ($other ""))))))))))

(= (claw:search-tavily $query)
   (claw:search-tavily-with-max $query 10))

(= (claw:search-ddg-url $base $query)
   (str:concat $base (web:url-encode (claw:search-decode-query $query))))

(= (claw:search-ddg-at $base $query)
   (let $url (claw:search-ddg-url $base $query)
   (let $result
        (http:request "GET" $url
          ((Header "User-Agent" "Mozilla/5.0"))
          "" 10000 1048576)
        (case $result
          (((HttpResult 200 $html)
            (claw:search-format-json-array
              (web:ddg-results-from-html $html 10)))
           ((HttpResult $status $body) "")
           ($other ""))))))

(= (claw:search-ddg $query)
   (let $first (claw:search-ddg-at "https://lite.duckduckgo.com/lite/?q=" $query)
        (if (and (not (== $first "")) (not (== $first "()")))
            $first
            (let $second
                 (claw:search-ddg-at "https://html.duckduckgo.com/html/?q=" $query)
                 (if (== $second "") $first $second)))))

(= (claw:search-auto $query)
   (let $tavily (claw:search-tavily $query)
        (if (and (not (== $tavily "")) (not (== $tavily "()")))
            $tavily
            (claw:search-ddg $query))))

(= (claw:search $query)
   (case (claw:search-query-provider $query)
     (((SearchQuery tavily $q) (claw:search-tavily $q))
      ((SearchQuery api $q) (claw:search-tavily $q))
      ((SearchQuery ddg $q) (claw:search-ddg $q))
      ((SearchQuery duckduckgo $q) (claw:search-ddg $q))
      ((SearchQuery html $q) (claw:search-ddg $q))
      ((SearchQuery auto $q) (claw:search-auto $q))
      ((SearchQuery $other $q) (claw:search-auto $q)))))
