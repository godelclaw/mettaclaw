!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

(= (assertEqual $A $B) (assert (== $A $B)))

;; The same weak process runner executes both turns. Policy data alone changes
;; the admission bound: agent executes one command and reports the deferred
;; suffix; coding executes both commands before returning.
!(py-eval "(__import__('helper').__dict__.__setitem__('_batch_probe_prompts', []), __import__('synthetic_llm').__dict__.__setitem__('chat', lambda *args: (__import__('helper')._batch_probe_prompts.append(str(args[-1])) or '((help send) (help query))')), __import__('helper').__dict__.__setitem__('interactive_batch_probe_ok', lambda feedback: int(str(feedback).count('COMMAND_RETURN:') == 1 and 'COMMAND_BATCH_DEFERRED:' in str(feedback))), __import__('helper').__dict__.__setitem__('coding_batch_probe_ok', lambda feedback: int(str(feedback).count('COMMAND_RETURN:') == 2 and 'COMMAND_BATCH_DEFERRED:' not in str(feedback))))")
!(py-eval "__import__('helper').__dict__.__setitem__('batch_probe_prompt_limits_ok', lambda: int(len(__import__('helper')._batch_probe_prompts) == 2 and 'at most 1 command(s)' in __import__('helper')._batch_probe_prompts[0] and 'at most 5 command(s)' in __import__('helper')._batch_probe_prompts[1]))")
!(py-eval "(__import__('helper').__dict__.__setitem__('_working_boot_cache', {}), __import__('helper').__dict__.__setitem__('working_boot', lambda: 3))")
!(initMemory)
!(configure commchannel telegram)

!(let* (($_ (py-call (loop_modes.set_mode "agent")))
         ($initial (initLoop))
         ($after-agent
          (process-step $initial
            (turnProcess (process-periphery $initial))))
         ($agent-feedback
          (loop-last-results (process-periphery $after-agent)))
         ($_ (assertEqual
               (py-call (helper.interactive_batch_probe_ok $agent-feedback))
               1))
         ($_ (py-call (loop_modes.set_mode "coding")))
         ($after-coding
          (process-step $after-agent
            (turnProcess (process-periphery $after-agent))))
         ($coding-feedback
          (loop-last-results (process-periphery $after-coding)))
         ($_ (assertEqual
               (py-call (helper.coding_batch_probe_ok $coding-feedback))
               1))
         ($_ (assertEqual
               (py-call (helper.batch_probe_prompt_limits_ok))
               1))
         ($_ (assertEqual (process-root $after-coding)
                          weak-process-core-v1)))
     (println! INTERACTIVE_BATCH_POLICY_OK))
