;; Pre-LLM agent-loop test: the budget-arming state machine, driven by a
;; scripted inbox + fixture provider + counted sleep. No network, no real LLM.
;;
;; This is the regression guard for the class of bug the live twins hit
;; (human-message arming). Every snapshot below is hand-verified against
;; pettaclaw's mettaclaw semantics, not merely frozen:
;;
;;   k  message            tick         new? human? arm?  act               loops
;;   1  human "WORK1"      (first,no-)  yes  yes    ARM   WORK,no-rest       3
;;   2  human "WORK1"      3->2         no   yes    -     WORK,no-rest       2
;;   3  bot   "PING1"      2->1         yes  no     -     PING -> rest ->0   0
;;   4  bot   "PING1"      max0(0-1)=0  no   no     -     idle (loops 0)     0
;;   5  human "WORK2"      0            yes  yes    ARM   WORK,no-rest       3   (resume after rest)
;;   6  human "WORK2"      3->2         no   yes    -     WORK,no-rest       2
;;   7  human "WORK3"      2->1         yes  yes    ARM   WORK,no-rest       3   (arm from 1 -> exactly max)
;;   8  human "WORK3"      3->2         no   yes    -     WORK,no-rest       2

!(import! &self ../src/loop.metta)
!(import! &self ./fixtures/llm.metta)

!(claw:init 3
   ((Msg human "WORK1") (Msg human "WORK1")
    (Msg bot   "PING1") (Msg bot   "PING1")
    (Msg human "WORK2") (Msg human "WORK2")
    (Msg human "WORK3") (Msg human "WORK3")))

;; Exact per-iteration trajectory: (Snap k loops-after armed? acted?).
!(assertEqual
  (claw:run-n 1 8)
  ((Snap 1 3 armed acted)
   (Snap 2 2 no    acted)
   (Snap 3 0 no    acted)
   (Snap 4 0 no    idle)
   (Snap 5 3 armed acted)
   (Snap 6 2 no    acted)
   (Snap 7 3 armed acted)
   (Snap 8 2 no    acted)))

;; The loop polled + slept every iteration, including the idle one at loops 0.
!(assertEqual (get-state &sleep-count) 8)

;; A human message did re-arm; the final &loops reflects the last decrement.
!(assertEqual (get-state &loops) 2)

;; The sleep interval was reset (never lowered) across the run.
!(assertEqual (get-state &sleep-ms) 1000)
