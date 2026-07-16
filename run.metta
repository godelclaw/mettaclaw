;; Ordinary local entrypoint. The live service uses the bounded, transactional
;; entrypoint; this one still initializes every state cell before one turn.
!(import! &self ./lib_cettaclaw.metta)
!(claw:init 22 ())
!(claw:mettaclaw 1)
