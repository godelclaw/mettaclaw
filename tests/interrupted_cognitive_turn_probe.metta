!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

(= (assertEqual $A $B) (assert (== $A $B)))
(= (probe-stimulus)
   (py-call (telegram._set_last "probe" "new stimulus" False "full" 811)))
!(py-eval "__import__('synthetic_llm').__dict__.__setitem__('chat', lambda *args: '((probe-stimulus) (pin _quote_withheld-cognitive-pin-must-not-land_quote_))')")
!(py-eval "__import__('helper').__dict__.__setitem__('_working_boot_cache', {})")
!(initMemory)
!(configure commchannel telegram)

!(let* (($_ (py-call (loop_modes.set_mode "agent")))
         ($initial (initLoop))
         ($after (process-step $initial
                   (turnProcess (process-periphery $initial))))
         ($feedback (loop-last-results (process-periphery $after)))
         ($_ (assertEqual
               (py-call (helper.text_nonempty $feedback)) 1)))
     (println! INTERRUPTED_COGNITIVE_TURN_OK))
