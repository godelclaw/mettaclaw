;; Real channels identify messages by event/update id, not just visible text.
;; Two human messages with the same text but different keys must both re-arm;
;; repeating the same key must not.

!(import! &self ../src/loop.metta)
!(import! &self ./fixtures/llm.metta)

!(claw:init 3
   ((Msg human "u1" "PING")
    (Msg human "u2" "PING")))

!(assertEqual
  (claw:run-n 1 3)
  ((Snap 1 0 armed acted)
   (Snap 2 0 armed acted)
   (Snap 3 0 no idle)))
