;; src/context.metta — prompt, history, and model-facing turn context.
;;
;; This module owns only context construction. The live prompt and history are
;; read from configured files at turn time, while the short claw:context in
;; loop.metta remains a file-free seam for offline loop tests.

!(import! &self fs)
!(import! &self str)
!(import! &self time)
!(import! &self ./config.metta)
!(import! &self ./value.metta)
!(import! &self ./text.metta)
!(import! &self ./skills.metta)

(= (claw:max-feedback) 50000)
(= (claw:max-history) 30000)

(= (claw:read-text-or-empty $path)
   (case (fs:read-text $path)
     (((FsError $msg) "")
      ($text $text))))

(= (claw:context-tail $text $limit)
   (claw:decode-repr-quotes (claw:last-chars $text $limit)))

(= (claw:prompt-text)
   (let $p (claw:setting "METTACLAW_PROMPT_PATH")
        (if (== $p NotFound) "" (claw:read-text-or-empty $p))))

(= (claw:history-tail)
   (let $p (claw:setting "METTACLAW_HISTORY_PATH")
        (if (== $p NotFound) ""
            (claw:context-tail
              (claw:read-text-or-empty $p)
              (claw:max-history)))))

(= (claw:feedback-tail $last)
   (claw:context-tail $last (claw:max-feedback)))

;; Keep the wire instruction next to the context that exposes it. Dispatch and
;; its model-facing catalog remain together in skills.metta.
(= (claw:output-format)
   "OUTPUT_FORMAT: Output a ((skillName1 args1) (skillName2 args2) (skillName3 args3) (skillName4 args4) (skillName5 args5)) S-expression of up to 5 sexpr commands, double-check the parentheses it must be (cmd1 ... cmdn)! Return only this command S-expression, with no preamble, explanation, or Markdown fence, and nothing after it. Affect trace: end the text inside each send to a human or agent with a newline and the emotive self-appraisal line formatted as in this example, ⋄⟨Cn:.5 C:.7 Ct:.8 I:.2 J:.6 A:.4 S:.6 Co:-.42⟩, values ∈ [-1,1]. Dimensions: Cn connection, C curiosity, Ct contribution, I integrity, J joy, A agency, S safety, Co confidence. Each arg is an explicit string hence needs quotes, and variables are forbidden!")

(= (claw:full-context $msgtext $loops $interval $isnew $ishuman $last)
   (str:join " "
     ("PROMPT:" (claw:prompt-text)
      "SKILLS:" (claw:skills-catalog)
      (claw:output-format)
      "LOOPS_LEFT:" (repr $loops)
      "SLEEP_INTERVAL_SECONDS:" (repr $interval)
      "LAST_SKILL_USE_RESULTS:" (claw:feedback-tail $last)
      "HISTORY:" (claw:history-tail)
      "TIME:" (time:time-string)
      "HUMAN-LAST-MSG:" $msgtext
      "MESSAGE-IS-NEW:" (repr $isnew)
      "HUMAN-MESSAGE-ARMS-LOOP:" (repr $ishuman))))

;; The loop keeps a bounded in-process view for tests and child state. Durable
;; history is appended only by runtime/commit.metta.
(= (claw:add-to-history $mtext $rtext)
   (let $old (get-state &history)
        (change-state! &history (cons-atom (Entry $mtext $rtext) $old))))
