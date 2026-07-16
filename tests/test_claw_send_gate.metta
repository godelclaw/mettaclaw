;; Telegram send skills are externally gated. In the default test/process
;; environment they must preview the exact outbound text, not call sendMessage.

!(import! &self ../src/loop.metta)

!(claw:init 3 ())
!(change-state! &reply-chat "1001001")

!(assertEqual
  (claw:run (send "hello"))
  (SendPreview "1001001" "hello"))

!(assertEqual
  (claw:run (send-telegram-chat "42" "direct"))
  (SendPreview "42" "direct"))

!(change-state! &reply-chat "")

!(assertEqual
  (claw:run (send "lost"))
  (SendNoChat "lost"))

(= (claw:test-remove-if-exists $path)
   (case (fs:exists $path)
     ((True (fs:remove $path))
      ($other ()))))

(= (claw:test-write-failed? $x)
   (case $x
     (((WriteFailed $path (FsError $msg)) True)
      ($other False))))

(= (claw:test-append-failed? $x)
   (case $x
     (((AppendFailed $path (FsError $msg)) True)
      ($other False))))

!(claw:test-remove-if-exists "runtime/test_claw_append_existing.txt")
!(claw:test-remove-if-exists "runtime/test_claw_append_missing.txt")

!(assertEqual
  (claw:run (append-file "runtime/test_claw_append_missing.txt" "no create"))
  (AppendMissingFile "runtime/test_claw_append_missing.txt"))

!(assertEqual
  (fs:exists "runtime/test_claw_append_missing.txt")
  False)

!(assertEqual
  (claw:run (write-file "runtime/test_claw_append_existing.txt" "alpha"))
  (Wrote "runtime/test_claw_append_existing.txt"))

!(assertEqual
  (claw:run (append-file "runtime/test_claw_append_existing.txt" "beta"))
  (Appended "runtime/test_claw_append_existing.txt"))

!(assertEqual
  (fs:read-text "runtime/test_claw_append_existing.txt")
  "alphabeta")

!(assertEqual
  (claw:run (read-file "runtime/test_claw_missing_read.txt"))
  (ReadMissingFile "runtime/test_claw_missing_read.txt"))

!(assertEqual
  (claw:test-write-failed?
    (claw:run (write-file "runtime/test_claw_missing_dir/out.txt" "x")))
  True)

!(fs:mkdirs "runtime/test_claw_append_dir")

!(assertEqual
  (claw:test-append-failed?
    (claw:run (append-file "runtime/test_claw_append_dir" "x")))
  True)

;; The prompt tells the model to quote every argument, so (rest seconds) must
;; accept a decimal string just like Pettaclaw's Python int(...) path.
!(assertEqual
  (claw:run (rest "60"))
  (Resting loops-left 0 sleep-ms 60000))

!(assertEqual (get-state &loops) 0)
!(assertEqual (get-state &sleep-ms) 60000)

!(change-state! &loops 3)
!(change-state! &sleep-ms 1000)

!(assertEqual
  (claw:run (rest 2))
  (Resting loops-left 0 sleep-ms 2000))

!(change-state! &loops 3)
!(change-state! &sleep-ms 1000)

!(assertEqual
  (claw:run (rest "abc"))
  (RestInvalidSeconds "abc"))

!(assertEqual (get-state &loops) 3)
!(assertEqual (get-state &sleep-ms) 1000)

;; Agent-written MeTTa must not run in-process. A good expression returns real
;; CeTTa output; malformed input is reported as data instead of breaking the
;; live loop.
!(assertEqual
  (claw:run (metta "(+ 1 2)"))
  (MettaOk "[3]\n"))

!(assertEqual
  (claw:run (metta "(bad"))
  (MettaFailed 1 "error: could not read /dev/stdin\n"))
