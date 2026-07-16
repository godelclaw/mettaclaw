;; src/loop.metta — the CeTTaClaw agent loop, pure CeTTa.
;;
;; Mirrors pettaclaw-godel/src/loop.metta's (mettaclaw $k) recursion as closely
;; as CeTTa allows: initLoop -> claw:init (state cells), getContext ->
;; claw:full-context, and the per-iteration act. claw:iterate is one pass;
;; claw:mettaclaw recurses forever (real runs) and claw:run-n runs a bounded
;; number of passes (offline goldens) over the exact same body.
;;
;; The three effectful edges are seams so the loop is testable with no LLM and no
;; channel: receive -> &inbox-schedule (channels), the LLM call -> claw:llm-chat
;; (src/llm, or the test-owned offline fixture), sleep -> claw:sleep (utils).
;;
;; Faithful invariants preserved from mettaclaw:
;;   * the first iteration does NOT decrement the budget; every later iteration
;;     decrements &loops to (max 0 (- loops 1));
;;   * a *new* *human* message re-arms &loops to &max-loops and resets the sleep;
;;   * the model is called / commands run only while loops > 0, but the loop keeps
;;     polling and sleeping at loops == 0 so a new human can re-arm;
;;   * a malformed command is contained, never fatal.

!(import! &self str)
!(import! &self time)
!(import! &self ./value.metta)
!(import! &self ./wire.metta)
!(import! &self ./utils.metta)
!(import! &self ./channels.metta)
!(import! &self ./skills.metta)
!(import! &self ./context.metta)

;; ---- loop / LLM policy (pettaclaw initLoop) -------------------------------
(= (claw:max-loops) 50)
(= (claw:default-sleep-ms) 1000)
(= (claw:max-output-tokens) 6000)
(= (claw:reasoning-effort) "medium")

;; Quiet-time wake policy. The shared default is zero (message-driven only);
;; an agent may opt in through its private settings profile. Store milliseconds
;; to match the native clock without conversion at every loop boundary.
(= (claw:heartbeat-interval-ms-from-setting)
   (let $raw (claw:setting "METTACLAW_HEARTBEAT_INTERVAL_SECONDS")
        (if (== $raw NotFound)
            0
            (let $seconds (claw:parse-nat (str:trim $raw))
                 (if (< $seconds 0) 0 (* $seconds 1000))))))

;; ---- setup: create + initialize every cell (call once before looping) -----
;; CeTTa cells are bind!-once, so this is the initLoop/initMemory/initChannels
;; hoist. $max is the re-arm budget (claw:max-loops in live runs); $schedule is
;; the scripted inbox (the live driver rewrites it from a real getUpdates batch).
;; new-state stores its argument unreduced, so force the policy value to a
;; literal first (pettaclaw's (configure sleepInterval 1) stored a value, not a
;; thunk); every other cell below is already a literal / param.
(= (claw:init $max $schedule)
   (let $sleep (claw:default-sleep-ms)
   (let $heartbeat-ms (claw:heartbeat-interval-ms-from-setting)
   (let $now (time:unix-time-ms)
   (let $a (bind! &loops (new-state $max))
   (let $b (bind! &max-loops (new-state $max))
   (let $c (bind! &sleep-ms (new-state $sleep))
   (let $d (bind! &default-sleep-ms (new-state $sleep))
   (let $e (bind! &prevmsg (new-state ""))
   (let $f (bind! &pins (new-state ()))
   (let $g (bind! &history (new-state ()))
   (let $h (bind! &last (new-state ""))
   (let $i (bind! &inbox-schedule (new-state $schedule))
   (let $j (bind! &sleep-count (new-state 0))
   (let $k (bind! &reply-chat (new-state ""))
   (let $l (bind! &pending-offset (new-state ""))
   (let $m (bind! &tg-queue (new-state (TgQueue ())))
   (let $n (bind! &llm-model (new-state ""))
   (let $o (bind! &heartbeat-interval-ms (new-state $heartbeat-ms))
   (let $p (bind! &last-heartbeat-ms (new-state $now))
        ClawReady))))))))))))))))))))

;; ---- budget transitions ---------------------------------------------------
(= (claw:tick $k)
   (if (== $k 1) ClawFirst (claw:decrement)))
(= (claw:decrement)
   (change-state! &loops (claw:max 0 (- (get-state &loops) 1))))
(= (claw:arm)
   (let $a (change-state! &loops (get-state &max-loops))
   (let $b (change-state! &sleep-ms (get-state &default-sleep-ms))
   (let $c (change-state! &last-heartbeat-ms (time:unix-time-ms))
        ClawArmed))))

