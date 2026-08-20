!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

!(let $bundle (py-call (context_sources.bundle))
   (if (== (py-call (helper.text_nonempty $bundle)) 1)
       (println! CONTEXT_SOURCES_OK)
       (println! CONTEXT_SOURCES_EMPTY)))
