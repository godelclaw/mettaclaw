;; src/mcp.metta — Cettaclaw's MCP adapter via the Python SDK bridge.
;;
;; This keeps the protocol implementation in the official Python MCP SDK while
;; CeTTaClaw supplies only a bounded process/stdin boundary.

!(import! &self json)
!(import! &self process)
!(import! &self str)
!(import! &self system)
!(import! &self ./config.metta)
!(import! &self ./text.metta)

(= (claw:mcp-python)
   (system:getenv-or-default "METTACLAW_MCP_PYTHON" "python3"))

(= (claw:mcp-bridge-cli)
   (system:getenv-or-default
     "METTACLAW_MCP_BRIDGE_CLI"
     "scripts/mcp_bridge_cli.py"))

;; Empty by default: the bridge CLI then loads its vendored sibling
;; (scripts/mcp_bridge.py). Set METTACLAW_MCP_BRIDGE to override.
(= (claw:mcp-bridge-path)
   (system:getenv-or-default "METTACLAW_MCP_BRIDGE" ""))

(= (claw:mcp-config-path)
   (let $fallback (str:concat (claw:home) "/.mcp.json")
        (system:getenv-or-default "METTACLAW_MCP_CONFIG" $fallback)))

(= (claw:mcp-max-output-chars)
   (system:getenv-or-default "METTACLAW_MCP_MAX_OUTPUT_CHARS" "40000"))

(= (claw:mcp-env-for-config $config-path)
   ((Env "HOME" (claw:home))
    (Env "PATH" (system:getenv-or-default "PATH" "/usr/bin:/bin"))
    (Env "METTACLAW_MCP_CONFIG" $config-path)
    (Env "METTACLAW_MCP_BRIDGE" (claw:mcp-bridge-path))
    (Env "METTACLAW_MCP_MAX_OUTPUT_CHARS" (claw:mcp-max-output-chars))))

(= (claw:mcp-env)
   (claw:mcp-env-for-config (claw:mcp-config-path)))

(= (claw:mcp-run-argv-stdin-config $config-path $argv $stdin)
   (let $result
        (process-run-cmd-cwd-env-stdin-timeout-cap-bytes
          $argv
          (system:cwd)
          (claw:mcp-env-for-config $config-path)
          $stdin
          120000
          262144)
        (if (== (process-result-exit-code $result) 0)
            (str:trim (process-result-stdout $result))
            (json-stringify
              (JsonObject
                ((JsonPair "error"
                   (JsonString (process-result-aggregated-output $result)))))))))

(= (claw:mcp-run-argv-stdin $argv $stdin)
   (claw:mcp-run-argv-stdin-config (claw:mcp-config-path) $argv $stdin))

(= (claw:mcp-servers-from-config $config-path)
   (claw:mcp-run-argv-stdin-config
     $config-path
     ((claw:mcp-python) (claw:mcp-bridge-cli) "servers")
     ""))

(= (claw:mcp-servers)
   (claw:mcp-servers-from-config (claw:mcp-config-path)))

(= (claw:mcp-tools-from-config $config-path $server)
   (claw:mcp-run-argv-stdin-config
     $config-path
     ((claw:mcp-python) (claw:mcp-bridge-cli) "tools" (claw:decode-safe $server))
     ""))

(= (claw:mcp-tools $server)
   (claw:mcp-tools-from-config (claw:mcp-config-path) $server))

(= (claw:mcp-tool-info-from-config $config-path $server $tool)
   (claw:mcp-run-argv-stdin-config
     $config-path
     ((claw:mcp-python) (claw:mcp-bridge-cli) "tool-info"
      (claw:decode-safe $server) (claw:decode-safe $tool))
     ""))

(= (claw:mcp-tool-info $server $tool)
   (claw:mcp-tool-info-from-config (claw:mcp-config-path) $server $tool))

(= (claw:mcp-call-from-config $config-path $server $tool $arguments-json)
   (claw:mcp-run-argv-stdin-config
     $config-path
     ((claw:mcp-python) (claw:mcp-bridge-cli) "call"
      (claw:decode-safe $server) (claw:decode-safe $tool))
     (claw:decode-safe $arguments-json)))

(= (claw:mcp-call $server $tool $arguments-json)
   (claw:mcp-call-from-config (claw:mcp-config-path) $server $tool $arguments-json))