;; ---- per-human arm grants ---------------------------------------------------
;; METTACLAW_ARM_GRANTS = "from_id:count,from_id:count". A message from a listed
;; human arms max(current, count) instead of the full budget: chatty senders get
;; a short attention tail rather than the whole 50-loop grant, and re-arming can
;; never REDUCE loops mid-burst. Unlisted humans (and offline fixtures, whose
;; sender carries no id) arm the full budget as before.
(= (claw:digit-val $c)
   (case $c (("0" 0) ("1" 1) ("2" 2) ("3" 3) ("4" 4)
             ("5" 5) ("6" 6) ("7" 7) ("8" 8) ("9" 9) ($o -1))))
(= (claw:parse-nat-acc $s $i $n $acc)
   (if (== $i $n)
       $acc
       (let $d (claw:digit-val (str:slice $s $i (+ $i 1)))
            (if (< $d 0) -1 (claw:parse-nat-acc $s (+ $i 1) $n (+ (* 10 $acc) $d))))))
(= (claw:parse-nat $s)
   (if (== (str:length $s) 0) -1 (claw:parse-nat-acc $s 0 (str:length $s) 0)))

(= (claw:arm-grant-lookup $pairs $from-id)
   (if (== $pairs ())
       -1
       (let ($head $tail) (decons-atom $pairs)
            (case (str:split ":" (str:trim $head))
              ((($id $count)
                (if (== (str:trim $id) $from-id)
                    (claw:parse-nat (str:trim $count))
                    (claw:arm-grant-lookup $tail $from-id)))
               ($other (claw:arm-grant-lookup $tail $from-id)))))))

(= (claw:arm-grant-for $from-id)
   (if (== $from-id "")
       (get-state &max-loops)
       (let $raw (claw:setting "METTACLAW_ARM_GRANTS")
            (if (== $raw NotFound)
                (get-state &max-loops)
                (let $g (claw:arm-grant-lookup (str:split "," $raw) $from-id)
                     (if (< $g 0) (get-state &max-loops) $g))))))

(= (claw:arm-msg $msg)
   (let $grant (claw:arm-grant-for (claw:msg-from-id $msg))
   (let $a (change-state! &loops (claw:max (get-state &loops) $grant))
   (let $b (change-state! &sleep-ms (get-state &default-sleep-ms))
   (let $c (change-state! &last-heartbeat-ms (time:unix-time-ms))
        ClawArmed)))))

;; Deterministic seam for crash-free offline tests; the live loop supplies now.
;; A heartbeat is a SET to the normal maximum, never an accumulating grant.
(= (claw:maybe-heartbeat-at $now)
   (let $interval (get-state &heartbeat-interval-ms)
        (if (<= $interval 0)
            ClawNoop
            (if (>= (- $now (get-state &last-heartbeat-ms)) $interval)
                (let $a (change-state! &loops (get-state &max-loops))
                (let $b (change-state! &sleep-ms (get-state &default-sleep-ms))
                (let $c (change-state! &last-heartbeat-ms $now)
                     ClawHeartbeatArmed)))
                ClawNoop))))

(= (claw:maybe-heartbeat)
   (claw:maybe-heartbeat-at (time:unix-time-ms)))

;; new? updates &prevmsg and reports whether this key differs from the last.
(= (claw:note-prevmsg $mkey)
   (let $prev (get-state &prevmsg)
   (let $isnew (not (== $mkey $prev))
   (let $_ (change-state! &prevmsg $mkey)
        $isnew))))

;; Minimal hermetic context for offline goldens. The live prompt/history
;; contract lives in context.metta and is called only by the live driver.
(= (claw:context $msg)
   (str:join " "
     ("LOOPS_LEFT:" (repr (get-state &loops))
      "PINS:" (repr (get-state &pins))
      "LAST:" (get-state &last)
      "MESSAGE:" (claw:msg-text $msg))))

;; ---- command execution ----------------------------------------------------
;; Walk the parsed command expression structurally with decons-atom, capped so a
;; runaway list cannot spin. The list is quoted internally so command heads are
;; not evaluated while we dispatch (see skills.metta claw:run-quoted).
(= (claw:max-commands-per-turn) 16)

(= (claw:run-all-quoted-limit (quote ()) $remaining) ())
(= (claw:run-all-quoted-limit (quote $cmds) $remaining)
   (if (<= $remaining 0)
       ((CommandLimitExceeded (claw:max-commands-per-turn)))
       (let ($head $tail) (decons-atom $cmds)
       (let $r (once (claw:run-quoted (quote $head)))
       (let $wrapped (once (claw:command-return (quote $head) $r))
       (let $rest (once (claw:run-all-quoted-limit (quote $tail) (- $remaining 1)))
            (cons-atom $wrapped $rest)))))))

