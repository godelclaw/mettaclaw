;; End-to-end offline turn test through the refactored loop: scripted inbox +
;; fixture provider, no Python, no network. Exercises the act phase (context ->
;; provider -> balance/parse -> run commands -> history) including a real native
;; shell command via the process interface.

!(import! &self ../src/loop.metta)
!(import! &self ./fixtures/llm.metta)

;; Two human turns: a PING (pin + rest) then a WORK (shell + pin).
!(claw:init 50
   ((Msg human "PING please") (Msg human "let's WORK")))

;; Iteration 1: PING re-arms to 50, fixture replies ((pin "saw ping") (rest));
;; rest drops the budget to 0, so the snapshot shows loops 0, armed, acted.
!(assertEqual (claw:run-n 1 1)
              ((Snap 1 0 armed acted)))

;; The pin landed in working memory (decoded), the shell has not run yet.
!(assertEqual (get-state &pins) ("saw ping"))

;; Iteration 2: WORK re-arms to 50 and runs a real shell command natively.
!(assertEqual (claw:run-n 2 2)
              ((Snap 2 50 armed acted)))

;; History accumulated both turns, newest first, with the real shell output.
!(assertEqual (let $h (get-state &history) (car-atom $h))
              (Entry "let's WORK"
                     (repr (RESULTS: ((COMMAND_RETURN: ("(shell \"printf worked\")" (ShellOk 0 "worked")))
                                      (COMMAND_RETURN: ("(pin \"did work\")" (Pinned "did work"))))))))

;; The WORK turn's pin is now on top of working memory.
!(assertEqual (let $p (get-state &pins) (car-atom $p)) "did work")
