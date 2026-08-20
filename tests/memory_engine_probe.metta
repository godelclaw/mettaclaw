!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)
!(println! (py-call (memory_health.engine_query_probe "memory index health probe")))
