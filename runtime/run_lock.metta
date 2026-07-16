;; runtime/run_lock.metta — single-writer run lock for the live driver.
;; A create-exclusive lock file (fs:write-new-text) ensures only one live loop
;; runs against a given bot/offset at a time. Path is CETTACLAW_RUN_LOCK_PATH or
;; ~/.config/cettaclaw/run.lock.
!(import! &self fs)
!(import! &self str)
!(import! &self system)
!(import! &self time)
!(import! &self ../src/config.metta)

(= (claw:live-run-lock-path)
   (let $p (claw:setting "CETTACLAW_RUN_LOCK_PATH")
        (if (== $p NotFound)
            (str:concat (claw:home) "/.config/cettaclaw/run.lock")
            $p)))

(= (claw:live-run-lock-record)
   (str:concat "cettaclaw run_id="
     (str:concat (system:getenv-or-default "CETTACLAW_RUN_ID" "unset")
       (str:concat " since " (time:time-string)))))

(= (claw:live-acquire-run-lock-to-path $path)
       (case (once (eval (claw:live-run-lock-record)))
     (($record
       (case (once (fs:write-new-text $path $record))
         ((() (RunLockAcquired $path))
          (AlreadyExists (RunLockBusy $path AlreadyExists))
          ($err (RunLockBusy $path $err))))))))

(= (claw:live-acquire-run-lock)
   (claw:live-acquire-run-lock-to-path (claw:live-run-lock-path)))

(= (claw:live-release-run-lock-to-path $path)
   (case (once (catch (fs:remove $path)))
     (((catch ()) (RunLockReleased $path))
      (() (RunLockReleased $path))
      ($err (RunLockReleaseFailed $path $err)))))

(= (claw:live-release-run-lock)
   (claw:live-release-run-lock-to-path (claw:live-run-lock-path)))
