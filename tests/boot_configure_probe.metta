;; The live start path, up to the first iteration, without starting the loop.
;; Run before switching engines:
;;   METTACLAW_SKIP_INITIALIZE=1 METTACLAW_ENGINE=cetta CETTA_BIN=<bin> \
;;     bash run.sh tests/boot_configure_probe.metta
;; An engine that reads an empty value after configure leaves initLoop empty,
;; so the live loop never starts and the process exits before its first turn.
!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

(= (assertEqual $A $B) (assert (== $A $B)))
(= (nonempty $x) (not (== $x ())))

!(configure sleepInterval 1)
!(assertEqual (collapse (sleepInterval)) (1))
!(assert (nonempty (collapse (initialPeriphery))))
!(assert (nonempty (collapse (initLoop))))
!(assertEqual (loop-iteration (process-periphery (initLoop))) 1)
!(println! boot-configure-probe-passed)
