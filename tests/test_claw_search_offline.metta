!(import! &self fs)
!(import! &self ../src/search.metta)

!(assertEqual
  (claw:search-query-provider "tavily: intuitionistic HOL")
  (SearchQuery tavily "intuitionistic HOL"))

!(assertEqual
  (claw:search-query-provider "ddg: CeTTa runtime")
  (SearchQuery ddg "CeTTa runtime"))

!(assertEqual
  (claw:search-format-json-array
    (JsonArray
      ((JsonObject
         ((JsonPair "title" (JsonString " A  title "))
          (JsonPair "url" (JsonString "https://example.test"))
          (JsonPair "content" (JsonString " hello   world ")))))))
  "((TITLE: A title URL: https://example.test SNIPPET: hello world))")

!(assertEqual
  (claw:search-tavily-format-body
    "{\"answer\":\"Direct answer\",\"results\":[{\"title\":\" One \",\"url\":\"https://one.test\",\"content\":\" Some   text \"}]}")
  "((TITLE: Tavily answer SNIPPET: Direct answer) (TITLE: One URL: https://one.test SNIPPET: Some text))")

!(assertEqual
  (claw:search-format-json-array
    (web:ddg-results-from-html
      (fs:read-text "tests/fixtures/ddg_lite_sample.html")
      5))
  "((TITLE: Example & Result URL: https://example.com/a?x=1 SNIPPET: A snippet 'here') (TITLE: Second Result URL: https://example.org/b SNIPPET: Another snippet))")
