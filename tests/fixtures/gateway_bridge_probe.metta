!(import! &self (library lib_import))

!(println! (py-call (gateway_bridge.submit "engine-slow" "delay" "[]" "{\"seconds\":1}" 10)))
!(println! (py-call (gateway_bridge.status "engine-slow")))
!(println! GATEWAY_COGNITION_CONTINUES)
!(println! (py-call (gateway_bridge.submit "engine-crash" "crash")))
!(println! (py-call (gateway_bridge.submit "engine-next" "echo" "[]" "\"still-alive\"" 10)))
!(println! GATEWAY_BRIDGE_OK)
