!(import! &self ../src/value.metta)
!(import! &self ../src/text.metta)
!(import! &self ../src/wire.metta)

;; numeric
!(assertEqual (claw:max 3 7) 7)
!(assertEqual (claw:min 3 7) 3)

;; safe-text round-trips (newline / quote / apostrophe)
!(assertEqual (claw:encode-safe "a\nb") "a_newline_b")
!(assertEqual (claw:decode-safe "a_newline_b") "a\nb")
!(assertEqual (claw:decode-safe (claw:encode-safe "he said \"hi\" it's ok"))
              "he said \"hi\" it's ok")
!(assertEqual (claw:decode-repr-quotes "he said \\\"hi\\\"")
              "he said \"hi\"")

;; balance-parens normalizes to exactly (( ... ))
!(assertEqual (claw:balance-parens "(foo bar)") "((foo bar))")
!(assertEqual (claw:balance-parens "  (((foo bar)))  ") "((foo bar))")
!(assertEqual (claw:balance-parens "foo bar") "((foo bar))")
!(assertEqual
  (claw:balance-parens "((write-file \"demo.py\" \"print('(kept)')\"))\n⋄⟨Cn:.7⟩")
  "((write-file \"demo.py\" \"print('(kept)')\"))")
!(assertEqual
  (claw:balance-parens "prose (is not a command boundary)")
  "((prose (is not a command boundary))")
!(assertEqual
  (claw:strip-trailing-affect "((write-file \"note\" \"diamond ⋄ stays\"))")
  "((write-file \"note\" \"diamond ⋄ stays\"))")
!(assertEqual
  (claw:strip-trailing-affect "((pin \"x\"))\n⋄⟨Cn:.7")
  "((pin \"x\"))\n⋄⟨Cn:.7")
!(assertEqual
  (claw:strip-trailing-affect "⋄⟨Cn:.7⟩\n((pin \"x\"))")
  "⋄⟨Cn:.7⟩\n((pin \"x\"))")
!(assertEqual (claw:balance-parens "((send \\\"hi\\\"))")
              "((send \"hi\"))")

;; last-chars window
!(assertEqual (claw:last-chars "abcdef" 3) "def")
!(assertEqual (claw:last-chars "ab" 5) "ab")
