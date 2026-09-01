;; The fuel discipline crosses the Python boundary as a usable integer.
;; (Read-only: the probe never switches the persisted discipline, so it
;; exercises whatever is configured, and the saturate assertions below hold
;; for the default.)
!(import! &self (library lib_import))
!(import! &self ./src/utils)
!(import! &self ./src/weak_process_core)
!(import! &self ./src/open_assemblage)
!(import! &self ./src/loop_policy)

(= (assertEqual $A $B) (assert (== $A $B)))

!(let* (($grant (policy-burst-budget agent))
        ($_ (assertEqual $grant 50))
        ;; A renewal never grants less than the offered burst, whatever the
        ;; discipline and whatever is held.
        ($fresh (py-call (fuel_modes.refuel 0 $grant)))
        ($_ (assert (>= $fresh $grant)))
        ($held (py-call (fuel_modes.refuel 30 $grant)))
        ($_ (assert (>= $held $grant)))
        ($topped (py-call (fuel_modes.refuel 200 $grant)))
        ($_ (assert (>= $topped $grant)))
        ;; The result is an integer the periphery can carry.
        ($periphery (coordinate loops 7 coordinates-empty))
        ($refuelled (coordinate-set loops $held $periphery))
        ($_ (assertEqual (loop-budget $refuelled) $held))
        ;; A malformed boundary value degrades to 0 rather than raising.
        ($_ (assertEqual (py-call (fuel_modes.refuel "x" "y")) 0))
        ($name (py-call (fuel_modes.current_fuel)))
        ($_ (println! (ACTIVE_FUEL $name))))
     (println! FUEL_POLICY_OK))
