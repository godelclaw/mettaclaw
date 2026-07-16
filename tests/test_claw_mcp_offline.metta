!(import! &self json)
!(import! &self ../src/mcp.metta)

(= (mcp-test:first-array-item (JsonArray $items))
   (car-atom $items))

(= (mcp-test:config)
   "tests/fixtures/mcp_fake_config.json")

!(assertEqual
  (json-object-get
    (json-parse (claw:mcp-servers-from-config (mcp-test:config)))
    "servers")
  (JsonArray
    ((JsonObject
       ((JsonPair "name" (JsonString "fake"))
        (JsonPair "type" (JsonString "stdio")))))))

!(assertEqual
  (json-object-get
    (json-parse (claw:mcp-tools-from-config (mcp-test:config) "fake"))
    "tools")
  (JsonArray
    ((JsonObject
       ((JsonPair "description" (JsonString "Echo text"))
        (JsonPair "name" (JsonString "echo")))))))

!(assertEqual
  (json-object-get
    (json-parse (claw:mcp-tool-info-from-config (mcp-test:config) "fake" "echo"))
    "name")
  (JsonString "echo"))

!(assertEqual
  (json-object-get
    (json-parse (claw:mcp-call-from-config
                  (mcp-test:config)
                  "fake"
                  "echo"
                  "{\"text\":\"hi\"}"))
    "isError")
  (JsonBool False))

!(assertEqual
  (json-object-get
    (mcp-test:first-array-item
      (json-object-get
        (json-parse (claw:mcp-call-from-config
                      (mcp-test:config)
                      "fake"
                      "echo"
                      "{\"text\":\"hi\"}"))
        "content"))
    "text")
  (JsonString "echo:hi"))
