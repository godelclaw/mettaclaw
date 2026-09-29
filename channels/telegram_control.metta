; Lila's operator-command responder, in MeTTa.
;
; The CeTTa Telegram channel service asks about the operator commands it does
; not answer itself. /engine, /mode, /fuel, /model, /quota, /health,
; /activity, /wake, /start, /stop and /claude_code_authorization read or
; change Lila's settings, never her thinking, so they are answered here, in a
; process of its own beside her loop that makes no model call: an answer
; never waits for her turn. /delete stays with her loop's Telegram client,
; which owns her sends and their receipts.
;
; Run by `run.sh telegram-control`. The service answers the operator itself
; if this process is not there to answer in time.

!(import! &self str)
!(import! &self json)
!(import! &self fs)
!(import! &self cwp)
!(import! &self system)
!(import! &self ./src/helper.py)

(= (tc:env $name $default) (system:getenv-or-default $name $default))
(= (tc:socket) (tc:env "METTACLAW_TELEGRAM_SERVICE_SOCKET" ""))
(= (tc:call $code $name $body)
   (let $path (tc:socket) (cwp:call $path $code $name $body 5000)))

(= (tc:tasks-after $after $limit)
   (if (== $limit 0) ()
     (case (tc:call 1 $after "")
       (((cwp:reply 65 $task $body)
         (let $rest (tc:tasks-after $task (- $limit 1))
           (cons-atom ($task $body) $rest)))
        ($other ())))))

(= (tc:answer-task $task $text)
   (let $cut (if (> (str:char-length $text) 3800) (str:char-slice $text 0 3800) $text)
     (let $body (json-stringify (JsonArray ((JsonString "answer") (JsonString $cut))))
       (case (tc:call 2 $task $body)
         (((cwp:reply 66 $n $b) True)
          ((cwp:reply 68 $n $b) True)
          ((cwp:reply 69 $n $b) True)
          ($other False))))))

(= (tc:text $value) (format-args "{}" ($value)))

; Wakes Lila from a rest: her loop's client reads and removes this file.
(= (tc:wake $reason)
   (let $file (tc:env "METTACLAW_WAKE_REQUEST_PATH" "")
     (if (== $file "") () (fs:write $file $reason))))

(= (tc:with-hint $view $hint) (format-args "{} — {}" ($view $hint)))

(= (tc:answer $name $args)
   (case $name
     (("/start"
       (let $reply (py-call (lifecycle.start))
         (let $woken (if (== (py-call (lifecycle.cognition_enabled)) 1) (tc:wake "operator start") ())
           (tc:text $reply))))
      ("/stop"
       (let $reply (py-call (lifecycle.stop))
         (let $woken (tc:wake "operator stop") (tc:text $reply))))
      ("/wake" (let $woken (tc:wake "/wake") "Waking."))
      ("/claude_code_authorization" (tc:text (py-call (helper.claude_code_toggle))))
      ("/health" (tc:text (py-call (runtime_health.report))))
      ("/activity" (tc:text (py-call (runtime_health.activity_report))))
      ("/engine"
       (let $adopted (py-call (helper.adopt_active_engine))
         (if (== $args "")
           (tc:with-hint (tc:text (py-call (engine_modes.engine_view))) "/engine <name> to switch, /engines to list")
           (let $reply (tc:text (py-call (engine_modes.set_engine $args)))
             (let $selected (tc:text (py-call (engine_modes.selected_engine)))
               (let $active (tc:text (py-call (engine_modes.active_engine)))
                 (if (and (not (str:starts-with $reply "engine-set failed:")) (not (== $selected $active)))
                   (let $recycle (py-call (engine_modes.request_recycle))
                     (let $woken (tc:wake "engine switch") $reply))
                   $reply)))))))
      ("/fuel"
       (if (== $args "")
         (tc:with-hint (tc:text (py-call (fuel_modes.fuel_view))) "/fuel <name> to switch, /fuels to list")
         (tc:text (py-call (fuel_modes.set_fuel $args)))))
      ("/mode"
       (if (== $args "")
         (tc:with-hint (tc:text (py-call (loop_modes.mode_view))) "/mode <name> to switch, /modes to list")
         (let $reply (tc:text (py-call (loop_modes.set_mode $args)))
           (let $woken (tc:wake "mode switch") $reply))))
      ("/quota" (tc:text (py-call (synthetic_llm.quota))))
      ("/model"
       (if (== $args "")
         (let $model (tc:text (py-call (synthetic_llm.current_model)))
           (format-args "active model: {} — /model <name> to switch, /models to list, /quota for budget" ($model)))
         (tc:text (py-call (synthetic_llm.set_model $args)))))
      ($other (format-args "unknown command {}" ($name))))))

; Answer every command task but /delete, once each.
(= (tc:handle $tasks)
   (if (== $tasks ()) 0
     (let $head (car-atom $tasks)
       (let $tail (cdr-atom $tasks)
         (let ($task $body) $head
           (let $done
                (case (json-parse $body)
                  (((JsonArray ((JsonString "command") (JsonString $key) (JsonString $name) (JsonString $args) (JsonString $lane)))
                    (if (== $name "/delete") 0
                      (let $text (tc:answer $name $args)
                        (if (tc:answer-task $task $text) 1 0))))
                   ($other 0)))
             (+ $done (tc:handle $tail))))))))

(= (tc:serve-once) (tc:handle (tc:tasks-after "" 256)))

; Forever: answer what is waiting, then look again shortly.
(= (tc:serve)
   (let $answered (tc:serve-once)
     (let $slept (py-call (time.sleep 0.1))
       (tc:serve))))
