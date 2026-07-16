;; src/utils.metta — shared helpers for the CeTTaClaw agent core.
;;
;; Mirrors the ROLE of pettaclaw-godel/src/utils.metta (small cross-cutting
;; helpers). The string / number / time primitives it wrapped in Prolog are
;; CeTTa interfaces (str, time) or focused src helpers, so this file keeps only
;; the message algebra the loop and channels share, plus the pre-LLM sleep seam.


;; ---- message algebra ------------------------------------------------------
;; A message is legacy (Msg $sender $text) or keyed (Msg $sender $key $text),
;; with $sender in {human, bot}. Real Telegram messages carry update_id as the
;; key so repeated identical texts still count as new (this drives the &prevmsg
;; dedup, exactly as pettaclaw's (repr (receive)) != &prevmsg comparison did).
(= (claw:is-human $msg)
   (case $msg
     (((Msg human $t) True)
      ((Msg human $key $t) True)
      ((Msg (human $id) $t) True)
      ((Msg (human $id) $key $t) True)
      ($other False))))

;; Sender user id for rich live messages; "" for legacy/offline fixtures.
(= (claw:msg-from-id $msg)
   (case $msg
     (((Msg (human $id) $t) $id)
      ((Msg (human $id) $key $t) $id)
      ($other ""))))
(= (claw:msg-key $msg)
   (case $msg
     (((Msg $s $key $t) $key)
      ((Msg $s $t) $t)
      ($other ""))))
(= (claw:msg-text $msg)
   (case $msg
     (((Msg $s $key $t) $t)
      ((Msg $s $t) $t)
      ($other ""))))

;; ---- sleep seam -----------------------------------------------------------
;; Pre-LLM: count instead of blocking so offline goldens are instant. The live
;; driver (runtime/) swaps this for (time:sleep-ms $ms).
(= (claw:sleep $ms)
   (let $_ (change-state! &sleep-count (+ 1 (get-state &sleep-count)))
        (Slept $ms)))
