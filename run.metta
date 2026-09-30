!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

!(println! (py-call (gateway_bridge.boot_probe)))
!(mettaclaw)
