!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

(= (assertEqual $A $B) (assert (== $A $B)))

;; Two real turns through the shared PeTTa loop.  The first executes a real
;; deterministic help command.  The second request must contain both that
;; result and the Iter fixture's appended message before its model call.
!(py-eval "(__import__('helper').__dict__.__setitem__('_coding_probe_prompts', []), __import__('synthetic_llm').__dict__.__setitem__('chat', lambda *args: (__import__('helper')._coding_probe_prompts.append(str(args[-1])) or ('((help send))' if len(__import__('helper')._coding_probe_prompts)==1 else '((nop))'))), __import__('helper').__dict__.__setitem__('coding_probe_ok', lambda: int(len(__import__('helper')._coding_probe_prompts)>=2 and 'MESSAGE: 2' in __import__('helper')._coding_probe_prompts[0] and 'LAST_SKILL_USE_RESULTS:' in __import__('helper')._coding_probe_prompts[1] and 'usage: (send' in __import__('helper')._coding_probe_prompts[1])))")
!(py-eval "(__import__('helper').__dict__.__setitem__('_working_boot_cache', {}), __import__('helper').__dict__.__setitem__('working_boot', lambda: 1))")
!(initMemory)
!(configure commchannel telegram)

!(let* (($_ (py-call (loop_modes.set_mode "iter-coding")))
         ($initial (initLoop))
         ($after-first
          (process-step $initial
            (turnProcess (process-periphery $initial))))
         ($after-second
          (process-step $after-first
            (turnProcess (process-periphery $after-first))))
         ($_ (assertEqual (process-root $after-second) weak-process-core-v1))
         ($_ (assertEqual (py-call (helper.coding_probe_ok)) 1)))
     (println! INTEGRATED_CODING_TURN_OK))