;; pettaclaw feedback parity: each command is paired with its result as
;; (COMMAND_RETURN: (cmd result)); an Error result carries pettaclaw's
;; self-explanatory retry idiom so the model's learned repair reflexes fire.
(= (claw:cr-tag-error $r)
   (let $inner (cons-atom $r ())
        (cons-atom SINGLE_COMMAND_FORMAT_ERROR_NOTHING_WAS_DONE_PLEASE_FIX_AND_RETRY $inner)))

;; Build (COMMAND_RETURN: (cmd result)) with cons-atom so the command stays
;; DATA: a template position would evaluate an evaluable head like (+ 1 "x").
;; cons-atom here does NOT reduce its arguments, so each intermediate is
;; let-bound to force it (nesting in arg position stays literal otherwise).
(= (claw:command-return (quote $cmd) $r)
   (let $c (repr $cmd)
   (let $r2 (case $r (((Error $a $b) (claw:cr-tag-error $r)) ($other $other)))
   (let $r2l (cons-atom $r2 ())
   (let $pair (cons-atom $c $r2l)
   (let $pl (cons-atom $pair ())
        (cons-atom COMMAND_RETURN: $pl)))))))

(= (claw:run-all-quoted (quote $cmds))
   (RESULTS: (claw:run-all-quoted-limit (quote $cmds) (claw:max-commands-per-turn))))

(= (claw:run-all-parsed $cmds)
   (claw:run-all-quoted (quote $cmds)))

;; ---- the act phase (only reached while loops > 0) -------------------------
;; context -> provider -> balance/parse -> run commands -> record history +
;; lastresults. The provider is called with the agent's resolved model + policy
;; (matching pettaclaw's (synthetic_llm.chat (LLM) (maxOutputToken) (reasoningMode)
;; $send)); offline the fixture ignores them and keys on the context.
;; pettaclaw parity: a response that is not a command S-expression is not
;; parsed or executed; the model gets the original self-correcting feedback.
(= (claw:prose-response? $raw)
   (not (str:starts-with (str:trim (claw:strip-trailing-affect $raw)) "(")))

(= (claw:act $msg $msgnew)
   (let $ctx (claw:context $msg)
   (let $raw (claw:llm-chat (claw:session-model)
                            (claw:max-output-tokens)
                            (claw:reasoning-effort)
                            $ctx)
   (let $results
        (if (claw:prose-response? $raw)
            ((REMEMBER:OUTPUT_NOTHING_ELSE_THAN: ((skill arg) (skill arg))))
            (claw:run-all-parsed (once (parse (claw:balance-parens $raw)))))
   (let $rtext (repr $results)
   (let $mtext (claw:msg-text $msg)
   ;; pettaclaw parity: skip history when the message is stale AND the model
   ;; produced no commands — idle/outage turns must not bloat the record.
   (let $h (if (or $msgnew (not (== $results (RESULTS: ()))))
               (claw:add-to-history $mtext $rtext)
               HistorySkipped)
   (let $l (change-state! &last $rtext)
        (Acted Ran $results)))))))))

;; ---- one iteration (mirrors one pass of mettaclaw) ------------------------
;; Reports a snapshot (Snap $k $loops-after $armed $acted) for observability.
(= (claw:armed? $x)
   (case $x ((ClawArmed armed) (ClawHeartbeatArmed heartbeat) ($o no))))
(= (claw:acted? $x) (case $x ((ClawIdle idle) ($o acted))))
(= (claw:iterate $k)
   (let $t (claw:tick $k)
   (let $msg (claw:receive $k)
   (let $msgnew (claw:note-prevmsg (claw:msg-key $msg))
   (let $humanmsg (claw:is-human $msg)
   (let $armed (if (and $msgnew $humanmsg) (claw:arm-msg $msg) ClawNoop)
   (let $heartbeat (claw:maybe-heartbeat)
   (let $acted (if (> (get-state &loops) 0) (claw:act $msg $msgnew) ClawIdle)
   (let $s (claw:sleep (get-state &sleep-ms))
        (Snap $k (get-state &loops)
              (if (== (claw:armed? $armed) armed)
                  armed
                  (claw:armed? $heartbeat))
              (claw:acted? $acted)))))))))))

;; ---- drivers (shared body) ------------------------------------------------
;; Real run: recurse forever.
(= (claw:mettaclaw $k)
   (let $_ (claw:iterate $k) (claw:mettaclaw (+ $k 1))))
;; Bounded run: collect the snapshot of each iteration $k..$max.
(= (claw:run-n $k $max)
   (if (> $k $max)
       ()
       (let $snap (claw:iterate $k)
       (let $rest (claw:run-n (+ $k 1) $max)
            (cons-atom $snap $rest)))))
