!(import! &self ../lib_cettaclaw.metta)

(= (test:contains? $text $needle)
   (if (== (collapse (str:find $text $needle)) ()) False True))

(= (test:context-fields $context)
   (ContextFields
     (test:contains? $context "PROMPT:")
     (test:contains? $context "SKILLS:")
     (test:contains? $context "OUTPUT_FORMAT:")
     (test:contains? $context "LOOPS_LEFT:")
     (test:contains? $context "SLEEP_INTERVAL_SECONDS:")
     (test:contains? $context "LAST_SKILL_USE_RESULTS:")
     (test:contains? $context "HISTORY:")
     (test:contains? $context "TIME:")
     (test:contains? $context "HUMAN-LAST-MSG:")
     (test:contains? $context "MESSAGE-IS-NEW:")
     (test:contains? $context "HUMAN-MESSAGE-ARMS-LOOP:")))

!(test:context-fields
   (claw:full-context "hello" 7 1 True True "last-result"))
